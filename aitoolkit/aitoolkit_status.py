#!/usr/bin/env python3

import os
import re
import json
import time
import math
import glob
import sqlite3
import subprocess
from typing import List, Tuple, Optional, Dict

# ============================================================
# ENV CONFIG
# ============================================================

OUTPUT_DIR = os.environ.get("AI_TOOLKIT_OUTPUT_DIR", os.getcwd())
DB_PATH = os.environ.get("AI_TOOLKIT_LOSS_DB", os.path.join(OUTPUT_DIR, "loss_log.db"))
SAMPLES_DIR = os.environ.get("AI_TOOLKIT_SAMPLES_DIR", os.path.join(OUTPUT_DIR, "samples"))
RUN_TITLE = os.environ.get("RUN_TITLE", os.path.basename(os.path.abspath(OUTPUT_DIR)))

INTERVAL_MIN = int(os.environ.get("INTERVAL_MIN", "30"))
ROLLING_N = int(os.environ.get("ROLLING_N", "200"))
EMA_ALPHA = float(os.environ.get("EMA_ALPHA", "0.10"))
SLOPE_N = int(os.environ.get("SLOPE_N", "500"))
SPEED_N = int(os.environ.get("SPEED_N", "300"))

PLATEAU_ABS_PER_1K = float(os.environ.get("PLATEAU_ABS_PER_1K", "0.0015"))
SPIKE_MULT = float(os.environ.get("SPIKE_MULT", "2.0"))

SLOPE_FLAT_PER_1K = float(os.environ.get("SLOPE_FLAT_PER_1K", "0.0015"))
SLOPE_BAD_PER_1K  = float(os.environ.get("SLOPE_BAD_PER_1K", "0.004"))

MAX_STEPS = int(os.environ.get("MAX_STEPS", "0"))

TG_ENABLED = os.environ.get("TELEGRAM_ENABLE", "1") != "0"
TG_BIN = os.environ.get("TELEGRAM_SEND_BIN", "telegram-send")
TELEGRAM_PRE = os.environ.get("TELEGRAM_PRE", "1") != "0"

SEND_STARTUP = os.environ.get("SEND_STARTUP", "1") != "0"
ERROR_HEARTBEAT_MIN = int(os.environ.get("ERROR_HEARTBEAT_MIN", "10"))

LOSS_KEY = os.environ.get("LOSS_KEY", "loss/loss")
LR_KEY = os.environ.get("LR_KEY", "learning_rate")

TELEGRAM_SAMPLES = os.environ.get("TELEGRAM_SAMPLES", "0") != "0"
TELEGRAM_SAMPLES_EVERY_RAW = os.environ.get("TELEGRAM_SAMPLES_EVERY", "auto")
TELEGRAM_SAMPLES_MAX = int(os.environ.get("TELEGRAM_SAMPLES_MAX", "4"))
TELEGRAM_SAMPLES_STEP_MODE = os.environ.get("TELEGRAM_SAMPLES_STEP", "latest")
TELEGRAM_SAMPLES_ON_STATUS = os.environ.get("TELEGRAM_SAMPLES_ON_STATUS", "0") != "0"

STATE_PATH = os.path.join(OUTPUT_DIR, ".status_state.json")

# ============================================================
# UTIL
# ============================================================

def run_cmd(cmd: List[str]) -> Tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return 0, out.strip()
    except subprocess.CalledProcessError as e:
        return e.returncode, e.output or ""
    except FileNotFoundError:
        return 127, ""

def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def tg_send(msg: str):
    if not TG_ENABLED:
        print(msg)
        return
    if TELEGRAM_PRE:
        msg = f"<pre>{html_escape(msg)}</pre>"
        run_cmd([TG_BIN, "--format", "html", msg])
    else:
        run_cmd([TG_BIN, msg])

def tg_send_images(paths: List[str], caption: str):
    if not TG_ENABLED or not paths:
        return
    run_cmd([TG_BIN, "-i", *paths, "--caption", caption])

def fmt(x, n=6):
    if x is None:
        return "n/a"
    return f"{x:.{n}f}"

def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except:
        return {}

def save_state(s):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, STATE_PATH)

# ============================================================
# MATH
# ============================================================

def ema(values, alpha):
    if not values:
        return None
    e = values[0]
    for v in values[1:]:
        e = alpha * v + (1 - alpha) * e
    return e

def slope(xs, ys):
    if len(xs) < 2:
        return None
    xm = sum(xs)/len(xs)
    ym = sum(ys)/len(ys)
    num = sum((x-xm)*(y-ym) for x,y in zip(xs,ys))
    den = sum((x-xm)**2 for x in xs)
    if den == 0:
        return None
    return num/den

def steps_per_min(points):
    if len(points) < 2:
        return None
    s0,t0 = points[0]
    s1,t1 = points[-1]
    dt = t1 - t0
    if dt <= 0:
        return None
    return (s1-s0)/dt*60

def eta(step, spm):
    if MAX_STEPS <= 0 or spm is None or spm <= 0:
        return None
    rem = MAX_STEPS-step
    if rem <= 0:
        return "done"
    mins = rem/spm
    if mins < 60:
        return f"{mins:.0f}m"
    return f"{mins/60:.1f}h"

# ============================================================
# DB
# ============================================================

def db_latest(conn):
    row = conn.execute("""
        SELECT s.step, s.wall_time,
        (SELECT value_real FROM metrics WHERE step=s.step AND key=?),
        (SELECT value_real FROM metrics WHERE step=s.step AND key=?)
        FROM steps s ORDER BY s.step DESC LIMIT 1
    """,(LOSS_KEY,LR_KEY)).fetchone()

    if not row:
        return None
    return {"step":row[0], "time":row[1], "loss":row[2], "lr":row[3]}

def db_recent_loss(conn,n):
    rows = conn.execute("""
        SELECT s.step, s.wall_time, m.value_real
        FROM steps s JOIN metrics m
        ON m.step=s.step AND m.key=?
        ORDER BY s.step DESC LIMIT ?
    """,(LOSS_KEY,n)).fetchall()
    return list(reversed(rows))

def db_recent_steps(conn,n):
    rows = conn.execute("""
        SELECT step, wall_time FROM steps
        ORDER BY step DESC LIMIT ?
    """,(n,)).fetchall()
    return list(reversed(rows))

# ============================================================
# SAMPLES
# ============================================================

STEP_RE = re.compile(r"__0*(\d+)_")

def latest_sample_step():
    if not os.path.isdir(SAMPLES_DIR):
        return None
    steps=set()
    for f in os.listdir(SAMPLES_DIR):
        m=STEP_RE.search(f)
        if m:
            steps.add(int(m.group(1)))
    if not steps:
        return None
    return max(steps)

def sample_images(step):
    if step is None:
        return []
    return sorted(glob.glob(os.path.join(SAMPLES_DIR,f"*__{step:09d}_*.jpg")))[:TELEGRAM_SAMPLES_MAX]

# ============================================================
# YAML sample_every
# ============================================================

def yaml_sample_every():
    if TELEGRAM_SAMPLES_EVERY_RAW!="auto":
        try:
            return int(TELEGRAM_SAMPLES_EVERY_RAW)
        except:
            return 0

    for p in ["training_config.yaml","config.yaml"]:
        fp=os.path.join(OUTPUT_DIR,p)
        if os.path.exists(fp):
            try:
                import yaml
                d=yaml.safe_load(open(fp))
                return d.get("sample",{}).get("sample_every",0)
            except:
                pass
    return 0

# ============================================================
# STATUS
# ============================================================

def status_once():
    if not os.path.exists(DB_PATH):
        return "DB_NOT_READY"

    conn = sqlite3.connect(DB_PATH)

    latest = db_latest(conn)
    if not latest:
        return "DB_NOT_READY"

    pts = db_recent_loss(conn,ROLLING_N)
    losses=[p[2] for p in pts if p[2] is not None]
    avg=minv=maxv=None
    if losses:
        avg=sum(losses)/len(losses)
        minv=min(losses)
        maxv=max(losses)

    ema_v=ema(losses,EMA_ALPHA)

    slope_pts=db_recent_loss(conn,SLOPE_N)
    if len(slope_pts)>=2:
        xs=[p[0] for p in slope_pts]
        ys=[p[2] for p in slope_pts]
        s=slope(xs,ys)
    else:
        s=None

    slope_1k = None if s is None else s*1000
    
    plateau = None
    if slope_1k is not None:
        plateau = abs(slope_1k) < PLATEAU_ABS_PER_1K
    plateau_txt = "n/a" if plateau is None else ("YES" if plateau else "no")
    
    # trend
    trend="❓"
    if slope_1k is not None:
        if slope_1k <= -SLOPE_FLAT_PER_1K:
            trend="✅"
        elif abs(slope_1k)<SLOPE_FLAT_PER_1K:
            trend="🟨"
        elif slope_1k>=SLOPE_BAD_PER_1K:
            trend="🚨"
        else:
            trend="↗️"

    # spike
    spike=False
    if latest["loss"] and avg:
        spike = latest["loss"] > avg*SPIKE_MULT

    # speed
    spm=steps_per_min(db_recent_steps(conn,SPEED_N))
    eta_txt=eta(latest["step"],spm)

    progress=""
    if MAX_STEPS>0:
        progress=f"{latest['step']}/{MAX_STEPS} ({latest['step']/MAX_STEPS*100:.1f}%)"

    progress_txt = f" | {progress}" if progress else ""
    eta_out = eta_txt if eta_txt else "n/a"

    msg = "\n".join([
        f"🧪 {RUN_TITLE}",
        (
            f"Step {latest['step']} | "
            f"Loss {fmt(latest['loss'])}{' ⚠️SPIKE' if spike else ''} | "
            f"EMA(α={EMA_ALPHA}) {fmt(ema_v)} | "
            f"LR {fmt(latest['lr'], 8)}"
            f"{progress_txt}"
        ),
        f"Rolling({ROLLING_N}): avg={fmt(avg)}  min={fmt(minv)}  max={fmt(maxv)}",
        (
            f"{trend} Trend | "
            f"Slope({SLOPE_N}): {fmt(slope_1k)} /1k | "
            f"Plateau<{PLATEAU_ABS_PER_1K}: {plateau_txt}"
        ),
        f"Speed({SPEED_N}): {fmt(spm, 2)} step/min | ETA: {eta_out}",
        f"Time: {now_str()}",
    ])
    
    # samples
    if TELEGRAM_SAMPLES:
        se=yaml_sample_every()
        if TELEGRAM_SAMPLES_ON_STATUS or (se and latest["step"]%se==0):
            step=latest_sample_step()
            imgs=sample_images(step)
            if imgs:
                tg_send_images(imgs,f"{RUN_TITLE} step {step}")

    tg_send(msg)
    return "OK"

# ============================================================
# LOOP
# ============================================================

def startup_message():
    msg="\n".join([
        "🧪 AI-Toolkit monitor started",
        f"Run: {RUN_TITLE}",
        f"Interval: {INTERVAL_MIN} min",
        f"DB: {DB_PATH}",
        f"Host: {os.uname().nodename}",
        f"Time: {now_str()}",
    ])
    tg_send(msg)

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--loop",action="store_true")
    args=ap.parse_args()

    if args.loop:
        if SEND_STARTUP:
            startup_message()

        state=load_state()
        last_err_ts=state.get("last_err_ts",0)

        while True:
            res=status_once()
            if res=="DB_NOT_READY":
                now=time.time()
                if now-last_err_ts>ERROR_HEARTBEAT_MIN*60:
                    tg_send(f"Monitor alive — waiting for DB: {DB_PATH}")
                    state["last_err_ts"]=now
                    save_state(state)
            time.sleep(INTERVAL_MIN*60)
    else:
        status_once()

if __name__=="__main__":
    main()

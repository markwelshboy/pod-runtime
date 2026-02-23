#!/usr/bin/env python3
"""
AI-Toolkit training monitor (SQLite loss_log.db + Telegram):
- Reads loss + lr from loss_log.db (steps/metrics tables)
- Rolling stats, EMA smoothing, slope (linear regression), plateau detection
- Speed (steps/min) and ETA if MAX_STEPS is set
- Optional spike detection (loss vs rolling average)
- Sends Telegram status via telegram-send
- Optional: sends sample images on cadence from YAML (sample.sample_every) or override

Telegram formatting:
- If TELEGRAM_PRE=1 (default), wraps message in <pre>...</pre> and sends with --format html
"""

import os
import re
import json
import time
import math
import glob
import sqlite3
import subprocess
from typing import List, Tuple, Optional, Dict

# ----------------------------
# Config (env)
# ----------------------------
OUTPUT_DIR = os.environ.get("AI_TOOLKIT_OUTPUT_DIR", os.getcwd())
DB_PATH = os.environ.get("AI_TOOLKIT_LOSS_DB", os.path.join(OUTPUT_DIR, "loss_log.db"))
SAMPLES_DIR = os.environ.get("AI_TOOLKIT_SAMPLES_DIR", os.path.join(OUTPUT_DIR, "samples"))

RUN_TITLE = os.environ.get("RUN_TITLE", os.path.basename(os.path.abspath(OUTPUT_DIR)))

INTERVAL_MIN = int(os.environ.get("INTERVAL_MIN", "30"))  # for --loop
ROLLING_N = int(os.environ.get("ROLLING_N", "100"))
EMA_ALPHA = float(os.environ.get("EMA_ALPHA", "0.10"))  # 0<alpha<=1
SLOPE_N = int(os.environ.get("SLOPE_N", "300"))  # points for slope
SPEED_N = int(os.environ.get("SPEED_N", "300"))  # points for speed

# plateau threshold: abs(loss change) per 1000 steps (lower = stricter)
PLATEAU_ABS_PER_1K = float(os.environ.get("PLATEAU_ABS_PER_1K", "0.002"))

# Spike detection (current loss vs rolling avg)
SPIKE_MULT = float(os.environ.get("SPIKE_MULT", "2.0"))

# Alert gating
# always|interesting|bad
ALERT_MODE = os.environ.get("ALERT_MODE", "always").strip().lower()
BAD_JUMP_FRAC = float(os.environ.get("BAD_JUMP_FRAC", "0.25"))  # +25% vs last sent
MIN_STEP_ADVANCE = int(os.environ.get("MIN_STEP_ADVANCE", "1000"))

STATE_PATH = os.environ.get("STATE_PATH", os.path.join(OUTPUT_DIR, ".status_state.json"))

# Telegram
TG_ENABLED = os.environ.get("TELEGRAM_ENABLE", "1") != "0"
TG_BIN = os.environ.get("TELEGRAM_SEND_BIN", "telegram-send")

# Use <pre> monospace HTML formatting by default
TELEGRAM_PRE = os.environ.get("TELEGRAM_PRE", "1") != "0"

# Metric keys (confirmed in your DB)
LOSS_KEY = os.environ.get("LOSS_KEY", "loss/loss")
LR_KEY = os.environ.get("LR_KEY", "learning_rate")

# Optional total steps (ETA)
MAX_STEPS = int(os.environ.get("MAX_STEPS", "0"))  # 0 disables ETA

# Sample image sending
TELEGRAM_SAMPLES = os.environ.get("TELEGRAM_SAMPLES", "0") != "0"
TELEGRAM_SAMPLES_EVERY_RAW = os.environ.get("TELEGRAM_SAMPLES_EVERY", "auto").strip().lower()  # auto|<int>
TELEGRAM_SAMPLES_MAX = int(os.environ.get("TELEGRAM_SAMPLES_MAX", "4"))
TELEGRAM_SAMPLES_STEP_MODE = os.environ.get("TELEGRAM_SAMPLES_STEP", "latest").strip().lower()  # latest|nearest|exact
TELEGRAM_SAMPLES_INCLUDE_PROMPTS = os.environ.get("TELEGRAM_SAMPLES_INCLUDE_PROMPTS", "0") != "0"
TELEGRAM_SAMPLES_PROMPT_CHARS = int(os.environ.get("TELEGRAM_SAMPLES_PROMPT_CHARS", "140"))

# Send images whenever we send a status (uses latest sample step) if set
TELEGRAM_SAMPLES_ON_STATUS = os.environ.get("TELEGRAM_SAMPLES_ON_STATUS", "0") != "0"

# ----------------------------
# Helpers
# ----------------------------
def fmt_time_unix(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

def fmt_num(x: Optional[float], nd: int = 6) -> str:
    if x is None:
        return "n/a"
    try:
        if math.isnan(x) or math.isinf(x):
            return "n/a"
    except Exception:
        pass
    return f"{x:.{nd}f}"

def run_cmd(cmd: List[str]) -> Tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return 0, out.strip()
    except subprocess.CalledProcessError as e:
        return e.returncode, (e.output or "").strip()
    except FileNotFoundError:
        return 127, ""

def html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )

def send_telegram_text(msg: str) -> None:
    if not TG_ENABLED:
        print(msg)
        return

    if TELEGRAM_PRE:
        # HTML <pre> requires escaping
        payload = f"<pre>{html_escape(msg)}</pre>"
        cmd = [TG_BIN, "--format", "html", payload]
    else:
        cmd = [TG_BIN, msg]

    rc, out = run_cmd(cmd)
    if rc != 0:
        # fallback to stdout
        print(msg)
        if out:
            print(f"[telegram-send error] {out}")

def sample_count() -> int:
    if not os.path.isdir(SAMPLES_DIR):
        return 0
    cnt = 0
    for root, _, files in os.walk(SAMPLES_DIR):
        cnt += sum(1 for f in files if not f.startswith("."))
    return cnt

def load_state() -> Dict:
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(st: Dict) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)

# ----------------------------
# Math
# ----------------------------
def ema(values: List[float], alpha: float) -> Optional[float]:
    if not values:
        return None
    e = values[0]
    for v in values[1:]:
        e = alpha * v + (1 - alpha) * e
    return e

def linear_regression_slope(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    num = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    den = sum((x - xbar) * (x - xbar) for x in xs)
    if den == 0:
        return None
    return num / den  # loss per step

def steps_per_min(points: List[Tuple[int, float]]) -> Optional[float]:
    if len(points) < 2:
        return None
    s0, t0 = points[0]
    s1, t1 = points[-1]
    dt = t1 - t0
    ds = s1 - s0
    if dt <= 0 or ds <= 0:
        return None
    return (ds / dt) * 60.0

def plateau_flag(slope_per_step: Optional[float]) -> Optional[bool]:
    if slope_per_step is None:
        return None
    per_1k = abs(slope_per_step) * 1000.0
    return per_1k < PLATEAU_ABS_PER_1K

def eta_str(step: int, spm: Optional[float]) -> Optional[str]:
    if MAX_STEPS <= 0 or spm is None or spm <= 0:
        return None
    remaining = MAX_STEPS - step
    if remaining <= 0:
        return "done"
    mins = remaining / spm
    if mins < 60:
        return f"{mins:.0f} min"
    hrs = mins / 60
    if hrs < 48:
        return f"{hrs:.1f} h"
    days = hrs / 24
    return f"{days:.1f} d"

# ----------------------------
# DB Queries (schema-aware)
# ----------------------------
def get_latest(conn: sqlite3.Connection) -> Dict:
    row = conn.execute(
        """
        SELECT
          s.step,
          s.wall_time,
          (SELECT value_real FROM metrics WHERE step=s.step AND key=?),
          (SELECT value_real FROM metrics WHERE step=s.step AND key=?)
        FROM steps s
        ORDER BY s.step DESC
        LIMIT 1
        """,
        (LOSS_KEY, LR_KEY),
    ).fetchone()

    if not row:
        return {"step": None, "wall_time": None, "loss": None, "lr": None}

    step, wall_time, loss, lr = row
    return {
        "step": int(step),
        "wall_time": float(wall_time),
        "loss": float(loss) if loss is not None else None,
        "lr": float(lr) if lr is not None else None,
    }

def get_recent_loss_points(conn: sqlite3.Connection, n: int) -> List[Tuple[int, float, float]]:
    rows = conn.execute(
        """
        SELECT s.step, s.wall_time, m.value_real
        FROM steps s
        JOIN metrics m ON m.step=s.step AND m.key=?
        ORDER BY s.step DESC
        LIMIT ?
        """,
        (LOSS_KEY, n),
    ).fetchall()
    rows = list(reversed(rows))
    out: List[Tuple[int, float, float]] = []
    for step, wall, loss in rows:
        if loss is None:
            continue
        out.append((int(step), float(wall), float(loss)))
    return out

def get_recent_step_times(conn: sqlite3.Connection, n: int) -> List[Tuple[int, float]]:
    rows = conn.execute(
        """
        SELECT step, wall_time
        FROM steps
        ORDER BY step DESC
        LIMIT ?
        """,
        (n,),
    ).fetchall()
    rows = list(reversed(rows))
    return [(int(s), float(t)) for (s, t) in rows]

def rolling_stats(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"avg": None, "min": None, "max": None}
    return {"avg": sum(values) / len(values), "min": min(values), "max": max(values)}

# ----------------------------
# YAML config lookup for sample cadence/prompts
# ----------------------------
_SAMPLE_RE = re.compile(r"^\d+__0*(\d+)_([0-9]+)\.(jpg|jpeg|png)$", re.IGNORECASE)

def find_training_yaml() -> Optional[str]:
    cands = [
        os.path.join(OUTPUT_DIR, "training_config.yaml"),
        os.path.join(OUTPUT_DIR, "config.yaml"),
        os.path.join(OUTPUT_DIR, "config", "config.yaml"),
    ]
    for p in cands:
        if os.path.exists(p):
            return p
    return None

def read_sample_block_from_yaml(path: str) -> Dict:
    # Try PyYAML first
    try:
        import yaml  # type: ignore
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        sample = data.get("sample") if isinstance(data, dict) else None
        out: Dict = {}
        if isinstance(sample, dict):
            se = sample.get("sample_every")
            if isinstance(se, int):
                out["sample_every"] = se
            elif isinstance(se, str) and se.isdigit():
                out["sample_every"] = int(se)

            prompts: List[str] = []
            smpls = sample.get("samples")
            if isinstance(smpls, list):
                for item in smpls:
                    if isinstance(item, dict) and isinstance(item.get("prompt"), str):
                        prompts.append(item["prompt"])
            out["prompts"] = prompts
        return out
    except Exception:
        pass

    # Fallback: indentation-aware scan for sample_every only
    try:
        in_sample = False
        sample_indent = None
        with open(path, "r") as f:
            for line in f:
                raw = line.rstrip("\n")
                if not raw.strip() or raw.lstrip().startswith("#"):
                    continue
                indent = len(raw) - len(raw.lstrip(" "))

                if raw.strip() == "sample:":
                    in_sample = True
                    sample_indent = indent
                    continue

                if in_sample:
                    if indent <= (sample_indent or 0) and ":" in raw:
                        in_sample = False
                        sample_indent = None
                        continue

                    m = re.match(r"^\s*sample_every\s*:\s*([0-9]+)\s*$", raw)
                    if m:
                        return {"sample_every": int(m.group(1)), "prompts": []}
    except Exception:
        pass

    return {}

def resolve_samples_every_and_prompts() -> Tuple[int, List[str]]:
    if TELEGRAM_SAMPLES_EVERY_RAW != "auto":
        try:
            return max(0, int(TELEGRAM_SAMPLES_EVERY_RAW)), []
        except Exception:
            return 0, []

    y = find_training_yaml()
    if not y:
        return 0, []
    blk = read_sample_block_from_yaml(y)
    se = int(blk.get("sample_every") or 0)
    prompts = blk.get("prompts") or []
    return (se if se > 0 else 0), prompts

def telegram_send_images(paths: List[str], caption: str) -> bool:
    """
    telegram-send 0.37 supports:
      telegram-send -i img1 img2 --caption "..."
    """
    if not TG_ENABLED:
        return False
    if not paths:
        return False

    # Caption: keep simple (Telegram captions may not render <pre>; this is fine)
    cap = caption
    cmd = [TG_BIN, "-i", *paths, "--caption", cap]
    rc, out = run_cmd(cmd)
    if rc == 0:
        return True

    # Fallback: try one-by-one
    ok_any = False
    for p in paths:
        rc2, _ = run_cmd([TG_BIN, "-i", p, "--caption", cap])
        ok_any = ok_any or (rc2 == 0)
    if not ok_any and out:
        print(f"[telegram-send image error] {out}")
    return ok_any

def list_sample_steps(samples_dir: str) -> List[int]:
    if not os.path.isdir(samples_dir):
        return []
    steps = set()
    for name in os.listdir(samples_dir):
        m = _SAMPLE_RE.match(name)
        if not m:
            continue
        steps.add(int(m.group(1)))
    return sorted(steps)

def pick_sample_step(current_step: int, mode: str, samples_dir: str) -> Optional[int]:
    steps = list_sample_steps(samples_dir)
    if not steps:
        return None
    if mode == "latest":
        return steps[-1]
    if mode == "exact":
        return current_step if current_step in steps else None
    # nearest: greatest <= current_step, else earliest
    chosen = None
    for s in steps:
        if s <= current_step:
            chosen = s
        else:
            break
    return chosen if chosen is not None else steps[0]

def sample_images_for_step(samples_dir: str, step: int, max_n: int) -> List[str]:
    pats = [
        os.path.join(samples_dir, f"*__{step:09d}_*.jpg"),
        os.path.join(samples_dir, f"*__{step:09d}_*.jpeg"),
        os.path.join(samples_dir, f"*__{step:09d}_*.png"),
    ]
    files: List[str] = []
    for p in pats:
        files.extend(glob.glob(p))

    def keyfn(p: str) -> int:
        base = os.path.basename(p)
        m = _SAMPLE_RE.match(base)
        return int(m.group(2)) if m else 999999

    files = sorted(set(files), key=keyfn)
    return files[:max_n]

def format_prompts(prompts: List[str], max_chars: int) -> str:
    if not prompts:
        return ""
    lines = []
    for i, p in enumerate(prompts[:4], 1):
        p = " ".join(p.split())
        if len(p) > max_chars:
            p = p[: max_chars - 1] + "…"
        lines.append(f"{i}) {p}")
    return "\n".join(lines)

# ----------------------------
# Alert gating
# ----------------------------
def should_send(state: Dict, latest_step: int, latest_loss: Optional[float], plateau: Optional[bool]) -> Tuple[bool, str]:
    if ALERT_MODE == "always":
        return True, "always"

    last = state.get("last_sent", {})
    last_step = last.get("step")
    last_loss = last.get("loss")
    last_plateau = last.get("plateau")

    reasons = []

    if last_loss is not None and latest_loss is not None and last_loss > 0:
        frac = (latest_loss - last_loss) / last_loss
        if frac >= BAD_JUMP_FRAC:
            reasons.append(f"loss jump +{frac * 100:.0f}%")

    if plateau is not None and last_plateau is not None and plateau != last_plateau:
        reasons.append("plateau changed")

    if last_step is None or (latest_step - int(last_step)) >= MIN_STEP_ADVANCE:
        reasons.append(f"step +{(0 if last_step is None else latest_step - int(last_step))}")

    if ALERT_MODE == "bad":
        ok = any(r.startswith("loss jump") for r in reasons)
        return ok, (", ".join(reasons) if ok else "no bad trigger")

    if ALERT_MODE == "interesting":
        ok = len(reasons) > 0
        return ok, (", ".join(reasons) if ok else "no interesting trigger")

    return True, "unknown mode"

# ----------------------------
# Main report
# ----------------------------
def run_once() -> int:
    if not os.path.exists(DB_PATH):
        print(f"ERROR: missing DB: {DB_PATH}")
        return 2

    conn = sqlite3.connect(DB_PATH)

    latest = get_latest(conn)
    if latest["step"] is None:
        print("ERROR: DB has no steps yet")
        return 3

    pts_roll = get_recent_loss_points(conn, ROLLING_N)
    pts_slope = get_recent_loss_points(conn, SLOPE_N)
    pts_speed = get_recent_step_times(conn, SPEED_N)

    roll_vals = [p[2] for p in pts_roll]
    roll = rolling_stats(roll_vals)
    ema_v = ema(roll_vals, EMA_ALPHA)

    # spike detection
    spike = False
    if latest["loss"] is not None and roll["avg"] is not None and roll["avg"] > 0:
        spike = latest["loss"] > (SPIKE_MULT * roll["avg"])
    spike_txt = " ⚠️SPIKE" if spike else ""

    spm = steps_per_min(pts_speed)
    eta = eta_str(latest["step"], spm)

    slope = None
    if len(pts_slope) >= 2:
        xs = [float(p[0]) for p in pts_slope]
        ys = [float(p[2]) for p in pts_slope]
        slope = linear_regression_slope(xs, ys)  # loss per step

    plateau = plateau_flag(slope)
    slope_1k = None if slope is None else slope * 1000.0

    SLOPE_FLAT_PER_1K = float(os.environ.get("SLOPE_FLAT_PER_1K", "0.0015"))
    SLOPE_BAD_PER_1K  = float(os.environ.get("SLOPE_BAD_PER_1K", "0.004"))

    trend = "❓"
    if slope_1k is not None:
        if slope_1k <= -SLOPE_FLAT_PER_1K:
            trend = "✅"
        elif abs(slope_1k) < SLOPE_FLAT_PER_1K:
            trend = "🟨"
        elif slope_1k >= SLOPE_BAD_PER_1K:
            trend = "🚨"
        else:
            trend = "↗️"

    samples_now = sample_count()
    state = load_state()
    last_samples = state.get("last_seen_samples")
    samples_delta = None if last_samples is None else max(0, samples_now - int(last_samples))

    send_ok, reason = should_send(state, latest["step"], latest["loss"], plateau)

    plateau_txt = "n/a" if plateau is None else ("YES" if plateau else "no")
    progress_txt = ""
    if MAX_STEPS > 0:
        pct = (latest["step"] / MAX_STEPS) * 100.0
        progress_txt = f" | Progress: {pct:.1f}% ({latest['step']}/{MAX_STEPS})"

    msg = "\n".join(
        [
            f"🧪 AI-Toolkit: {RUN_TITLE}",
            f"Step: {latest['step']} | Loss: {fmt_num(latest['loss'], 6)}{spike_txt} | EMA(α={EMA_ALPHA}): {fmt_num(ema_v, 6)} | LR: {fmt_num(latest['lr'], 8)}{progress_txt}",
            f"Rolling({ROLLING_N}): avg={fmt_num(roll['avg'], 6)}  min={fmt_num(roll['min'], 6)}  max={fmt_num(roll['max'], 6)}",
            f"{trend} Slope({SLOPE_N}): {fmt_num(slope_1k, 6)} loss/1k (negative=improving) | Plateau<{PLATEAU_ABS_PER_1K}: {plateau_txt}",
            f"Speed({SPEED_N}): {fmt_num(spm, 2)} steps/min" + (f" | ETA: {eta}" if eta else ""),
            f"Time: {fmt_time_unix(latest['wall_time'])}",
            f"Samples: {samples_now}" + (f" (+{samples_delta})" if samples_delta is not None and samples_delta > 0 else ""),
        ]
    )

    if ALERT_MODE != "always":
        msg += f"\nTrigger: {reason} (mode={ALERT_MODE})"

    # ---- optional: send sample images ----
    samples_every, sample_prompts = resolve_samples_every_and_prompts()
    send_images_now = (
        TELEGRAM_SAMPLES
        and TG_ENABLED
        and send_ok
        and (
            TELEGRAM_SAMPLES_ON_STATUS
            or (samples_every > 0 and (latest["step"] % samples_every == 0))
        )
    )

    if send_images_now:
        chosen_step = pick_sample_step(latest["step"], TELEGRAM_SAMPLES_STEP_MODE, SAMPLES_DIR)
        if chosen_step is not None:
            imgs = sample_images_for_step(SAMPLES_DIR, chosen_step, TELEGRAM_SAMPLES_MAX)
            if imgs:
                cap_lines = [
                    f"{RUN_TITLE}",
                    f"Samples @ step {chosen_step} (current {latest['step']}, cadence={samples_every or 'status'})",
                    f"loss={fmt_num(latest['loss'], 6)}  lr={fmt_num(latest['lr'], 8)}",
                ]
                if TELEGRAM_SAMPLES_INCLUDE_PROMPTS:
                    ptxt = format_prompts(sample_prompts, TELEGRAM_SAMPLES_PROMPT_CHARS)
                    if ptxt:
                        cap_lines.append("Prompts:")
                        cap_lines.append(ptxt)
                caption = "\n".join(cap_lines)

                ok_any = telegram_send_images(imgs, caption)
                if not ok_any:
                    msg += "\nSamples: (could not send images via telegram-send)\n" + "\n".join(
                        os.path.basename(x) for x in imgs
                    )
            else:
                msg += f"\nSamples: none found for step {chosen_step}"
        else:
            msg += "\nSamples: none found (no sample steps detected)"

    # Send main text status
    if send_ok:
        send_telegram_text(msg)
        state["last_sent"] = {"ts": time.time(), "step": latest["step"], "loss": latest["loss"], "plateau": plateau}
    else:
        print(f"[not sent] {reason}\n{msg}")

    state["last_seen_samples"] = samples_now
    save_state(state)
    return 0

def main():
    import argparse

    ap = argparse.ArgumentParser(description="AI-Toolkit loss monitor (Telegram)")
    ap.add_argument("--loop", action="store_true", help="run forever, send every INTERVAL_MIN minutes")
    args = ap.parse_args()

    if args.loop:
        while True:
            rc = run_once()
            if rc != 0:
                time.sleep(60)
            time.sleep(INTERVAL_MIN * 60)
    else:
        raise SystemExit(run_once())

if __name__ == "__main__":
    main()

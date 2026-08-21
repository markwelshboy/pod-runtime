#!/usr/bin/env python3
from __future__ import annotations

import subprocess

from sl_lib.cli import main
from sl_lib.common import SlError, die

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SlError as exc:
        die(str(exc), 1)
    except subprocess.CalledProcessError as exc:
        die(f"command failed with exit status {exc.returncode}", exc.returncode or 1)
    except KeyboardInterrupt:
        die("interrupted", 130)

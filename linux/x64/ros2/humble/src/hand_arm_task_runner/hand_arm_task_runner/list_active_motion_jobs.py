from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def _format_duration(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    mins = int(seconds // 60)
    secs = seconds - mins * 60
    return f"{mins}m{secs:.1f}s"


def _load_status(path: Path) -> dict:
    if not path.exists():
        return {"running": False, "note": f"status file not found: {path}"}
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise RuntimeError("status payload is not an object")
    return raw


def _print_status(path: Path) -> None:
    now_epoch = time.time()
    now_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_epoch))
    status = _load_status(path)

    print("=" * 72)
    print(f"[{now_text}] active motion status")
    print(f"status_file: {path}")

    if status.get("running"):
        started_epoch = float(status.get("started_epoch", now_epoch))
        elapsed = max(0.0, now_epoch - started_epoch)
        print("running: YES")
        print(f"run_id: {status.get('run_id', 'N/A')}")
        print(f"action_name: {status.get('action_name', 'N/A')}")
        print(f"started_at: {status.get('started_at', 'N/A')}")
        print(f"elapsed: {_format_duration(elapsed)}")
    else:
        print("running: NO")
        last_run = status.get("last_run", {})
        if isinstance(last_run, dict) and last_run:
            print(f"last_run_id: {last_run.get('run_id', 'N/A')}")
            print(f"last_action: {last_run.get('action_name', 'N/A')}")
            print(f"last_status: {last_run.get('status', 'N/A')}")
            print(f"last_elapsed: {_format_duration(float(last_run.get('elapsed_sec', 0.0)))}")
            print(f"last_started_at: {last_run.get('started_at', 'N/A')}")
            print(f"last_finished_at: {last_run.get('finished_at', 'N/A')}")
            err = str(last_run.get("error", "")).strip()
            if err:
                print(f"last_error: {err}")
        note = str(status.get("note", "")).strip()
        if note:
            print(f"note: {note}")

    print(f"updated_at: {status.get('updated_at', 'N/A')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print current GUI-issued task/motion status from runtime state file."
    )
    parser.add_argument(
        "--status-file",
        default="runtime/active_motion.json",
        help="Path to runtime status JSON. Default: runtime/active_motion.json",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch mode. Refresh status periodically.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Watch refresh interval in seconds. Default: 1.0",
    )
    args = parser.parse_args()

    status_path = Path(args.status_file).expanduser().resolve()
    interval = max(0.2, float(args.interval))

    if not args.watch:
        _print_status(status_path)
        return

    try:
        while True:
            _print_status(status_path)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nwatch stopped by user")


if __name__ == "__main__":
    main()

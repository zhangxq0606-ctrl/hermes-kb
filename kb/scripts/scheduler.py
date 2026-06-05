import os
import sys
import subprocess
import logging
import argparse
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler

TZ = timezone(timedelta(hours=8))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SCHEDULER_LOG = os.path.join(LOGS_DIR, "scheduler.log")
MAIN_PY_PATH = os.path.join(BASE_DIR, "main.py")

os.makedirs(LOGS_DIR, exist_ok=True)

scheduler_logger = logging.getLogger("scheduler")
scheduler_logger.setLevel(logging.INFO)
scheduler_logger.propagate = False
fh = logging.FileHandler(SCHEDULER_LOG, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(message)s"))
if not scheduler_logger.handlers:
    scheduler_logger.addHandler(fh)


def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    scheduler_logger.info(line)
    print(line)


def run_main():
    log("TASK_START: Starting pipeline execution")
    try:
        result = subprocess.run(
            [sys.executable, MAIN_PY_PATH],
            capture_output=True,
            text=True,
            cwd=BASE_DIR,
            timeout=600,
        )
        if result.returncode == 0:
            log("TASK_SUCCESS: Pipeline completed successfully")
        else:
            log(f"TASK_FAILED: Pipeline exited with code {result.returncode}")
            if result.stderr:
                log(f"TASK_ERROR: {result.stderr.strip()[:500]}")
    except subprocess.TimeoutExpired:
        log("TASK_TIMEOUT: Pipeline execution timed out")
    except Exception as e:
        log(f"TASK_EXCEPTION: {str(e)}")
    log("TASK_END: Pipeline execution finished")


def check_main_py():
    if not os.path.isfile(MAIN_PY_PATH):
        log(f"ERROR: main.py not found at {MAIN_PY_PATH}")
        print(f"ERROR: main.py not found at {MAIN_PY_PATH}")
        return False
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", MAIN_PY_PATH],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log(f"ERROR: main.py has syntax errors: {result.stderr}")
            print(f"ERROR: main.py has syntax errors")
            return False
    except Exception as e:
        log(f"ERROR: Failed to check main.py: {str(e)}")
        print(f"ERROR: Failed to check main.py: {str(e)}")
        return False
    
    log(f"OK: main.py is ready at {MAIN_PY_PATH}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Xq.KB Pipeline Scheduler")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run pipeline once and exit (test mode)"
    )
    args = parser.parse_args()

    if not check_main_py():
        sys.exit(1)

    if args.test:
        log("TEST_MODE: Running pipeline once")
        run_main()
        log("TEST_MODE: Exiting")
        return

    log("SCHEDULER_START: Starting scheduler")
    
    scheduler = BlockingScheduler(timezone=str(TZ))
    
    scheduler.add_job(
        run_main,
        "cron",
        hour=20,
        day="*/2",
        id="hermes_pipeline",
        name="Xq.KB Pipeline",
        replace_existing=True,
    )
    
    log("SCHEDULER_JOB_REGISTERED: Job scheduled - cron: 0 20 */2 * * (every 2 days at 20:00)")
    log("SCHEDULER_READY: Scheduler is running. Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log("SCHEDULER_STOP: Scheduler stopped")


if __name__ == "__main__":
    main()
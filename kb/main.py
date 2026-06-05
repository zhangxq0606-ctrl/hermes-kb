import os
import sys
import json
import subprocess
import logging
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
MAIN_LOG = os.path.join(LOGS_DIR, "main.log")

STEPS = [
    {"name": "BOOTSTRAP", "script": "bootstrap.py", "parse_json": True, "critical": True},
    {"name": "HERMES_ENGINE", "script": "hermes_engine.py", "parse_json": True, "critical": False},
    {"name": "INDEX_GUARD", "script": "index_guard.py", "parse_json": True, "critical": False},
    {"name": "WEEKLY_SCAN", "script": "weekly_scan.py", "parse_json": False, "critical": False},
]

os.makedirs(LOGS_DIR, exist_ok=True)

main_logger = logging.getLogger("main")
main_logger.setLevel(logging.INFO)
main_logger.propagate = False
fh = logging.FileHandler(MAIN_LOG, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(message)s"))
if not main_logger.handlers:
    main_logger.addHandler(fh)


def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    main_logger.info(line)
    print(line)


def run_script(script_path):
    proc = subprocess.run(
        [sys.executable, script_path],
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
        timeout=300,
    )
    return proc


def parse_last_json(text):
    lines = text.strip().split("\n")
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    return None


BORDER = "=" * 52
SEP = "-" * 52


def main():
    print(BORDER)
    print("  Xq.KB - Unified Pipeline")
    print(BORDER)
    log("PIPELINE START")

    report = {
        "bootstrap": None,
        "engine": None,
        "index_guard": None,
        "weekly_scan": "ok",
    }
    pipeline_ok = True

    for i, step in enumerate(STEPS, 1):
        script = os.path.join(SCRIPTS_DIR, step["script"])
        print(f"\n[{i}/4] {step['name']} - {step['script']}")
        print(SEP)

        try:
            proc = run_script(script)
        except subprocess.TimeoutExpired:
            print(f"  [FATAL] Timeout")
            log(f"STEP {step['name']}: FATAL timeout")
            if step["critical"]:
                report["bootstrap"] = {"status": "timeout"}
                pipeline_ok = False
                break
            continue
        except Exception as e:
            print(f"  [FATAL] {e}")
            log(f"STEP {step['name']}: FATAL {e}")
            if step["critical"]:
                report["bootstrap"] = {"status": "exception"}
                pipeline_ok = False
                break
            continue

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        for line in stdout.split("\n"):
            stripped = line.strip()
            if stripped:
                log(f"  [{step['name']}] {stripped}")

        if stderr:
            for line in stderr.split("\n"):
                stripped = line.strip()
                if stripped:
                    log(f"  [{step['name']}:ERR] {stripped}")

        if proc.returncode != 0:
            print(f"  [ERROR] exit code: {proc.returncode}")
            if step["critical"]:
                report["bootstrap"] = {"status": "fail"}
                pipeline_ok = False
                break

        if step["parse_json"]:
            parsed = parse_last_json(stdout)
            if parsed:
                report_key = step["name"].lower().replace("hermes_", "")
                report[report_key] = parsed
                print(f"  >> {json.dumps(parsed, ensure_ascii=False)}")

                if step["name"] == "BOOTSTRAP":
                    if not parsed.get("system_ready", False):
                        print(f"  [ABORT] system not ready")
                        log("PIPELINE ABORTED: bootstrap system_ready=false")
                        pipeline_ok = False
                        break
            else:
                print(f"  [WARN] no JSON output parsed")
        else:
            print(f"  [OK]")

        print(f"  [DONE]")

    print(f"\n{BORDER}")
    print("  Final Report")
    print(BORDER)

    if report.get("bootstrap"):
        b = report["bootstrap"]
        print(f"  Bootstrap   : ready={b.get('system_ready')} repaired={len(b.get('repaired_items',[]))}")
    if report.get("engine"):
        e = report["engine"]
        print(f"  Engine      : processed={e.get('processed_count')} success={e.get('success_count')} failed={e.get('failed_count')}")
    if report.get("index_guard"):
        ig = report["index_guard"]
        print(f"  Index Guard : scanned={ig.get('scanned_files')} changed={ig.get('changed_files')} updated={ig.get('updated_index')}")
    if report.get("weekly_scan"):
        print(f"  Weekly Scan : {report['weekly_scan']}")

    print(f"\n  System Healthy: {pipeline_ok}")
    print(BORDER)

    log(f"PIPELINE END: healthy={pipeline_ok}")
    log(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

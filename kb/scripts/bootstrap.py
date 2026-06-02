import os
import sys
import json
import time
import subprocess
import logging
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOTSTRAP_LOG = os.path.join(BASE_DIR, "logs", "bootstrap.log")

SYNCTHING_PATH = r"C:\Users\qqmin06\Downloads\syncthing\syncthing-windows-amd64-v2.1.0"
SYNCTHING_HOME = os.path.join(os.path.dirname(BASE_DIR), ".syncthing")

REQUIRED_DIRS = [
    os.path.join(BASE_DIR, "inbox"),
    os.path.join(BASE_DIR, "processing"),
    os.path.join(BASE_DIR, "core"),
    os.path.join(BASE_DIR, "manual"),
    os.path.join(BASE_DIR, "raw"),
    os.path.join(BASE_DIR, "output"),
    os.path.join(BASE_DIR, "logs"),
    os.path.join(BASE_DIR, "scripts"),
    os.path.join(BASE_DIR, "core", "question"),
    os.path.join(BASE_DIR, "core", "note"),
]

REQUIRED_FILES = {
    os.path.join(BASE_DIR, "000_Dashboard.md"): "# Hermes KB\n\n知识库就绪。\n",
    os.path.join(BASE_DIR, "scripts", "SAFEGUARD.md"): "# SAFEGUARD\n\n本文件由 bootstrap.py 自动创建。\n\n- 不允许删除已有文件\n- 不允许修改 core / manual / raw 已有内容\n- 所有操作必须记录日志\n",
    os.path.join(BASE_DIR, "logs", "index_state.json"): "{}",
}

os.makedirs(os.path.dirname(BOOTSTRAP_LOG), exist_ok=True)

bootstrap_logger = logging.getLogger("bootstrap")
bootstrap_logger.setLevel(logging.INFO)
bootstrap_logger.propagate = False
fh = logging.FileHandler(BOOTSTRAP_LOG, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(message)s"))
if not bootstrap_logger.handlers:
    bootstrap_logger.addHandler(fh)


def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    bootstrap_logger.info(line)
    print(line)


def _ensure_psutil():
    try:
        import psutil  # noqa: F401
    except ImportError:
        log("PSUTIL_NOT_FOUND: installing psutil via pip ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "psutil", "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log("PSUTIL_INSTALLED: psutil installed successfully")


def _check_syncthing_binary():
    syncthing_exe = os.path.join(SYNCTHING_PATH, "syncthing.exe")
    if not os.path.isfile(syncthing_exe):
        print()
        print("=" * 60)
        print("  [WARNING] syncthing.exe not found at:")
        print(f"    {syncthing_exe}")
        print()
        print("  Please configure the correct path in bootstrap.py:")
        print("    SYNCTHING_PATH = r\"你的syncthing.exe所在目录的绝对路径\"")
        print("=" * 60)
        print()
        log(f"SYNCTHING_BINARY_NOT_FOUND: {syncthing_exe}")
        return None
    log(f"SYNCTHING_BINARY_FOUND: {syncthing_exe}")
    return syncthing_exe


def _is_syncthing_running():
    import psutil
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() == "syncthing.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _launch_syncthing(syncthing_exe):
    try:
        subprocess.Popen(
            [syncthing_exe, "serve", "--home", SYNCTHING_HOME, "--no-console", "--no-browser"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        log(f"SYNCTHING_LAUNCHED: serve --home={SYNCTHING_HOME} --no-console --no-browser")
        return True
    except Exception as e:
        log(f"SYNCTHING_LAUNCH_FAILED: {e}")
        return False


def _ensure_syncthing():
    syncthing_exe = _check_syncthing_binary()
    if syncthing_exe is None:
        return

    if _is_syncthing_running():
        log("SYNCTHING_ALREADY_RUNNING: Syncthing is already running.")
        print("  Syncthing is already running.")
        return

    log("SYNCTHING_NOT_RUNNING: attempting to launch ...")
    _launch_syncthing(syncthing_exe)

    time.sleep(2)
    if _is_syncthing_running():
        log("SYNCTHING_GUARD_OK: Syncthing confirmed running after launch")
        return

    for i in range(3):
        log(f"SYNCTHING_GUARD_RETRY_{i+1}: retrying launch ...")
        _launch_syncthing(syncthing_exe)
        time.sleep(3)
        if _is_syncthing_running():
            log("SYNCTHING_GUARD_OK: Syncthing confirmed running after retry")
            return

    log("SYNCTHING_GUARD_FAILED: Syncthing failed to start after 3 retries, continuing anyway")
    print("  [WARNING] Syncthing failed to start after 3 attempts. Continuing without Syncthing.")


def main():
    _ensure_psutil()
    _ensure_syncthing()

    missing = []
    repaired = []

    for d in REQUIRED_DIRS:
        label = os.path.relpath(d, BASE_DIR).replace("\\", "/")
        if not os.path.isdir(d):
            missing.append(label)
            os.makedirs(d, exist_ok=True)
            repaired.append(label)
            log(f"CREATED_DIR {label}")
        else:
            log(f"OK_DIR {label}")

    for filepath, default_content in REQUIRED_FILES.items():
        label = os.path.relpath(filepath, BASE_DIR).replace("\\", "/")
        if not os.path.exists(filepath):
            missing.append(label)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(default_content)
            repaired.append(label)
            log(f"CREATED_FILE {label}")
        else:
            log(f"OK_FILE {label}")

    system_ready = len([item for item in missing if item not in repaired]) == 0

    result = {
        "status": "pass" if system_ready else "fail",
        "missing_items": [m for m in missing if m not in repaired],
        "repaired_items": repaired,
        "system_ready": system_ready,
    }

    log(f"BOOTSTRAP: ready={system_ready} missing={len(missing)} repaired={len(repaired)}")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

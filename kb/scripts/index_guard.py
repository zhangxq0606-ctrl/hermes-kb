import os
import json
import hashlib
import logging
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = [
    os.path.join(BASE_DIR, "core"),
    os.path.join(BASE_DIR, "manual"),
    os.path.join(BASE_DIR, "raw"),
]
INDEX_FILE = os.path.join(BASE_DIR, "logs", "index_state.json")
GUARD_LOG = os.path.join(BASE_DIR, "logs", "index_guard.log")

os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
os.makedirs(os.path.dirname(GUARD_LOG), exist_ok=True)

guard_logger = logging.getLogger("index_guard")
guard_logger.setLevel(logging.INFO)
guard_logger.propagate = False
fh = logging.FileHandler(GUARD_LOG, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(message)s"))
if not guard_logger.handlers:
    guard_logger.addHandler(fh)


def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    guard_logger.info(line)
    print(line)


def file_hash(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_index():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_index(data):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def collect_md_files():
    files = []
    for scan_dir in SCAN_DIRS:
        if not os.path.isdir(scan_dir):
            continue
        for root, dirs, filenames in os.walk(scan_dir):
            for fn in filenames:
                if fn.endswith(".md"):
                    files.append(os.path.join(root, fn))
    return sorted(files)


def main():
    index = load_index()
    all_files = collect_md_files()
    scanned = len(all_files)
    changed = 0
    updated = 0

    for filepath in all_files:
        rel = os.path.relpath(filepath, BASE_DIR).replace("\\", "/")
        try:
            h = file_hash(filepath)
            mtime = os.path.getmtime(filepath)
            mtime_ts = datetime.fromtimestamp(mtime, tz=TZ).strftime("%Y-%m-%d %H:%M:%S")

            existing = index.get(rel)

            if existing is None:
                log(f"NEW {rel} -> indexed")
                index[rel] = {"hash": h, "last_modified": mtime_ts}
                updated += 1
                changed += 1
            elif existing.get("hash") != h:
                log(f"CHANGED {rel} -> re-indexed (old: {existing.get('hash','')[:12]}... new: {h[:12]}...)")
                index[rel] = {"hash": h, "last_modified": mtime_ts}
                updated += 1
                changed += 1
            else:
                log(f"OK {rel}")
        except Exception as e:
            log(f"ERROR {rel}: {e}")

    stale = [k for k in index if not os.path.exists(os.path.join(BASE_DIR, k))]
    for k in stale:
        log(f"REMOVED {k} (file deleted)")
        del index[k]

    if defined_files_count := sum(1 for k in index if os.path.exists(os.path.join(BASE_DIR, k))):
        pass

    save_index(index)
    log(f"INDEX_GUARD: scanned={scanned} changed={changed} updated={updated}")

    result = {
        "scanned_files": scanned,
        "changed_files": changed,
        "updated_index": updated,
        "status": "pass",
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

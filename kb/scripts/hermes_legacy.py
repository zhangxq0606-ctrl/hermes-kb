import os
import shutil
import json
import logging
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(BASE_DIR, "inbox")
PROCESSING = os.path.join(BASE_DIR, "processing")
LOG_FILE = os.path.join(BASE_DIR, "logs", "hermes.log")
MANUAL_TECH = os.path.join(BASE_DIR, "manual", "technical")
CORE_INSIGHT = os.path.join(BASE_DIR, "core", "insight")
MANUAL_REF = os.path.join(BASE_DIR, "manual", "reference")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

os.makedirs(PROCESSING, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
os.makedirs(MANUAL_TECH, exist_ok=True)
os.makedirs(CORE_INSIGHT, exist_ok=True)
os.makedirs(MANUAL_REF, exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(message)s",
)

SPEC_PROMPT = """你是一个知识分类引擎。分析以下文本内容，仅输出一个JSON对象（不要任何其他文字），结构如下：

{
  "type": "technical | insight | mixed",
  "technical_score": 0-10,
  "cognitive_score": 0-10,
  "summary": "一句话总结"
}

分类标准：
- technical: 偏向技术操作、配置、代码、工具使用说明
- insight: 偏向后设认知、思考方法、学习策略、元知识
- mixed: 同时包含上述两者

现在分析以下内容并仅输出JSON："""


def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    logging.info(line)
    print(line)


def call_deepseek(content):
    import urllib.request
    import urllib.error

    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set")

    messages = [
        {"role": "system", "content": "你只输出JSON，不要输出任何其他内容。"},
        {"role": "user", "content": SPEC_PROMPT + "\n\n" + content},
    ]

    body = json.dumps({
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 300,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(DEEPSEEK_API_URL, data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {DEEPSEEK_API_KEY}")

    resp = urllib.request.urlopen(req, timeout=60)
    raw = resp.read().decode("utf-8")
    data = json.loads(raw)

    reply = data["choices"][0]["message"]["content"].strip()

    if reply.startswith("```"):
        lines = reply.split("\n")
        reply = "\n".join(lines[1:])
        if reply.endswith("```"):
            reply = reply[:-3]
    reply = reply.strip()

    return json.loads(reply)


def route_file(result, src, filename):
    target_dirs = []
    t = result.get("type", "")

    if t == "technical":
        target_dirs.append(MANUAL_TECH)
    elif t == "insight":
        target_dirs.append(CORE_INSIGHT)
    elif t == "mixed":
        target_dirs.append(MANUAL_REF)
        target_dirs.append(CORE_INSIGHT)
    else:
        target_dirs.append(MANUAL_REF)

    for d in target_dirs:
        shutil.copy2(src, os.path.join(d, filename))

    os.remove(src)

    targets = ", ".join(os.path.relpath(d, BASE_DIR) for d in target_dirs)
    log(f"PROCESSED {filename} -> {targets}")


# ---- Phase 1: Move inbox -> processing ----
moved_count = 0

for entry in os.listdir(INBOX):
    src = os.path.join(INBOX, entry)
    if not os.path.isfile(src):
        continue
    dst = os.path.join(PROCESSING, entry)
    shutil.move(src, dst)
    moved_count += 1
    log(f"MOVED {entry}")

inbox_empty = len([e for e in os.listdir(INBOX) if os.path.isfile(os.path.join(INBOX, e))]) == 0

# ---- Phase 2: AI classify & route processing/ files ----
processed = 0
tags = {"technical": 0, "insight": 0, "mixed": 0, "failed": 0}

for entry in sorted(os.listdir(PROCESSING)):
    src = os.path.join(PROCESSING, entry)
    if not os.path.isfile(src):
        continue
    try:
        with open(src, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if not content.strip():
            os.remove(src)
            log(f"SKIPPED {entry} (empty file)")
            continue
        result = call_deepseek(content)
        route_file(result, src, entry)
        processed += 1
        t = result.get("type", "unknown")
        if t in tags:
            tags[t] += 1
    except Exception as e:
        tags["failed"] += 1
        log(f"FAILED {entry}: {e}")

summary = {
    "processed": processed,
    "technical": tags["technical"],
    "insight": tags["insight"],
    "mixed": tags["mixed"],
    "failed": tags["failed"],
}

if moved_count > 0:
    summary["moved_from_inbox"] = moved_count
    summary["inbox_empty"] = inbox_empty

print(json.dumps(summary, ensure_ascii=False))

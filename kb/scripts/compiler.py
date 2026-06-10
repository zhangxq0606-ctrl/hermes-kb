import os
import sys
import re
import json
import logging
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
from env_loader import load_dotenv
import semantic_index

load_dotenv()

TZ = timezone(timedelta(hours=8))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOPIC_DIR = os.path.join(BASE_DIR, "core", "topic")
SCAN_DIRS = [
    os.path.join(BASE_DIR, "core", "insight"),
    os.path.join(BASE_DIR, "manual", "technical"),
]
COMPILER_LOG = os.path.join(BASE_DIR, "logs", "compiler.log")

AI_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
AI_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
AI_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

os.makedirs(TOPIC_DIR, exist_ok=True)
os.makedirs(os.path.dirname(COMPILER_LOG), exist_ok=True)

compiler_logger = logging.getLogger("compiler")
compiler_logger.setLevel(logging.INFO)
compiler_logger.propagate = False
fh = logging.FileHandler(COMPILER_LOG, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(message)s"))
if not compiler_logger.handlers:
    compiler_logger.addHandler(fh)

TAG_PATTERN = re.compile(r"^> 标签:\s*(.+)$", re.MULTILINE)

COMPILER_SYSTEM = """你是一个知识编译助手。你需要将多篇同一主题的笔记综合成一页"主题页"——即关于该主题的当前综合结论。

输入：多篇笔记的精炼版内容（每篇包含标题、核心洞察、逻辑链）
输出：一篇综合后的主题页 markdown，结构如下：

# {AI 决定的主题名}

🎯 【综合判断】
- 综合所有笔记后的核心结论，1-2句话。必须是"综合后"的新判断，不是某单篇的结论。

🗺️ 【核心脉络】
- 该主题下各篇笔记共同推导出的逻辑演进路径
- 用有序列表，3-5步，展现递进/互补关系

📦 【各篇核心观点对照】
- {笔记A标题}: {该篇的核心独到之处，突出每篇独有的价值}
- {笔记B标题}: ...同上

📎 【关联原始笔记】
- [{笔记A标题}]({笔记A文件名})
- [{笔记B标题}]({笔记B文件名})

> 编译于 {当前日期} | 覆盖 {N} 篇精炼笔记
> 标签: {该组的 usage_tag}

要求：
- 综合判断必须是"综合后"的结论，不是某单篇的结论，也不是简单罗列
- 核心脉络要展现各篇之间的递进/互补关系
- 各篇核心观点对照要突出每篇独有的价值，不是重复综合判断
- 链接格式使用 [{标题}]({文件名}.md)，文件名不带路径和 _refined 后缀
- 主题名用中文，简洁概括该主题的核心议题
- 如果不确定某篇笔记是否应归入此主题，宁可不归入
"""


def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    compiler_logger.info(line)
    print(line)


def scan_refined():
    entries = []
    for scan_dir in SCAN_DIRS:
        if not os.path.isdir(scan_dir):
            continue
        for fn in os.listdir(scan_dir):
            if not fn.endswith("_refined.md"):
                continue
            fp = os.path.join(scan_dir, fn)
            if not os.path.isfile(fp):
                continue
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue
            tag_match = TAG_PATTERN.search(content)
            tag = tag_match.group(1).strip() if tag_match else "unlabeled"
            entries.append({"path": fp, "filename": fn, "content": content, "tag": tag})
    log(f"SCAN: found {len(entries)} refined notes")
    return entries


def inherit_tags(entries):
    unlabeled = [e for e in entries if e["tag"] == "unlabeled"]
    labeled = [e for e in entries if e["tag"] != "unlabeled"]
    if not unlabeled:
        return entries
    log(f"CLUSTER: {len(unlabeled)} unlabeled notes attempting tag inheritance")
    for entry in unlabeled:
        query_text = entry["content"][:2000]
        try:
            results = semantic_index.search(query_text, top_k=3, min_score=0.3)
        except Exception:
            results = []
        inherited = None
        for r_path, score, _ in results:
            for le in labeled:
                if le["path"] == r_path:
                    inherited = le["tag"]
                    break
            if inherited:
                break
        if inherited:
            entry["tag"] = inherited
            log(f"  TAG_INHERIT: {entry['filename']} -> {inherited}")
        else:
            log(f"  TAG_UNASSIGNED: {entry['filename']} remains unlabeled")
    return entries


def cluster_by_tag(entries):
    groups = {}
    for e in entries:
        tag = e["tag"]
        if tag == "unlabeled":
            continue
        groups.setdefault(tag, []).append(e)
    compilable = {tag: members for tag, members in groups.items() if len(members) >= 2}
    log(f"CLUSTER: {len(compilable)} compilable groups (tags: {list(compilable.keys())})")
    return compilable


def safe_filename(name):
    safe = re.sub(r'[\\/:*?"<>|]', '', name)
    safe = re.sub(r'\s+', '_', safe)
    return safe


def call_ai_compile(members, tag):
    import urllib.request
    import urllib.error

    if not AI_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not configured")

    url = f"{AI_BASE_URL}/v1/chat/completions"

    user_parts = []
    for i, m in enumerate(members, 1):
        title = m["filename"]
        if title.endswith("_refined.md"):
            title = title[:-11]
        user_parts.append(f"【笔记 {i}】\n标题：{title}\n标签：{tag}\n内容：\n{m['content']}\n")

    user_msg = "\n".join(user_parts)

    messages = [
        {"role": "system", "content": COMPILER_SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    body = json.dumps({
        "model": AI_MODEL,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 2000,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {AI_API_KEY}")

    resp = urllib.request.urlopen(req, timeout=180)
    raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    return data["choices"][0]["message"]["content"].strip()


def extract_topic_title(markdown_content):
    m = re.search(r"^#\s*(.+)$", markdown_content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return "untitled"


def write_topic(markdown_content, tag):
    filename = f"topic_{tag}.md"
    filepath = os.path.join(TOPIC_DIR, filename)

    # 确保链接格式修正, 去掉可能残留的 _refined 后缀
    markdown_content = re.sub(r'\[([^\]]+)\]\(([^)]+)_refined\.md\)', r'[\1](\2.md)', markdown_content)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    log(f"  WRITE: {filename} (tag={tag})")
    return filename


def main():
    log("COMPILER START")
    today = datetime.now(TZ).strftime("%Y-%m-%d")

    entries = scan_refined()
    if not entries:
        log("COMPILER_DONE: no refined notes found")
        print(json.dumps({"compiled_count": 0, "topics": []}, ensure_ascii=False))
        return

    entries = inherit_tags(entries)
    groups = cluster_by_tag(entries)

    if not groups:
        log("COMPILER_DONE: no compilable groups")
        print(json.dumps({"compiled_count": 0, "topics": []}, ensure_ascii=False))
        return

    topics = []
    for tag, members in groups.items():
        log(f"COMPILING: tag={tag} members={len(members)}")
        try:
            md = call_ai_compile(members, tag)
        except Exception as e:
            log(f"  COMPILE_FAIL: {e}")
            continue
        filename = write_topic(md, tag)
        topics.append(filename)

    log(f"COMPILER_DONE: compiled={len(topics)} topics={topics}")
    print(json.dumps({"compiled_count": len(topics), "topics": topics}, ensure_ascii=False))


if __name__ == "__main__":
    main()

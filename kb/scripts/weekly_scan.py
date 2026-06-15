import os
import sys
import re
import json
import hashlib
import logging
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_loader import load_dotenv

load_dotenv()

TZ = timezone(timedelta(hours=8))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD_FILE = os.path.join(BASE_DIR, "000_Dashboard.md")
SCAN_LOG = os.path.join(BASE_DIR, "logs", "weekly_scan.log")
STATE_FILE = os.path.join(BASE_DIR, "logs", ".weekly_scan_state.json")

CORE_INSIGHT = os.path.join(BASE_DIR, "core", "insight")
CORE_QUESTION = os.path.join(BASE_DIR, "core", "question")
MANUAL_TECH = os.path.join(BASE_DIR, "manual", "technical")

INSIGHT_PATTERN = re.compile(r"🎯\s*【一句话洞察】\s*\n\s*-\s*(.*?)(?:\n\n|\n🗺️|\n📦|\n\[)", re.DOTALL)
TITLE_PATTERN = re.compile(r"^#\s*(.+)$", re.MULTILINE)

AI_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
AI_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
AI_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

STAT_DIRS = {
    "inbox": os.path.join(BASE_DIR, "inbox"),
    "processing": os.path.join(BASE_DIR, "processing"),
    "core": os.path.join(BASE_DIR, "core"),
    "manual": os.path.join(BASE_DIR, "manual"),
}

QUESTION_START = "<!-- QUESTIONS_START -->"
QUESTION_END = "<!-- QUESTIONS_END -->"
ANSWER_START = "<!-- ANSWER_STATS_START -->"
ANSWER_END = "<!-- ANSWER_STATS_END -->"
ACTIVE_START = "<!-- ACTIVE_START -->"
ACTIVE_END = "<!-- ACTIVE_END -->"
BACKLOG_START = "<!-- BACKLOG_START -->"
BACKLOG_END = "<!-- BACKLOG_END -->"
ARCHIVE_FILE = os.path.join(BASE_DIR, "output", "question_archive.md")

os.makedirs(os.path.dirname(SCAN_LOG), exist_ok=True)

scan_logger = logging.getLogger("weekly_scan")
scan_logger.setLevel(logging.INFO)
scan_logger.propagate = False
fh = logging.FileHandler(SCAN_LOG, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(message)s"))
if not scan_logger.handlers:
    scan_logger.addHandler(fh)


def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    scan_logger.info(line)
    import sys
    try:
        print(line)
    except UnicodeEncodeError:
        safe = line.encode(sys.stdout.encoding or "ascii", errors="replace").decode(sys.stdout.encoding or "ascii")
        print(safe)


AUDIT_PROMPT = """你是一个务实的认知审计员。通读用户的精炼笔记摘要，输出有实际价值的追问。

输入格式：每行一条 `- [来源目录] 文件名: 一句话洞察`

审计目标：
- 基于已有认知，提出能帮用户**做决策、采取行动**的追问。
- 每个问题必须源自**单一主题**的深入挖掘，绝不能跨领域牵强关联。
- 只提两类问题：
  1. **实践盲区** — 用户提到了某个认知，但没有对应实践记录。追问落地情况。
  2. **判断缺口** — 用户的两个观点在同一主题下有值得深挖的递进关系，追问未覆盖的维度。

输出限制：
- 返回 0 ~ 2 个问题。宁缺毋滥。
- 以下情况**必须返回空**（不输出任何行）：
  - 没有足够内容支撑有价值追问
  - 只能靠跨领域关联才能出题
  - 只能输出类似"你怎么平衡A和B"的套路化问题
- 严禁"认知张力"式提问。两个不同领域的笔记之间没有天然交集时，不要强行关联。
- 格式：每行以 `* ` 开头，直接写问题本身，不加分类前缀（如【认知张力】）。禁止使用emoji。
- 好的范例：`* 你在训练AI工具链上的时间投入，有没有量化过产出回报？`
- 坏的范例：`* 【认知张力】你强调A又说B，两者如何平衡？`

现在开始审计以下知识库摘要："""


def collect_refined_md():
    files = []
    for scan_dir in (CORE_INSIGHT, MANUAL_TECH):
        if not os.path.isdir(scan_dir):
            continue
        for entry in sorted(os.listdir(scan_dir)):
            if not entry.endswith("_refined.md"):
                continue
            fp = os.path.join(scan_dir, entry)
            if not os.path.isfile(fp):
                continue
            mtime = os.path.getmtime(fp)
            files.append((mtime, fp, scan_dir))
    files.sort(key=lambda x: -x[0])
    return files


def extract_insight(content):
    m = INSIGHT_PATTERN.search(content)
    if m:
        return m.group(1).strip()
    m = TITLE_PATTERN.search(content)
    if m:
        title = m.group(1).strip()
        body = re.sub(r"^#.*", "", content, flags=re.MULTILINE).strip()
        return f"{title}: {body[:100]}"
    return content[:150].replace("\n", " ").strip()


def collect_answered_questions():
    """Read answered questions from core/question/ and return formatted context."""
    if not os.path.isdir(CORE_QUESTION):
        return ""
    parts = []
    for fn in sorted(os.listdir(CORE_QUESTION)):
        if not fn.endswith(".md"):
            continue
        fp = os.path.join(CORE_QUESTION, fn)
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue
        # Extract question title
        title_match = re.search(r"^#\s*(.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else fn
        # Extract answer from ## 我的思考
        answer_match = re.search(r"## 我的思考\s*\n\s*\n(.+?)(?:\n##|\Z)", content, re.DOTALL)
        answer = answer_match.group(1).strip() if answer_match else ""
        if not answer:
            continue  # skip unanswered questions
        parts.append(f"- 问题: {title}\n  你的回答: {answer[:200]}")
    if not parts:
        return ""
    return "\n\n=== 你的历史问答记录 ===\n" + "\n".join(parts)


def build_context(files):
    parts = []
    for mtime, fp, scan_dir in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                content = f.read().strip()
            if not content:
                continue
            insight = extract_insight(content)
            rel_dir = os.path.relpath(scan_dir, BASE_DIR).replace("\\", "/")
            filename = os.path.basename(fp)
            parts.append(f"- [{rel_dir}] {filename}: {insight}")
        except Exception:
            pass

    # Append answered questions as context
    qa_context = collect_answered_questions()
    if qa_context:
        parts.append(qa_context)

    if not parts:
        return "=== (empty) ===\n本周暂无新入库笔记。请基于通用技术趋势生成探索性问题。\n"

    return "已入库认知资产摘要：\n" + "\n".join(parts)


def call_ai_audit(context):
    import urllib.request
    import urllib.error

    if not AI_API_KEY:
        raise RuntimeError("API key not configured. Check .env file for DEEPSEEK_API_KEY.")

    url = f"{AI_BASE_URL}/v1/chat/completions"

    messages = [
        {"role": "system", "content": "你是一个务实的认知审计员。只输出 Markdown 列表，0~2 条。若无有价值问题则不输出任何行。禁止跨领域牵强关联。不输出任何其他内容。"},
        {"role": "user", "content": AUDIT_PROMPT + "\n\n" + context},
    ]

    body = json.dumps({
        "model": AI_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 800,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {AI_API_KEY}")

    resp = urllib.request.urlopen(req, timeout=120)
    raw = resp.read().decode("utf-8")
    data = json.loads(raw)

    usage = data.get("usage", {})
    in_tok = usage.get("prompt_tokens", "?")
    out_tok = usage.get("completion_tokens", "?")
    log(f"TOKENS: in={in_tok} out={out_tok}")

    reply = data["choices"][0]["message"]["content"].strip()

    if reply.startswith("```"):
        lines = reply.split("\n")
        reply = "\n".join(lines[1:])
        if reply.rstrip().endswith("```"):
            reply = reply[:reply.rfind("```")].rstrip()
    reply = reply.strip()

    return reply


def parse_questions(raw_text):
    questions = []
    for line in raw_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("*") and not stripped.startswith("**"):
            q = re.sub(r"^\*\s*", "", stripped).strip()
            q = q.replace(chr(0x1F504), "").strip()
            if q:
                questions.append(q)
    return questions[:2]


def compute_fingerprint(files):
    parts = []
    for mtime, fp, scan_dir in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                content_hash = hashlib.sha256(f.read().encode()).hexdigest()[:16]
            parts.append(f"{fp}|{mtime}|{content_hash}")
        except Exception:
            pass
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def count_files(directory):
    if not os.path.isdir(directory):
        return 0
    count = 0
    for root, dirs, filenames in os.walk(directory):
        for fn in filenames:
            if fn.endswith(".md"):
                count += 1
    return count


def compute_file_hash(filepath):
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def check_question_status(state):
    total = 0
    answered = 0
    if not os.path.isdir(CORE_QUESTION):
        return 0, 0
    stored_hashes = state.get("question_files", {})
    for entry in sorted(os.listdir(CORE_QUESTION)):
        if not entry.endswith(".md"):
            continue
        fp = os.path.join(CORE_QUESTION, entry)
        if not os.path.isfile(fp):
            continue
        total += 1
        current_hash = compute_file_hash(fp)
        stored = stored_hashes.get(entry)
        if stored and current_hash != stored:
            answered += 1
    return total, answered


def migrate_state(state):
    if "active" in state:
        return state
    if "questions" in state:
        old_questions = state.pop("questions", [])
        today = datetime.now(TZ)
        week = today.strftime("%Y-W%W")
        created = today.strftime("%Y-%m-%d")
        active = []
        file_index = {}
        if os.path.isdir(CORE_QUESTION):
            for fname in sorted(os.listdir(CORE_QUESTION)):
                if fname.endswith(".md"):
                    fp = os.path.join(CORE_QUESTION, fname)
                    try:
                        with open(fp, "r", encoding="utf-8") as fh:
                            first_line = fh.readline().strip().lstrip("#").strip()
                        file_index[fname] = first_line
                    except Exception:
                        pass
        for q_text in old_questions:
            matched = None
            for fname, title in file_index.items():
                if q_text[:30] in title or title[:30] in q_text:
                    matched = fname
                    break
            active.append({
                "text": q_text,
                "file": matched or "",
                "created": created,
                "week": week,
            })
        state["active"] = active
        state["backlog"] = []
        state.setdefault("question_files", {})
        state.setdefault("archived_count", 0)
        log(f"WEEKLY_SCAN: migrated old state -> active={len(active)}")
        return state
    state.setdefault("active", [])
    state.setdefault("backlog", [])
    state.setdefault("question_files", {})
    state.setdefault("archived_count", 0)
    return state


def get_active_answer_count(active_questions, question_files):
    answered = 0
    for q in active_questions:
        fname = q.get("file", "")
        if not fname:
            continue
        fp = os.path.join(CORE_QUESTION, fname)
        if not os.path.isfile(fp):
            continue
        stored = question_files.get(fname)
        if not stored:
            continue
        if compute_file_hash(fp) != stored:
            answered += 1
    return answered


def archive_old_backlog(backlog, current_week):
    parts = current_week.split("-W")
    cur_year = int(parts[0]) if len(parts) == 2 else 0
    cur_week = int(parts[1]) if len(parts) == 2 else 0

    kept = []
    expired = []
    for q in backlog:
        q_parts = q.get("week", "0-W0").split("-W")
        q_year = int(q_parts[0]) if len(q_parts) == 2 else 0
        q_week = int(q_parts[1]) if len(q_parts) == 2 else 0
        week_diff = (cur_year - q_year) * 52 + (cur_week - q_week)
        if week_diff > 4:
            expired.append(q)
        else:
            kept.append(q)

    if expired:
        os.makedirs(os.path.dirname(ARCHIVE_FILE), exist_ok=True)
        ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        block = f"\n\n## 归档于 {ts}\n\n"
        for q in expired:
            block += f"* {q['text']} (来源: {q.get('week', '?')})\n"
        with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
            f.write(block)
        log(f"ARCHIVED: {len(expired)} backlog items -> output/question_archive.md")

    return kept


def is_unanswered(q, question_files):
    fname = q.get("file", "")
    if not fname:
        return True
    stored = question_files.get(fname)
    if not stored:
        return True
    fp = os.path.join(CORE_QUESTION, fname)
    if not os.path.isfile(fp):
        return True
    return compute_file_hash(fp) == stored


def read_dashboard():
    if not os.path.exists(DASHBOARD_FILE):
        return ""
    with open(DASHBOARD_FILE, "r", encoding="utf-8") as f:
        return f.read()


def write_dashboard(content):
    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    core_files = collect_refined_md()
    fingerprint = compute_fingerprint(core_files)

    state = load_state()
    state = migrate_state(state)

    prev_fingerprint = state.get("fingerprint", "")
    today = datetime.now(TZ)
    current_week = today.strftime("%Y-W%W")
    current_date = today.strftime("%Y-%m-%d")

    if fingerprint != prev_fingerprint:
        context = build_context(core_files)
        log(f"WEEKLY_SCAN: sending {len(core_files)} files to AI audit")

        try:
            raw = call_ai_audit(context)
            log(f"WEEKLY_SCAN: AI response received ({len(raw)} chars)")
            log(f"  RAW: {raw[:200]}")

            questions = parse_questions(raw)
            log(f"WEEKLY_SCAN: parsed {len(questions)} questions")

            if not questions:
                log("WEEKLY_SCAN: no valuable questions generated, skipping")

            os.makedirs(CORE_QUESTION, exist_ok=True)
            ts = today.strftime("%Y%m%d_%H%M%S")
            new_active = []
            question_files = state.get("question_files", {})

            for i, q_text in enumerate(questions, 1):
                q_filename = f"question_{ts}_{i}.md"
                q_path = os.path.join(CORE_QUESTION, q_filename)
                q_content = (
                    f"# {q_text}\n\n"
                    f"> 生成时间: {today.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"> 来源: Weekly Scan\n\n"
                    f"## 我的思考\n\n\n\n"
                    f"## 研究笔记\n\n"
                )
                with open(q_path, "w", encoding="utf-8") as f:
                    f.write(q_content)
                question_files[q_filename] = compute_file_hash(q_path)
                new_active.append({
                    "text": q_text,
                    "file": q_filename,
                    "created": current_date,
                    "week": current_week,
                })
                log(f"  Q{i} saved -> {q_filename}")

            prev_active = state.get("active", [])
            backlog = state.get("backlog", [])
            for q in prev_active:
                if is_unanswered(q, question_files):
                    backlog.append(q)
                    log(f"  BACKLOG: {q['text'][:50]}...")

            backlog = archive_old_backlog(backlog, current_week)

            state["active"] = new_active
            state["backlog"] = backlog
            state["question_files"] = question_files
            state["fingerprint"] = fingerprint
            save_state(state)

        except Exception as e:
            log(f"WEEKLY_SCAN FAILED: {e}")
            if not state.get("active"):
                fallback_ts = today.strftime("%Y%m%d_%H%M%S")
                os.makedirs(CORE_QUESTION, exist_ok=True)
                fallback_qs = [
                    "如何在当前技术栈中进一步降低信息采集的摩擦力？",
                    "你的知识管理体系是否真正在推动决策，还是只在积累信息？",
                ]
                new_active = []
                question_files = state.get("question_files", {})
                for i, q_text in enumerate(fallback_qs, 1):
                    q_filename = f"question_{fallback_ts}_{i}.md"
                    q_path = os.path.join(CORE_QUESTION, q_filename)
                    q_content = (
                        f"# {q_text}\n\n"
                        f"> 生成时间: {today.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"> 来源: Weekly Scan (fallback)\n\n"
                        f"## 我的思考\n\n\n\n"
                        f"## 研究笔记\n\n"
                    )
                    with open(q_path, "w", encoding="utf-8") as f:
                        f.write(q_content)
                    question_files[q_filename] = compute_file_hash(q_path)
                    new_active.append({
                        "text": q_text,
                        "file": q_filename,
                        "created": current_date,
                        "week": current_week,
                    })
                state["active"] = new_active
                state["question_files"] = question_files
                state["fingerprint"] = fingerprint
                save_state(state)
    else:
        log("WEEKLY_SCAN: core unchanged, reusing previous active questions")
        active = state.get("active", [])
        backlog = state.get("backlog", [])
        question_files = state.get("question_files", {})

        remaining_active = []
        for q in active:
            if q.get("week") == current_week:
                remaining_active.append(q)
            else:
                if is_unanswered(q, question_files):
                    backlog.append(q)
                    log(f"  BACKLOG: {q['text'][:50]}...")

        backlog = archive_old_backlog(backlog, current_week)
        state["active"] = remaining_active
        state["backlog"] = backlog
        save_state(state)

    active = state.get("active", [])
    backlog = state.get("backlog", [])
    question_files = state.get("question_files", {})

    for lst in (active, backlog):
        for q in lst:
            t = q["text"]
            t = t.replace(chr(0x1F504), "").strip()
            while t and ord(t[0]) > 127 and not ("\u4e00" <= t[0] <= "\u9fff" or t[0] in "【"):
                t = t[1:]
            q["text"] = t.strip()

    for q in active:
        log(f"  ACTIVE: {q['text'][:60]}")
    for q in backlog:
        log(f"  BACKLOG: {q['text'][:60]} ({q.get('week', '?')})")

    active_answered = get_active_answer_count(active, question_files)

    dashboard = read_dashboard()

    if active:
        active_lines = "\n".join("* " + q["text"] for q in active)
    else:
        active_lines = "* （暂无本周拷问）"
    active_block = f"{ACTIVE_START}\n{active_lines}\n{ACTIVE_END}"
    active_section = f"### 🎯 本周核心拷问 (Active)\n{active_block}"

    if backlog:
        backlog_lines = "\n".join(f"* {q['text']} ({q.get('week', '?')})" for q in backlog)
    else:
        backlog_lines = "* （暂无积压悬案）"
    backlog_block = f"{BACKLOG_START}\n{backlog_lines}\n{BACKLOG_END}"
    backlog_section = f"### ⏳ 历史待办悬案 (Backlog)\n{backlog_block}"

    old_q_pattern = re.escape(QUESTION_START) + r".*?" + re.escape(QUESTION_END)
    new_questions_section = active_section + "\n\n" + backlog_section

    if re.search(old_q_pattern, dashboard, flags=re.DOTALL):
        dashboard = re.sub(old_q_pattern, new_questions_section, dashboard, flags=re.DOTALL)
    else:
        active_pattern = re.escape(ACTIVE_START) + r".*?" + re.escape(ACTIVE_END)
        if re.search(active_pattern, dashboard, flags=re.DOTALL):
            dashboard = re.sub(active_pattern, active_block, dashboard, flags=re.DOTALL)
        else:
            log("WEEKLY_SCAN WARN: no active anchor found in dashboard")

        backlog_pattern = re.escape(BACKLOG_START) + r".*?" + re.escape(BACKLOG_END)
        if re.search(backlog_pattern, dashboard, flags=re.DOTALL):
            dashboard = re.sub(backlog_pattern, backlog_block, dashboard, flags=re.DOTALL)
        else:
            active_end_idx = dashboard.find(ACTIVE_END)
            if active_end_idx != -1:
                insert_pos = active_end_idx + len(ACTIVE_END)
                dashboard = dashboard[:insert_pos] + "\n\n" + backlog_section + dashboard[insert_pos:]

    answer_line = f"> 本周拷问 {len(active)} 条 | 已回答 {active_answered} 条 | 积压悬案 {len(backlog)} 条"
    answer_block = f"{ANSWER_START}\n{answer_line}\n{ANSWER_END}"

    answer_pattern = re.escape(ANSWER_START) + r".*?" + re.escape(ANSWER_END)
    if re.search(answer_pattern, dashboard, flags=re.DOTALL):
        dashboard = re.sub(answer_pattern, answer_block, dashboard, flags=re.DOTALL)
    else:
        backlog_end_idx = dashboard.find(BACKLOG_END)
        insert_anchor = BACKLOG_END if backlog_end_idx != -1 else ACTIVE_END
        anchor_idx = dashboard.find(insert_anchor)
        if anchor_idx != -1:
            insert_pos = anchor_idx + len(insert_anchor)
            dashboard = dashboard[:insert_pos] + "\n" + answer_block + dashboard[insert_pos:]
        else:
            log("WEEKLY_SCAN WARN: cannot insert answer stats")

    stats_lines = []
    for label, path in STAT_DIRS.items():
        n = count_files(path)
        stats_lines.append(f"| {label} | {n} |")
    stats_pattern = r"(\| 目录 \| 文件数 \|[\s\S]*?)(?=\n>)"
    new_stats = "| 目录 | 文件数 |\n|------|--------|\n" + "\n".join(stats_lines)
    if re.search(stats_pattern, dashboard, flags=re.DOTALL):
        dashboard = re.sub(stats_pattern, new_stats, dashboard, flags=re.DOTALL)

    ts = today.strftime("%Y-%m-%d %H:%M:%S")
    dashboard = re.sub(r"> 上次扫描:.*", f"> 上次扫描: {ts}", dashboard)

    write_dashboard(dashboard)
    log("WEEKLY_SCAN: dashboard updated")

    lines = dashboard.strip().split("\n")
    print("--- Dashboard Summary ---")
    for line in lines:
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", errors="replace").decode("ascii"))
    print("--- End ---")


if __name__ == "__main__":
    main()

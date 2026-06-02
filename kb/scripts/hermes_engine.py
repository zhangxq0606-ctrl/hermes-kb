import os
import re
import sys
import shutil
import json
import hashlib
import logging
import urllib.request
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_loader import load_dotenv

load_dotenv()

TZ = timezone(timedelta(hours=8))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(BASE_DIR, "inbox")
PROCESSING = os.path.join(BASE_DIR, "processing")
RAW = os.path.join(BASE_DIR, "raw")
MANUAL_TECH = os.path.join(BASE_DIR, "manual", "technical")
CORE_INSIGHT = os.path.join(BASE_DIR, "core", "insight")
CORE_NOTE = os.path.join(BASE_DIR, "core", "note")
PROCESSING_DEAD = os.path.join(PROCESSING, ".dead")
RETRY_STATE_FILE = os.path.join(BASE_DIR, "logs", ".retry_state.json")
MAX_RETRIES = 3
LOG_FILE = os.path.join(BASE_DIR, "logs", "hermes.log")

AI_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
AI_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
AI_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

os.makedirs(PROCESSING, exist_ok=True)
os.makedirs(RAW, exist_ok=True)
os.makedirs(MANUAL_TECH, exist_ok=True)
os.makedirs(CORE_INSIGHT, exist_ok=True)
os.makedirs(CORE_NOTE, exist_ok=True)
os.makedirs(PROCESSING_DEAD, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

engine_logger = logging.getLogger("hermes_engine")
engine_logger.setLevel(logging.INFO)
fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(message)s"))
if not engine_logger.handlers:
    engine_logger.addHandler(fh)


def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    engine_logger.info(line)
    print(line)


def load_retry_state():
    if os.path.exists(RETRY_STATE_FILE):
        with open(RETRY_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_retry_state(state):
    with open(RETRY_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def collect_background_context():
    parts = []
    scan_dirs = [CORE_INSIGHT, CORE_NOTE]
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for entry in sorted(os.listdir(scan_dir)):
            if not entry.endswith("_refined.md"):
                continue
            fp = os.path.join(scan_dir, entry)
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
                title_match = re.search(r"^#\s*(.+)$", text, re.MULTILINE)
                title = title_match.group(1).strip() if title_match else entry.replace("_refined.md", "")
                clean = re.sub(r"^#.*", "", text, flags=re.MULTILINE).strip()
                summary = clean[:120].replace("\n", " ").strip()
                name_no_ext = entry.replace("_refined.md", "")
                parts.append(f"{len(parts)+1}. {title}（{name_no_ext}.md）: {summary}")
                if len(parts) >= 15:
                    break
            except Exception:
                pass
        if len(parts) >= 15:
            break
    return "\n".join(parts) if parts else ""


URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')


def _extract_urls(text):
    return URL_PATTERN.findall(text)


def _fetch_article_content(url):
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode('utf-8', errors='replace')

        if 'dedao.cn' in url:
            return _fetch_dedao_article(html)

        clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<[^>]+>', ' ', clean)
        clean = re.sub(r'&nbsp;', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean[:8000] if clean else None
    except Exception as e:
        log(f"URL_FETCH_FAIL: {url} -> {e}")
        return None


def _fetch_dedao_article(html):
    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*)', html, re.DOTALL)
    if not m:
        return None
    raw = m.group(1)
    depth = 0
    end = 0
    for i, ch in enumerate(raw):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    state = json.loads(raw[:end])

    packet = state.get('packetInfo', {})
    title = packet.get('article_title', '')
    content_raw = state.get('articleInfo', {}).get('content', '')
    if isinstance(content_raw, str):
        content_blocks = json.loads(content_raw)
    else:
        content_blocks = content_raw

    output = f"# {title}\n\n"
    for block in content_blocks:
        t = block.get('type', '')
        if t == 'audio':
            continue
        text = block.get('text', '')
        if isinstance(text, str) and text.strip():
            output += text + "\n\n"

    return output.strip() if output.strip() else None


SYSTEM_PROMPT = """你是知识碎片分类引擎。评估用户输入的笔记，完成分类与打分。

分类标准（knowledge_type）：
- hard: 硬知识。工具、API、命令、纯代码、配置、操作步骤。显性、工具型。
- soft: 软智慧。商业判断、人生方法论、投资理念、行业观察、产品思维、认知升级。隐性、思想型。
- mixed: 既包含具体工具/技术实现，又包含独立认知判断或方法论反思。

评分要求（0-10分）：
- technical_score: 技术细节的实用度和具体度。
- cognitive_score: 启发性的问题、观点变化、商业认知张力。

输出格式：必须且仅能返回一个合法JSON，禁止Markdown标记（如 ```json）。
{
  "knowledge_type": "hard | soft | mixed",
  "technical_score": 0,
  "cognitive_score": 0,
  "summary": "一句话核心摘要",
  "refined_content": "结构化提纯后的Markdown（见下方规范）",
  "tech_split": "非必填",
  "insight_split": "非必填"
}

=== 背景知识库唤醒（务必执行）===
当输入中包含【背景知识库】段落时，表示系统中已存在与当前话题相关的历史认知资产。
在输出 refined_content 时，必须主动寻找新内容与历史资产的【递进】【反驳】【互补】关系，
在对应位置使用Markdown链接语法 [相关：文章标题](文章标题.md) 插入关联引用。
严禁在引用文章标题时保留 .md 扩展名以外的任何后缀。
若无明显关联，则忽略本条指令，不做任何链接。

=== 细胞分裂指令（knowledge_type=mixed 且 cognitive_score≥5 时强制执行）===
当评判结果同时满足 knowledge_type=mixed 且 cognitive_score≥5 时，必须额外输出两个长文本字段：
- tech_split: 纯技术实现、代码、命令、排错步骤。提取自原文的技术维度。
- insight_split: 纯商业判断、行业思考、方法论反思。提取自原文的认知维度。
两者内容不得重复，各自独立完整。若认知分不足5或非mixed类别，这两个字段留空字符串。

=== refined_content 分支策略（根据 knowledge_type 选择模板）===

当 knowledge_type = soft 时，使用以下三层认知骨架：

🎯 【一句话洞察】
- 用一句话刺穿整篇内容最核心的本质结论。不超过60字。

🗺️ 【核心逻辑链】
- 提炼作者推导结论的3~5步核心逻辑演进。
- 使用Markdown有序列表，格式：1. → 2. → 3. → ... 每步一句话。

📦 【金句与底层案例夹囊】
- 只保留最具认知张力的1~2个原生案例或硬核数据。
- 每个案例用"> "引用块包裹，末尾标注数据来源（如有）。
- 口水话、背景铺垫全部删掉。

---

当 knowledge_type = hard 时，使用以下三层技术骨架：

🔧 【用途定位】
- 解决什么问题？适用什么场景？（2-3句说清即可）

📋 【核心方法】
- 可直接复制使用的代码、命令、配置、操作步骤。
- 只保留最精简可实操版本，不用解释原理。
- 多步骤用有序列表，每个步骤一行。

⚠️ 【避坑指南】
- 配置陷阱、边界条件、常见报错。
- 每个坑一句话，用"- "列表。

---

当 knowledge_type = mixed 时：
- tech_split 使用技术型骨架（🔧用途定位 / 📋核心方法 / ⚠️避坑指南）
- insight_split 使用认知型骨架（🎯一句话洞察 / 🗺️核心逻辑链 / 📦金句夹囊）
- refined_content 仍默认走认知型骨架

凡是不符合对应骨架的 refined_content 都是不合格的。
严禁保留原文口水话、背景铺垫、客套话。"""


def ai_classify_and_score(content):
    import urllib.request
    import urllib.error

    if not AI_API_KEY:
        raise RuntimeError("API key not configured. Check .env file for DEEPSEEK_API_KEY.")

    url = f"{AI_BASE_URL}/v1/chat/completions"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]

    body = json.dumps({
        "model": AI_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 4000,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {AI_API_KEY}")

    resp = urllib.request.urlopen(req, timeout=90)
    raw = resp.read().decode("utf-8")
    data = json.loads(raw)

    reply = data["choices"][0]["message"]["content"].strip()

    if reply.startswith("```"):
        lines = reply.split("\n")
        reply = "\n".join(lines[1:])
        if reply.rstrip().endswith("```"):
            reply = reply[:reply.rfind("```")].rstrip()
    reply = reply.strip()

    return json.loads(reply)


def route_file(result, src, filename):
    kt = result.get("knowledge_type", "soft")
    tech_score = result.get("technical_score", 0)
    cog_score = result.get("cognitive_score", 0)
    refined = result.get("refined_content", "")

    targets = []

    if kt == "soft":
        if cog_score >= 3:
            targets.append(CORE_INSIGHT)
        else:
            targets.append(CORE_NOTE)
    elif kt == "hard":
        targets.append(MANUAL_TECH)
    else:  # mixed
        if cog_score >= 5:
            targets.append(CORE_INSIGHT)
        if tech_score >= 5:
            targets.append(MANUAL_TECH)
        if not targets:
            targets.append(CORE_INSIGHT)

    for d in targets:
        shutil.copy2(src, os.path.join(d, filename))

    if refined:
        refined_name = f"{os.path.splitext(filename)[0]}_refined.md"
        for d in targets:
            with open(os.path.join(d, refined_name), "w", encoding="utf-8") as f:
                f.write(refined)

    tech_split = result.get("tech_split", "")
    insight_split = result.get("insight_split", "")
    if kt == "mixed" and cog_score >= 5 and tech_split and insight_split:
        base = os.path.splitext(filename)[0]
        tech_name = f"tech_{base}.md"
        insight_name = f"insight_{base}.md"
        tech_content = f"💡 关联底层认知思考：[[{os.path.splitext(insight_name)[0]}]]\n\n{tech_split}"
        insight_content = f"🛠️ 关联具体技术实现：[[{os.path.splitext(tech_name)[0]}]]\n\n{insight_split}"
        with open(os.path.join(MANUAL_TECH, tech_name), "w", encoding="utf-8") as f:
            f.write(tech_content)
        with open(os.path.join(CORE_INSIGHT, insight_name), "w", encoding="utf-8") as f:
            f.write(insight_content)
        log(f"SPLIT {filename} -> tech_{base}.md + insight_{base}.md")

    backup = os.path.join(RAW, filename)
    shutil.copy2(src, backup)

    os.remove(src)

    rel_targets = ", ".join(os.path.relpath(d, BASE_DIR).replace("\\", "/") for d in targets)
    log(f"COMMIT {filename} -> {rel_targets} (kt={kt} tech={tech_score} cog={cog_score})")


def scan_inbox():
    files = []
    if not os.path.isdir(INBOX):
        return files
    for entry in os.listdir(INBOX):
        fp = os.path.join(INBOX, entry)
        if os.path.isfile(fp) and (entry.endswith(".md") or entry.endswith(".txt")):
            files.append((entry, fp))
    return sorted(files, key=lambda x: x[0])


def main():
    details = []
    success = 0
    failed = 0
    processed = 0

    # ---- Step 1: Move inbox -> processing ----
    inbox_files = scan_inbox()
    for filename, src in inbox_files:
        dst = os.path.join(PROCESSING, filename)
        shutil.move(src, dst)
        log(f"MOVE_INBOX {filename} -> processing")
        processed += 1

    if processed == 0:
        log("ENGINE: inbox empty, nothing to process")
        result = {
            "processed_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "details": [],
        }
        print(json.dumps(result, ensure_ascii=False))
        return result

    # ---- Step 2 & 3: Process + Commit ----
    retry_state = load_retry_state()
    dead_count = 0

    for entry in sorted(os.listdir(PROCESSING)):
        filepath = os.path.join(PROCESSING, entry)
        if not os.path.isfile(filepath) or not (entry.endswith(".md") or entry.endswith(".txt")):
            continue

        retries = retry_state.get(entry, 0)
        if retries >= MAX_RETRIES:
            dead_path = os.path.join(PROCESSING_DEAD, entry)
            shutil.move(filepath, dead_path)
            log(f"DEAD_LETTER {entry} -> .dead/ (retries={retries})")
            dead_count += 1
            details.append({
                "file": entry,
                "status": "dead_letter",
                "retries": retries,
            })
            continue

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            if not content.strip():
                os.remove(filepath)
                log(f"SKIP_EMPTY {entry}")
                continue

            urls = _extract_urls(content)
            fetched_parts = []
            for url in urls:
                log(f"URL_DETECTED {entry}: {url}")
                article = _fetch_article_content(url)
                if article:
                    fetched_parts.append(article)
                    log(f"URL_FETCHED {entry}: {len(article)} chars from {url[:80]}")
                    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                    base = os.path.splitext(entry)[0]
                    raw_source_name = f"{base}_source_{url_hash}.md"
                    raw_source_path = os.path.join(RAW, raw_source_name)
                    with open(raw_source_path, "w", encoding="utf-8") as f:
                        f.write(article)
                    log(f"COLD_BACKUP {entry}: {len(article)} chars -> raw/{raw_source_name}")
            if fetched_parts:
                ai_input = "\n\n---\n\n".join(fetched_parts) + "\n\n---\n\n[原文]\n" + content
            else:
                ai_input = content

            background_context = collect_background_context()
            if background_context:
                ai_input = f"【背景知识库（请在新内容与它们关联时使用 [相关：标题](标题.md) 插入链接）】\n{background_context}\n\n【待处理内容】\n{ai_input}"
                log(f"CONTEXT_INJECT {entry}: {len(background_context)} chars background")

            try:
                result = ai_classify_and_score(ai_input)
            except Exception as e_first:
                if fetched_parts:
                    log(f"AI_RETRY_NO_FETCH {entry}: {e_first}")
                    ai_input = content
                    result = ai_classify_and_score(ai_input)
                else:
                    raise

            route_file(result, filepath, entry)

            retry_state.pop(entry, None)
            success += 1
            details.append({
                "file": entry,
                "status": "committed",
                "knowledge_type": result.get("knowledge_type", ""),
                "technical_score": result.get("technical_score", 0),
                "cognitive_score": result.get("cognitive_score", 0),
            })

        except Exception as e:
            retry_state[entry] = retries + 1
            failed += 1
            log(f"FAIL {entry}: {e} (retry {retry_state[entry]}/{MAX_RETRIES})")
            details.append({
                "file": entry,
                "status": "failed",
                "error": str(e)[:120],
            })

    save_retry_state(retry_state)

    result = {
        "processed_count": processed,
        "success_count": success,
        "failed_count": failed,
        "dead_letter_count": dead_count,
        "details": details,
    }

    log(f"ENGINE_DONE: processed={processed} success={success} failed={failed} dead={dead_count}")
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()

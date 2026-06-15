import os
import re
import sys
import shutil
import json
import hashlib
import logging
import urllib.request
import concurrent.futures
import time
import yaml
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import semantic_index
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


_context_cache = {}
_context_cache_time = {}


def collect_background_context(content):
    global _context_cache, _context_cache_time
    cache_key = hashlib.md5(content.encode()).hexdigest()
    if cache_key in _context_cache and time.time() - _context_cache_time.get(cache_key, 0) < 300:
        return _context_cache[cache_key]

    results = semantic_index.search(content, top_k=8, min_score=0.3)
    if not results:
        _context_cache[cache_key] = ""
        _context_cache_time[cache_key] = time.time()
        return ""

    PATH_LABELS = {
        "core/insight": "软智慧/洞察",
        "core/note": "软智慧/灵感",
        "manual/technical": "硬知识",
    }

    groups = {}
    for rel_path, score, mtime in results:
        dir_key = "/".join(rel_path.replace("\\", "/").split("/")[:2])
        label = PATH_LABELS.get(dir_key, dir_key)
        full_path = os.path.join(BASE_DIR, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            title_match = re.search(r"^#\s*(.+)$", text, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else os.path.basename(rel_path).replace("_refined.md", "")
            clean = re.sub(r"^#.*", "", text, flags=re.MULTILINE).strip()
            summary = clean[:120].replace("\n", " ").strip()
            name_no_ext = os.path.basename(rel_path).replace("_refined.md", "")
            groups.setdefault(label, []).append(f"{len(groups.get(label, []))+1}. {title} | {name_no_ext} | {summary}")
        except Exception:
            pass

    if not groups:
        _context_cache[cache_key] = ""
        _context_cache_time[cache_key] = time.time()
        return ""

    parts = []
    for label in ["软智慧/洞察", "软智慧/灵感", "硬知识"]:
        if label in groups:
            parts.append(f"【{label}】")
            parts.extend(groups[label])
    result = "\n".join(parts)
    _context_cache[cache_key] = result
    _context_cache_time[cache_key] = time.time()
    return result


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
- hard: 硬知识。工具、API、命令、代码、配置、操作步骤、工具介绍与评测、安装教程、AI/Agent使用方案与最佳实践、提示词工程、AI工具使用技巧与方法论。显性、工具型。
  规则1：推荐/评测类文章，只要核心价值是"介绍工具或方法"，即使包含使用体验评价也归为 hard。
  规则2：内容核心围绕AI/Agent的使用方法、分层策略、工作流编排、提示词技巧等，即使不包含具体命令/代码，也归为 hard。AI和Agent本身就是工具，讨论如何使用它们就是硬知识。
- soft: 软智慧。商业判断、人生方法论、投资理念、行业观察、产品思维、认知升级。隐性、思想型。
  规则：去掉所有工具/技术细节后，认知观点本身是否仍有独立价值？若无，则不应归为 soft。AI/Agent使用技巧不归为此类。
- mixed: 仅当同时满足两个条件：(a) 包含可复制使用的代码/命令/配置（tech≥5），(b) 包含可脱离技术独立成立的深层认知判断（cog≥5）。仅满足一侧不触发 mixed。

评分要求（0-10分）：
- technical_score: 技术细节的实用度和具体度。出现可复制使用的命令/代码/配置/操作步骤才能 ≥5；AI/Agent使用方案、分层策略、工作流编排、提示词技巧等系统性方法论，即使无具体代码，也可根据其可操作性和实用度评 3~8 分。仅提到工具名称不算。
- cognitive_score: 启发性的问题、观点变化、商业认知张力。出现可脱离工具/技术独立成立的商业判断或方法论反思才能 ≥5。产品体验评价（"好用""丝滑"）不算。纯AI/Agent使用技巧类内容此项应 ≤3。

时效性判断（timeliness）：
- high: 核心方法论、底层思维模型、投资理念、认知框架。十年后仍然成立，不受时间衰减影响。
- medium: 一般性知识、行业观察、产品分析、工具使用经验。3~5年内有效，随时间逐渐过时。
- low: 高度时效性内容。某轮融资消息、版本更新日志、热点事件评论。短期内作废。
判断原则：去掉时间背景后，核心内容是否仍有独立价值？仍然成立 → high；完全无意义 → low；部分保留 → medium。

输出格式：必须且仅能返回一个合法JSON，禁止Markdown标记（如 ```json）。
{
  "knowledge_type": "hard | soft | mixed",
  "technical_score": 0,
  "cognitive_score": 0,
  "summary": "一句话核心摘要",
  "refined_content": "结构化提纯后的Markdown（见下方规范）",
  "tech_split": "非必填",
  "insight_split": "非必填",
  "timeliness": "high | medium | low",
  "usage_tag": "tool | principle | case | reflection | reference | opinion"
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

=== [[wikilinks]] 交叉引用规则（根据 knowledge_type 选择策略）===

当 knowledge_type = hard 时：
- 识别正文中出现的工具名、API 名、命令名、技术名词
- 在 refined_content 中对该名词使用 [[名词]] 包裹
- 仅对已在【背景知识库】中出现过的工具/技术做链接

当 knowledge_type = soft 时：
- 基于【背景知识库】中的摘要，判断新内容与哪些已有笔记存在【递进】【反驳】【互补】关系
- 在 refined_content 相关段落中插入 [[已有笔记标题]]（不含 _refined.md 后缀）
- 链接位置要紧贴相关论述，不要堆在文末

当 knowledge_type = mixed 时：
- tech_split 走 hard 策略，insight_split 走 soft 策略
- wikilinks 格式：[[文件名（不含后缀）]]，如 [[财商的修炼]]
- 禁止链接到自身
- 即使未在背景知识库中出现，如果正文讨论的实体已有明确的对应笔记，也应建立链接

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
- 解决什么问题？适用什么场景？包含哪些关键名词（工具名、服务名、网站域名）。

📋 【核心方法】
- 可直接复制使用的代码、命令、配置、操作步骤、URL 链接；或 AI/Agent 的系统性使用策略/分层方案/工作流步骤。
- 只保留最精简可实操版本，不用解释原理。
- 多步骤用有序列表，每个步骤一行。
- 若原始内容仅为工具/网站引用（仅有名称和URL），至少保留完整的工具名称和访问链接，加上一句用途描述。禁止写"无具体技术细节"。

⚠️ 【避坑指南】
- 配置陷阱、边界条件、常见报错。
- 每个坑一句话，用"- "列表。
- 若原始内容没有可识别的坑，此项可省略。禁止写"无具体技术细节"或"无"。

---

当 knowledge_type = mixed 时：
- tech_split 使用技术型骨架（🔧用途定位 / 📋核心方法 / ⚠️避坑指南）
- insight_split 使用认知型骨架（🎯一句话洞察 / 🗺️核心逻辑链 / 📦金句夹囊）
- refined_content 仍默认走认知型骨架

凡是不符合对应骨架的 refined_content 都是不合格的。
严禁保留原文口水话、背景铺垫、客套话。

=== usage_tag 标签规则 ===
除 knowledge_type 分类外，额外输出一个用途标签 usage_tag，取值如下：
- #tool: 工具型资源。推荐/评测/介绍某个工具、网站、软件、服务。
- #principle: 认知/方法论/思维模型。商业判断、投资理念、产品方法论。
- #case: 具体案例/复盘。某产品/事件的分析复盘、项目踩坑记录。
- #reflection: 自我反思/元认知。对自己的思考、行为模式的觉察和反思。
- #reference: 参考资料/备忘。配置文档、命令备忘、速查表、操作步骤存档。
- #opinion: 观点/评论/时事观察。对社会现象、行业动态的个人评论。
选择原则：取最贴切的一个。如果同时符合多个，选与笔记「使用场景」最相关的那个。
"""


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


def parse_frontmatter(text):
    """Parse YAML frontmatter from text. Returns (frontmatter_dict, body_text).
    If no valid frontmatter found, falls back to {} and returns full text as body.
    """
    if text.startswith('---'):
        parts = text.split('---', 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1])
                if isinstance(fm, dict):
                    return fm, parts[2].strip()
            except yaml.YAMLError:
                pass
    return {}, text


def _update_frontmatter_field(filepath, field, value):
    """Update a specific field in a file's frontmatter in-place."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()

    fm, body = parse_frontmatter(text)
    fm[field] = value

    fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    full = f"---\n{fm_str}\n---\n\n{body}\n"

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(full)


def _add_to_related(filepath, new_entry):
    """Add a new_entry to file's frontmatter.related, avoiding duplicates."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()

    fm, body = parse_frontmatter(text)
    existing = fm.get("related", [])
    if not existing:
        existing = []

    if not any(isinstance(e, dict) and e.get("file") == new_entry["file"] for e in existing):
        existing.append(new_entry)
        fm["related"] = existing

        fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
        full = f"---\n{fm_str}\n---\n\n{body}\n"

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(full)


def compute_related(refined_path, usage_tag, filename):
    """Scan core/insight/ and manual/technical/ for _refined.md files,
    compute relatedness score, and bidirectionally write frontmatter.related.

    Scoring rules:
      - same usage_tag: +3
      - filename character overlap >= 3: +1
    Total >= 3 triggers bidirectional related link.
    """
    if not os.path.exists(refined_path):
        log(f"COMPUTE_RELATED: {refined_path} not found, skipping")
        return

    base_name = os.path.splitext(filename)[0]
    new_refined_name = f"{base_name}_refined.md"

    # Read the new file to get its title
    with open(refined_path, 'r', encoding='utf-8', errors='replace') as f:
        new_text = f.read()

    new_fm, new_body = parse_frontmatter(new_text)
    title_match = re.search(r'^#\s+(.+)$', new_body, re.MULTILINE)
    new_title = title_match.group(1).strip() if title_match else base_name

    directories = [CORE_INSIGHT, MANUAL_TECH]
    matches = []

    for directory in directories:
        if not os.path.isdir(directory):
            continue
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith('_refined.md'):
                continue
            if fname == new_refined_name:
                continue

            fpath = os.path.join(directory, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                    text = fh.read()
            except Exception:
                continue

            # Parse frontmatter (new format) or fallback to old format
            fm, body = parse_frontmatter(text)
            if fm and 'usage_tag' in fm:
                other_tag = fm['usage_tag']
            else:
                tag_match = re.search(r'>\s*标签:\s*(\S+)', text)
                other_tag = tag_match.group(1) if tag_match else ''

            # Get title
            t_match = re.search(r'^#\s+(.+)$', body if fm else text, re.MULTILINE)
            other_title = t_match.group(1).strip() if t_match else fname.replace('_refined.md', '')

            # Scoring
            score = 0
            if other_tag == usage_tag:
                score += 3

            overlap = len(set(base_name) & set(fname.replace('_refined.md', '')))
            if overlap >= 3:
                score += 1

            if score >= 3:
                matches.append({
                    "file": fname.replace('_refined.md', ''),
                    "title": other_title,
                    "score": score,
                    "path": fpath,
                })

    if not matches:
        log(f"COMPUTE_RELATED {refined_path}: no matches found")
        return

    # Update the new file's frontmatter with related
    related_list = [{"file": m["file"], "title": m["title"]} for m in matches]
    _update_frontmatter_field(refined_path, "related", related_list)

    # Update each matched file's frontmatter to include the new file
    new_entry = {"file": base_name, "title": new_title}
    for m in matches:
        _add_to_related(m["path"], new_entry)

    log(f"COMPUTE_RELATED {refined_path}: {len(matches)} related entries written bidirectionally")


def route_file(result, src, filename):
    kt = result.get("knowledge_type", "soft")
    tech_score = result.get("technical_score", 0)
    cog_score = result.get("cognitive_score", 0)
    refined = result.get("refined_content", "")
    timeliness = result.get("timeliness", "medium")
    usage_tag = result.get("usage_tag", "reference")

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

    tech_split = result.get("tech_split", "")
    insight_split = result.get("insight_split", "")

    if refined:
        refined_name = f"{os.path.splitext(filename)[0]}_refined.md"
        written_refined_paths = []
        for d in targets:
            if d == MANUAL_TECH and tech_split:
                content_to_write = tech_split
            elif d == CORE_INSIGHT and insight_split:
                content_to_write = insight_split
            else:
                content_to_write = refined

            refined_path = os.path.join(d, refined_name)
            # Write with YAML frontmatter
            fm_data = {"timeliness": timeliness, "usage_tag": usage_tag}
            fm_str = yaml.dump(fm_data, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
            full = f"---\n{fm_str}\n---\n\n{content_to_write.strip()}\n"
            with open(refined_path, "w", encoding="utf-8") as f:
                f.write(full)
            written_refined_paths.append(refined_path)

        # Compute related notes and update frontmatter bidirectionally
        if written_refined_paths:
            compute_related(written_refined_paths[0], usage_tag, filename)

    if kt == "mixed" and cog_score >= 5 and tech_split and insight_split:
        base = os.path.splitext(filename)[0]
        tech_name = f"tech_{base}.md"
        insight_name = f"insight_{base}.md"
        tech_content = tech_split
        insight_content = insight_split
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

    # ---- Step 1.5: Count all files in processing (new + retry) ----
    for entry in os.listdir(PROCESSING):
        fp = os.path.join(PROCESSING, entry)
        if os.path.isfile(fp) and (entry.endswith(".md") or entry.endswith(".txt")):
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

    log(f"[进度] 发现 {processed} 个文件待处理")

    # ---- Step 2 & 3: Process + Commit ----
    retry_state = load_retry_state()
    dead_count = 0
    seq = 0

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

        seq += 1
        log(f"[进度] {seq}/{processed} 处理中: {entry}")
        start_time = time.time()

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            if not content.strip():
                os.remove(filepath)
                log(f"SKIP_EMPTY {entry}")
                continue

            urls = _extract_urls(content)
            fetched_parts = []
            if urls:
                def _fetch_single(url):
                    log(f"URL_DETECTED {entry}: {url}")
                    article = _fetch_article_content(url)
                    if article:
                        log(f"URL_FETCHED {entry}: {len(article)} chars from {url[:80]}")
                        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                        base = os.path.splitext(entry)[0]
                        raw_source_name = f"{base}_source_{url_hash}.md"
                        raw_source_path = os.path.join(RAW, raw_source_name)
                        with open(raw_source_path, "w", encoding="utf-8") as f:
                            f.write(article)
                        log(f"COLD_BACKUP {entry}: {len(article)} chars -> raw/{raw_source_name}")
                        return article
                    log(f"URL_FETCH_FAIL {entry}: {url[:80]}")
                    return None

                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = [executor.submit(_fetch_single, url) for url in urls]
                    for future in concurrent.futures.as_completed(futures):
                        result = future.result()
                        if result:
                            fetched_parts.append(result)
            if fetched_parts:
                ai_input = "\n\n---\n\n".join(fetched_parts) + "\n\n---\n\n[原文]\n" + content
            else:
                ai_input = content

            background_context = collect_background_context(content)
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
            log(f"[进度] {seq}/{processed} 完成: {entry} ({time.time() - start_time:.1f}s)")

        except Exception as e:
            retry_state[entry] = retries + 1
            failed += 1
            log(f"FAIL {entry}: {e} (retry {retry_state[entry]}/{MAX_RETRIES})")
            details.append({
                "file": entry,
                "status": "failed",
                "error": str(e)[:120],
            })
            log(f"[进度] {seq}/{processed} 完成: {entry} ({time.time() - start_time:.1f}s)")

    save_retry_state(retry_state)

    result = {
        "processed_count": processed,
        "success_count": success,
        "failed_count": failed,
        "dead_letter_count": dead_count,
        "details": details,
    }

    log(f"[进度] 全部完成，成功 {success} / 失败 {failed} / 总计 {processed}")
    log(f"ENGINE_DONE: processed={processed} success={success} failed={failed} dead={dead_count}")
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()

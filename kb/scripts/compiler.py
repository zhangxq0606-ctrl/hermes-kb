import os
import sys
import re
import json
import logging
import yaml
import numpy as np
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

MAX_GROUP_SIZE = 7
SIMILARITY_THRESHOLD = 0.5

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

            # Parse frontmatter first (new format), fallback to regex (old format)
            fm, body = parse_frontmatter(content)
            if fm and "usage_tag" in fm:
                tag = fm["usage_tag"]
            else:
                tag_match = TAG_PATTERN.search(content)
                tag = tag_match.group(1).strip() if tag_match else "unlabeled"

            related = []
            if fm and "related" in fm:
                raw = fm["related"]
                if isinstance(raw, list):
                    related = raw

            entries.append({
                "path": fp,
                "filename": fn,
                "content": content,
                "tag": tag,
                "related": related,
            })
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
    """Group entries by tag, then split large groups (>7) into subgroups."""
    groups = {}
    for e in entries:
        tag = e["tag"]
        if tag == "unlabeled":
            continue
        groups.setdefault(tag, []).append(e)

    # Filter out groups with < 2 members
    compilable = {}
    for tag, members in groups.items():
        if len(members) < 2:
            continue
        if len(members) <= MAX_GROUP_SIZE:
            compilable[tag] = [members]
        else:
            log(f"CLUSTER: tag={tag} has {len(members)} notes (>={MAX_GROUP_SIZE+1}), splitting...")
            subgroups = sub_cluster_by_related(members)

            # Detect if related signal is weak/absent: >50% entries are isolated singletons
            isolated_count = sum(1 for sg in subgroups if len(sg) <= 1)
            weak_related = isolated_count > len(members) * 0.5

            # Also check if any subgroup oversize
            oversize = any(len(sg) > MAX_GROUP_SIZE for sg in subgroups)

            if weak_related or oversize:
                if weak_related:
                    log(f"  RELATED_SPLIT weak signal (tag={tag}): {isolated_count}/{len(members)} isolated, falling back to similarity")
                else:
                    log(f"  RELATED_SPLIT oversize for tag={tag}, falling back to similarity")
                subgroups = _sub_cluster_by_similarity(members)

            # Final safety: split any oversize subgroup arbitrarily
            final_subgroups = []
            for sg in subgroups:
                for k in range(0, len(sg), MAX_GROUP_SIZE):
                    chunk = sg[k:k + MAX_GROUP_SIZE]
                    if len(chunk) >= 2:
                        final_subgroups.append(chunk)
            compilable[tag] = final_subgroups
            log(f"  SPLIT_RESULT tag={tag}: {len(members)} notes -> {len(final_subgroups)} subgroups " +
                f"(sizes: {[len(sg) for sg in final_subgroups]})")

    total_groups = sum(len(sgs) for sgs in compilable.values())
    tags_str = ", ".join(f"{tag}({len(sgs)}组)" for tag, sgs in compilable.items())
    log(f"CLUSTER: {total_groups} total compilable groups ({tags_str})")
    return compilable


def sub_cluster_by_related(members):
    """Split a list of members into subgroups using frontmatter.related BFS.
    Returns list of subgroups (each subgroup is a list of members).
    """
    # Build filename -> index mapping
    fn_to_idx = {}
    for i, m in enumerate(members):
        fn = m["filename"]
        if fn.endswith("_refined.md"):
            fn = fn[:-11]
        fn_to_idx[fn] = i

    # Build adjacency graph from related connections
    adj = {i: set() for i in range(len(members))}
    for i, m in enumerate(members):
        related = m.get("related", [])
        for rel in related:
            rel_fn = ""
            if isinstance(rel, dict):
                rel_fn = rel.get("file", "")
            elif isinstance(rel, str):
                rel_fn = rel
            if rel_fn and rel_fn in fn_to_idx:
                j = fn_to_idx[rel_fn]
                if i != j:
                    adj[i].add(j)
                    adj[j].add(i)

    # BFS for connected components
    visited = set()
    components = []
    for i in range(len(members)):
        if i not in visited:
            comp = []
            stack = [i]
            while stack:
                node = stack.pop()
                if node not in visited:
                    visited.add(node)
                    comp.append(node)
                    stack.extend(adj[node] - visited)
            components.append(comp)

    # Isolated nodes with no related edges: each becomes its own subgroup
    result = []
    for comp in components:
        group = [members[i] for i in comp]
        result.append(group)

    return result


def _sub_cluster_by_similarity(members):
    """Use semantic_index embeddings to compute pairwise similarities
    and split into subgroups (each ≤ MAX_GROUP_SIZE).
    """
    if len(members) <= MAX_GROUP_SIZE:
        return [members]

    # Get embeddings
    embeddings = []
    for m in members:
        try:
            vec = semantic_index.embed(m["content"][:2000])
        except Exception:
            vec = []
        embeddings.append(vec)

    embeddings = np.array(embeddings)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings = embeddings / norms

    # Build similarity matrix and adjacency graph
    sim_matrix = np.dot(embeddings, embeddings.T)

    adj = {i: set() for i in range(len(members))}
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            if sim_matrix[i][j] >= SIMILARITY_THRESHOLD:
                adj[i].add(j)
                adj[j].add(i)

    # BFS connected components
    visited = set()
    components = []
    for i in range(len(members)):
        if i not in visited:
            comp = []
            stack = [i]
            while stack:
                node = stack.pop()
                if node not in visited:
                    visited.add(node)
                    comp.append(node)
                    stack.extend(adj[node] - visited)
            components.append(comp)

    # Split any component > MAX_GROUP_SIZE arbitrarily
    result = []
    for comp in components:
        if len(comp) <= MAX_GROUP_SIZE:
            result.append([members[i] for i in comp])
        else:
            comp_members = [members[i] for i in comp]
            for k in range(0, len(comp_members), MAX_GROUP_SIZE):
                result.append(comp_members[k:k + MAX_GROUP_SIZE])

    # Fallback: if >50% isolated singletons, split arbitrarily
    isolated = sum(1 for sg in result if len(sg) <= 1)
    if isolated > len(members) * 0.5 and len(members) > MAX_GROUP_SIZE:
        log(f"  SIMILARITY_SPLIT insufficient ({isolated}/{len(members)} isolated), falling back to arbitrary split")
        result = []
        for k in range(0, len(members), MAX_GROUP_SIZE):
            result.append(members[k:k + MAX_GROUP_SIZE])

    return result


def safe_filename(name):
    safe = re.sub(r'[\\/:*?"<>|]', '', name)
    safe = re.sub(r'\s+', '_', safe)
    return safe


def call_ai_compile(members, tag, subgroup_idx):
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

        # Include related links if available
        related_info = ""
        related = m.get("related", [])
        if related:
            related_titles = []
            for rel in related:
                if isinstance(rel, dict):
                    related_titles.append(rel.get("title", rel.get("file", "")))
                elif isinstance(rel, str):
                    related_titles.append(rel)
            if related_titles:
                related_info = f"关联笔记：{', '.join(related_titles[:5])}"

        content_block = f"标题：{title}\n标签：{tag}\n"
        if related_info:
            content_block += f"{related_info}\n"
        content_block += f"内容：\n{m['content']}\n"
        user_parts.append(f"【笔记 {i}】\n{content_block}")

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


def write_topic(markdown_content, tag, subgroup_idx=0):
    filename = f"topic_{tag}.md" if subgroup_idx == 0 else f"topic_{tag}_{subgroup_idx + 1}.md"
    filepath = os.path.join(TOPIC_DIR, filename)

    # Ensure link format: remove _refined suffix
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
    for tag, subgroups in groups.items():
        for idx, members in enumerate(subgroups):
            log(f"COMPILING: tag={tag} subgroup={idx + 1}/{len(subgroups)} members={len(members)}")
            try:
                md = call_ai_compile(members, tag, idx)
            except Exception as e:
                log(f"  COMPILE_FAIL tag={tag} idx={idx}: {e}")
                continue
            filename = write_topic(md, tag, idx)
            topics.append(filename)

    log(f"COMPILER_DONE: compiled={len(topics)} topics={topics}")
    print(json.dumps({"compiled_count": len(topics), "topics": topics}, ensure_ascii=False))


if __name__ == "__main__":
    main()

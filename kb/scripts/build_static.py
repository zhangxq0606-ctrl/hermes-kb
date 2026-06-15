import os
import re
import json
import time
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
PUBLIC_DIR = os.path.join(ROOT_DIR, "public")

CATEGORIES = {
    "topic": {"path": os.path.join(BASE_DIR, "core", "topic"), "label": "编译论点"},
    "insight": {"path": os.path.join(BASE_DIR, "core", "insight"), "label": "软智慧"},
    "technical": {"path": os.path.join(BASE_DIR, "manual", "technical"), "label": "硬知识"},
    "question": {"path": os.path.join(BASE_DIR, "core", "question"), "label": "问题拷问"},
}

STYLE_CSS = """\
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fafbfc; color: #374151; line-height: 1.6; }
.container { max-width: 640px; margin: 0 auto; padding: 20px 16px; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }

header { text-align: center; padding: 32px 0 24px; }
header h1 { font-size: 28px; font-weight: 700; color: #1a1a2e; }
header p { font-size: 14px; color: #9ca3af; margin-top: 6px; }
nav { padding: 8px 0 16px; }
nav a { font-size: 14px; }

.index-hero { text-align: center; padding: 40px 0; }
.index-hero h2 { font-size: 20px; font-weight: 700; color: #1a1a2e; }
.index-hero .subtitle { font-size: 14px; color: #9ca3af; margin-top: 8px; }

.categories { display: flex; flex-direction: column; gap: 12px; margin-bottom: 32px; }
.cat-card { display: flex; align-items: center; gap: 12px; background: #fff; border-radius: 12px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.05); transition: background .15s, box-shadow .15s; text-decoration: none; color: #374151; border-left: 4px solid; }
.cat-card:hover { box-shadow: 0 2px 6px rgba(0,0,0,.08); text-decoration: none; }
.cat-card--insight { border-left-color: #d97706; }
.cat-card--insight:hover { background: #fffbf0; }
.cat-card--technical { border-left-color: #2563eb; }
.cat-card--technical:hover { background: #f0f4ff; }
.cat-card--question { border-left-color: #7c3aed; }
.cat-card--question:hover { background: #f8f4ff; }
.cat-card--topic { border-left-color: #d97706; }
.cat-card--topic:hover { background: #fdf6ee; }
.cat-card .cat-icon { font-size: 22px; flex-shrink: 0; }
.cat-card .cat-name { font-size: 16px; font-weight: 600; color: #1a1a2e; }
.cat-card .cat-desc { margin-left: auto; font-size: 12px; color: #9ca3af; }
.cat-card .cat-count { font-size: 13px; color: #9ca3af; }

.stats { text-align: center; padding: 16px 0; border-top: 1px solid #f3f4f6; }
.stats span { font-size: 13px; color: #9ca3af; }
.stats span + span { margin-left: 16px; }

.browse-header a { font-size: 14px; }
.browse-header h1 { font-size: 20px; }
.browse-header p { font-size: 13px; }

#search { margin-bottom: 20px; }

.doc-list { display: flex; flex-direction: column; gap: 10px; }
.doc-card { display: block; background: #fff; border-radius: 8px; padding: 16px 18px; box-shadow: 0 1px 3px rgba(0,0,0,.04); text-decoration: none; color: #374151; transition: box-shadow .12s; border-left: 3px solid #2563eb; }
.doc-card:hover { box-shadow: 0 2px 6px rgba(0,0,0,.08); text-decoration: none; }
.doc-card .doc-title { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
.doc-card .doc-preview { font-size: 13px; color: #9ca3af; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.doc-card .doc-info { font-size: 11px; color: #d1d5db; margin-top: 8px; display: flex; gap: 12px; align-items: center; }

.card-list { display: flex; flex-direction: column; gap: 12px; }
.card-group { border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); background: #fff; }
.card { display: block; padding: 14px 16px; text-decoration: none; color: #374151; transition: background .12s; }
.card:hover { background: #f8fafc; text-decoration: none; }
.card:not(:last-child) { border-bottom: 1px solid #f3f4f6; }
.card-refined { border-left: 3px solid; padding-left: 13px; }
.card-refined:hover { background: #f0f4ff; }
.card-original { background: #fafafa; padding: 8px 16px; border-left: 3px solid #e5e7eb; }
.card-original:hover { background: #f3f4f6; }
.card-original .card-title { font-size: 13px; font-weight: 400; color: #6b7280; }
.card-original .card-preview { display: none; }
.card-original .card-meta { font-size: 11px; color: #d1d5db; }
.card-title { font-size: 15px; font-weight: 600; color: #1a1a2e; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
.card-title .badge { display: inline-block; font-size: 10px; font-weight: 600; padding: 1px 7px; border-radius: 8px; white-space: nowrap; flex-shrink: 0; }
.badge-refined { }
.badge-original { color: #9ca3af; background: #f3f4f6; }
.card-preview { font-size: 13px; color: #9ca3af; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 6px; }
.card-meta { font-size: 12px; color: #d1d5db; }

.empty-state { text-align: center; padding: 40px 0; color: #d1d5db; font-size: 14px; }

.content { background: #fff; border-radius: 12px; padding: 24px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.05); line-height: 1.8; }
.content h1 { font-size: 20px; margin-bottom: 16px; }
.content h2 { font-size: 17px; margin: 20px 0 10px; }
.content h3 { font-size: 15px; margin: 16px 0 8px; }
.content p { margin: 8px 0; }
.content ul, .content ol { margin: 8px 0; padding-left: 24px; }
.content li { margin: 4px 0; }
.content blockquote { border-left: 3px solid #7c3aed; padding: 4px 12px; margin: 12px 0; color: #6b7280; background: #faf5ff; border-radius: 0 6px 6px 0; }
.content code { background: #f1f5f9; color: #334155; padding: 1px 4px; border-radius: 3px; font-size: 90%; }
.content pre { background: #1e293b; color: #e2e8f0; padding: 14px 16px; border-radius: 8px; overflow-x: auto; font-size: 88%; margin: 10px 0; line-height: 1.5; }
.content pre code { background: none; padding: 0; color: inherit; font-size: inherit; }

.wikilink { color: #7c3aed; border-bottom: 1px dashed #c4b5fd; text-decoration: none; } .wikilink:hover { color: #6d28d9; border-bottom-style: solid; }

footer { text-align: center; padding: 32px 0; font-size: 12px; color: #d1d5db; }
footer a { color: #d1d5db; }

@media (max-width: 640px) {
  .container { padding: 16px 12px; }
  .content { padding: 18px 14px; }
  .cat-card { padding: 16px 14px; }
}
"""


def html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_markdown(text, slug_map=None):
    lines = text.split("\n")
    out = []
    in_list = False
    in_ol = False
    in_blockquote = False
    in_code_block = False

    def close_all():
        nonlocal in_list, in_ol, in_blockquote
        if in_list:
            out.append("</ul>")
            in_list = False
        if in_ol:
            out.append("</ol>")
            in_ol = False
        if in_blockquote:
            out.append("</blockquote>")
            in_blockquote = False

    for line in lines:
        if in_code_block:
            if line.strip().startswith("```"):
                out.append("</code></pre>")
                in_code_block = False
            else:
                out.append(html_escape(line) + "\n")
            continue

        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = True
            out.append("<pre><code>")
            continue

        if stripped.startswith("# "):
            close_all()
            out.append("<h1>" + html_escape(stripped[2:]) + "</h1>")
            continue
        if stripped.startswith("## "):
            close_all()
            out.append("<h2>" + html_escape(stripped[3:]) + "</h2>")
            continue
        if stripped.startswith("### "):
            close_all()
            out.append("<h3>" + html_escape(stripped[4:]) + "</h3>")
            continue

        if stripped.startswith("> "):
            if not in_blockquote:
                close_all()
                out.append("<blockquote>")
                in_blockquote = True
            out.append(stripped[2:] + "<br>")
            continue
        elif in_blockquote:
            out.append("</blockquote>")
            in_blockquote = False

        ol_match = re.match(r"^(\d+)\.\s+(.+)", stripped)
        if ol_match:
            if not in_ol:
                if in_list:
                    out.append("</ul>")
                    in_list = False
                out.append("<ol>")
                in_ol = True
            out.append("<li>" + ol_match.group(2) + "</li>")
            continue
        elif in_ol:
            out.append("</ol>")
            in_ol = False

        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                if in_ol:
                    out.append("</ol>")
                    in_ol = False
                out.append("<ul>")
                in_list = True
            out.append("<li>" + stripped[2:] + "</li>")
            continue
        elif in_list:
            out.append("</ul>")
            in_list = False

        if stripped == "":
            out.append("")
        else:
            out.append("<p>" + stripped + "</p>")

    if in_list:
        out.append("</ul>")
    if in_ol:
        out.append("</ol>")
    if in_blockquote:
        out.append("</blockquote>")
    if in_code_block:
        out.append("</code></pre>")

    rendered = "\n".join(out)
    rendered = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', rendered)
    if slug_map:
        def _replace_wikilink(m):
            name = m.group(1)
            if name in slug_map:
                return '<a href="%s" class="wikilink">%s</a>' % (slug_map[name], name)
            return '<a href="/browse/insight.html?q=%s" class="wikilink">%s</a>' % (name, name)
        rendered = re.sub(r"\[\[([^\]]+)\]\]", _replace_wikilink, rendered)
    else:
        rendered = re.sub(r"\[\[([^\]]+)\]\]", r'<a href="/browse/insight.html?q=\1" class="wikilink">\1</a>', rendered)
    rendered = re.sub(r"`([^`]+)`", r"<code>\1</code>", rendered)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"\*(.+?)\*", r"<em>\1</em>", rendered)
    return rendered


def extract_meta(filepath):
    slug = os.path.splitext(os.path.basename(filepath))[0]
    if slug.endswith("_refined"):
        slug = slug[:-8]
    title = slug
    preview = ""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return title, preview

    # 优先使用 # 标题作为 title
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            title = stripped[2:].strip()
            break

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("🎯"):
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith("- "):
                    preview = next_line[2:].strip()
                else:
                    preview = next_line[:120]
            else:
                content_after = stripped.lstrip("🎯").strip().lstrip("【").rstrip("】").rstrip("-").strip()
                preview = content_after[:120]
            break
    if not preview:
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("```") and not stripped.startswith("🎯") and not stripped.startswith("🗺️") and not stripped.startswith("📦"):
                preview = stripped[:120]
                break
    return title, preview


def _extract_tag(filepath):
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'>\s*标签:\s*(\S+)', line.strip())
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


TAG_LABEL = {
    "principle": "认知/方法论",
    "tool": "工具型资源",
    "reflection": "自我反思",
    "opinion": "观点/评论",
    "case": "案例/复盘",
    "reference": "参考资料",
}


def _is_derived_file(fn):
    """排除系统派生文件：tech_/insight_ 分裂产物和 _source_ URL冷备。"""
    name = fn[:-3] if fn.endswith(".md") else fn
    if name.startswith("tech_") or name.startswith("insight_"):
        return True
    if "_source_" in name:
        return True
    return False


def _find_original_file(dirpath, slug):
    """寻找与 slug 对应的原始 .md 文件（非 _refined）。"""
    candidates = [
        os.path.join(dirpath, f"{slug}.md"),
        os.path.join(dirpath, f"{slug}.txt"),
    ]
    for fp in candidates:
        if os.path.isfile(fp):
            return fp
    return None


def discover_docs():
    groups = {key: [] for key in CATEGORIES}
    for key, cfg in CATEGORIES.items():
        dirpath = cfg["path"]
        if not os.path.isdir(dirpath):
            continue

        # topic 独立处理：每篇 topic_*.md 是独立卡片
        if key == "topic":
            for fn in sorted(os.listdir(dirpath)):
                if not fn.endswith(".md") or not fn.startswith("topic_"):
                    continue
                fp = os.path.join(dirpath, fn)
                if not os.path.isfile(fp):
                    continue
                title, preview = extract_meta(fp)
                mtime = os.path.getmtime(fp)
                slug = fn.rsplit(".", 1)[0]
                groups[key].append({
                    "slug": slug,
                    "title": title or slug,
                    "preview": preview,
                    "mtime": mtime,
                    "refined": {"filepath": fp, "rel_url": f"/detail/{key}/{slug}.html"},
                    "original": None,
                })
            groups[key].sort(key=lambda g: g["mtime"], reverse=True)
            continue

        # 扫描 base slugs：从 _refined.md 和普通 .md 收集
        base_slugs = set()
        for fn in os.listdir(dirpath):
            if not (fn.endswith(".md") or fn.endswith(".txt")):
                continue
            if _is_derived_file(fn):
                continue
            name = fn.rsplit(".", 1)[0]
            if name.endswith("_refined"):
                base_slugs.add(name[:-8])
            else:
                base_slugs.add(name)

        for slug in sorted(base_slugs):
            refined_path = os.path.join(dirpath, f"{slug}_refined.md")
            original_path = _find_original_file(dirpath, slug)

            if os.path.isfile(refined_path):
                title, preview = extract_meta(refined_path)
                mtime = os.path.getmtime(refined_path)
                tag_raw = _extract_tag(refined_path)
                tag_display = TAG_LABEL.get(tag_raw, "精炼") if tag_raw else "精炼"
                group = {
                    "slug": slug,
                    "title": title,
                    "preview": preview,
                    "mtime": mtime,
                    "tag": tag_display,
                    "refined": {
                        "filepath": refined_path,
                        "rel_url": f"/detail/{key}/{slug}.html",
                    },
                    "original": None,
                }
                if original_path:
                    group["original"] = {
                        "filepath": original_path,
                        "rel_url": f"/detail/{key}/{slug}_original.html",
                    }
                groups[key].append(group)
            elif original_path:
                # 只有原文，没有精炼版
                title, preview = extract_meta(original_path)
                mtime = os.path.getmtime(original_path)
                group = {
                    "slug": slug,
                    "title": title,
                    "preview": preview,
                    "mtime": mtime,
                    "refined": None,
                    "original": {
                        "filepath": original_path,
                        "rel_url": f"/detail/{key}/{slug}_original.html",
                    },
                }
                groups[key].append(group)

        groups[key].sort(key=lambda g: g["mtime"], reverse=True)
    return groups


def _time_str(timestamp):
    return time.strftime("%Y-%m-%d", time.localtime(timestamp))


def make_head(title, back_url=None):
    back = ""
    if back_url:
        back = f'<nav><a href="{back_url}">← 返回</a></nav>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(title)} - Xq.KB</title>
<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
<div class="container">
{back}
"""


def make_foot():
    return """<footer>Xq.KB · <a href="/">首页</a></footer>
</div>
</body>
</html>"""


def generate_index(docs):
    total = sum(len(v) for v in docs.values())
    path = os.path.join(PUBLIC_DIR, "index.html")
    os.makedirs(PUBLIC_DIR, exist_ok=True)

    cats_html = ""
    for key, cfg in CATEGORIES.items():
        count = len(docs.get(key, []))
        icons = {"topic": "📖", "insight": "💡", "technical": "⚙️", "question": "❓"}
        descs = {"topic": "综合 · 编译 · 主题结论", "insight": "洞察 · 认知 · 思维框架", "technical": "工具 · 命令 · 实操方法", "question": "反思 · 追问 · 深度思考"}
        cats_html += f"""<a class="cat-card cat-card--{key}" href="/browse/{key}.html">
  <span class="cat-icon">{icons.get(key, "")}</span>
  <span class="cat-name">{cfg["label"]}</span>
  <span class="cat-desc">{descs.get(key, "")}</span>
</a>"""

    html = make_head("首页") + f"""
<header>
  <h1>Xq.KB</h1>
  <p>静态文档浏览 · 全文检索</p>
</header>
<div id="search"></div>
<div class="index-hero">
  <div class="categories">
    {cats_html}
  </div>
</div>
<div class="stats">
  <span>{total} 篇文档</span>
  <span>{len(CATEGORIES)} 个分类</span>
</div>
""" + make_foot()

    html += """<script>
window.addEventListener('DOMContentLoaded', function() {
  new PagefindUI({ element: "#search" });
});
</script>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  {path}")


CARD_COLORS = [
    "#2563eb", "#d97706", "#7c3aed", "#059669", "#dc2626",
    "#0891b2", "#c026d3", "#65a30d", "#e11d48", "#4f46e5",
]


def generate_browse(docs):
    import random

    for key, cfg in CATEGORIES.items():
        groups = docs.get(key, [])
        path = os.path.join(PUBLIC_DIR, "browse", f"{key}.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        list_html = ""
        if not groups:
            list_html = '<div class="empty-state">暂无文档</div>'
        elif key == "topic":
            for g in groups:
                if g.get("refined"):
                    d = g["refined"]
                    preview_html = ""
                    if g.get("preview"):
                        preview_html = '<div class="card-preview">%s</div>' % html_escape(g["preview"])
                    list_html += f"""<a class="card card-refined" href="{d['rel_url']}" style="border-left-color:#d97706">
  <div class="card-title">📖 {html_escape(g['title'])}</div>
  {preview_html}
  <div class="card-meta">{_time_str(g['mtime'])}</div>
</a>"""
        else:
            for g in groups:
                color = random.choice(CARD_COLORS)
                list_html += '<div class="card-group">'

                if g.get("refined"):
                    d = g["refined"]
                    preview_html = ""
                    if g.get("preview"):
                        preview_html = '<div class="card-preview">%s</div>' % html_escape(g["preview"])
                    list_html += f"""<a class="card card-refined" href="{d['rel_url']}" style="border-left-color:{color}">
  <div class="card-title">✨ {html_escape(g['title'])} <span class="badge badge-refined" style="color:{color};background:{color}1a">{g.get('tag', '精炼')}</span></div>
  {preview_html}
  <div class="card-meta">{_time_str(g['mtime'])}</div>
</a>"""

                if g.get("original"):
                    d = g["original"]
                    list_html += f"""<a class="card card-original" href="{d['rel_url']}">
  <div class="card-title">{html_escape(g['title'])} <span class="badge badge-original">原文</span></div>
  <div class="card-meta">{_time_str(g['mtime'])}</div>
</a>"""

                list_html += '</div>'

        html = make_head(cfg["label"], "/") + f"""
<header class="browse-header">
  <h1>{cfg["label"]}</h1>
  <p>{len(groups)} 篇</p>
</header>
<div class="card-list">
  {list_html}
</div>
""" + make_foot()

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  {path}")


def generate_detail(docs):
    # 构建 slug → rel_url 映射表，用于 wikilinks 编译期查表替换
    slug_to_url = {}
    for key, groups in docs.items():
        for g in groups:
            if g.get("refined"):
                slug_to_url[g["slug"]] = g["refined"]["rel_url"]
            elif g.get("original"):
                slug_to_url[g["slug"]] = g["original"]["rel_url"]

    for key, groups in docs.items():
        for g in groups:
            cat_label = CATEGORIES[key]["label"]

            # 生成精炼版详情页
            if g.get("refined"):
                d = g["refined"]
                detail_path = os.path.join(PUBLIC_DIR, "detail", key, f"{g['slug']}.html")
                os.makedirs(os.path.dirname(detail_path), exist_ok=True)

                try:
                    with open(d["filepath"], "r", encoding="utf-8") as f:
                        raw = f.read()
                except Exception:
                    raw = "（无法读取文件）"

                content = _render_detail_markdown(raw, slug_map=slug_to_url)

                # 如果有原文，添加原文链接
                original_link = ""
                if g.get("original"):
                    original_link = f'<div style="margin-top:16px;padding-top:12px;border-top:1px solid #f3f4f6;"><a href="{g["original"]["rel_url"]}" style="font-size:14px;color:#9ca3af;">← 查看原文</a></div>'

                html = make_head(g["title"] + " - Xq.KB", f"/browse/{key}.html") + f"""
<header class="browse-header">
  <h1>{html_escape(g['title'])}</h1>
  <p>{cat_label} · {_time_str(g['mtime'])} · 精炼版</p>
</header>
<div class="content">
{content}
</div>
{original_link}
""" + make_foot()

                with open(detail_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"  {detail_path}")

            # 生成原文详情页
            if g.get("original"):
                d = g["original"]
                detail_path = os.path.join(PUBLIC_DIR, "detail", key, f"{g['slug']}_original.html")
                os.makedirs(os.path.dirname(detail_path), exist_ok=True)

                try:
                    with open(d["filepath"], "r", encoding="utf-8") as f:
                        raw = f.read()
                except Exception:
                    raw = "（无法读取文件）"

                content = _render_detail_markdown(raw, slug_map=slug_to_url)

                # 如果有精炼版，添加精炼版链接
                refined_link = ""
                if g.get("refined"):
                    refined_link = f'<div style="margin-top:16px;padding-top:12px;border-top:1px solid #f3f4f6;"><a href="{g["refined"]["rel_url"]}" style="font-size:14px;color:#2563eb;">← 查看精炼版</a></div>'

                html = make_head(g["title"] + " - Xq.KB", f"/browse/{key}.html") + f"""
<header class="browse-header">
  <h1>{html_escape(g['title'])}</h1>
  <p>{cat_label} · {_time_str(g['mtime'])} · 原文</p>
</header>
<div class="content">
{content}
</div>
{refined_link}
""" + make_foot()

                with open(detail_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"  {detail_path}")


def _strip_frontmatter(text):
    """Strip YAML frontmatter (--- ... ---) from the beginning of a markdown file."""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip()
    return text


def _render_detail_markdown(text, slug_map=None):
    rendered = render_markdown(_strip_frontmatter(text), slug_map=slug_map)
    rendered = rendered.replace(
        '<a href="',
        '<a target="_blank" rel="noopener" href="'
    )
    return rendered


def generate_style():
    assets_dir = os.path.join(PUBLIC_DIR, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    path = os.path.join(assets_dir, "style.css")
    with open(path, "w", encoding="utf-8") as f:
        f.write(STYLE_CSS)
    print(f"  {path}")


def main():
    print("[build_static] 开始生成静态页面...")

    if os.path.exists(PUBLIC_DIR):
        shutil.rmtree(PUBLIC_DIR)
    os.makedirs(PUBLIC_DIR, exist_ok=True)

    print("[1/5] 发现文档...")
    docs = discover_docs()
    for key, items in docs.items():
        print(f"  {key}: {len(items)} 篇")

    print("[2/5] 生成样式...")
    generate_style()

    print("[3/5] 生成首页...")
    generate_index(docs)

    print("[4/5] 生成分类浏览页...")
    generate_browse(docs)

    print("[5/5] 生成文档详情页...")
    generate_detail(docs)

    total = sum(len(v) for v in docs.values())
    print(f"\n[build_static] 完成: {total} 篇文档, 输出至 {PUBLIC_DIR}")



if __name__ == "__main__":
    main()

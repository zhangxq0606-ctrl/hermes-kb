import os
import re
import json
import time
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
PUBLIC_DIR = os.path.join(ROOT_DIR, "public")

CATEGORIES = {
    "insight": {"path": os.path.join(BASE_DIR, "core", "insight"), "label": "软智慧"},
    "technical": {"path": os.path.join(BASE_DIR, "manual", "technical"), "label": "硬知识"},
    "question": {"path": os.path.join(BASE_DIR, "core", "question"), "label": "问题拷问"},
}

STYLE_CSS = """\
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #222; line-height: 1.6; }
.container { max-width: 640px; margin: 0 auto; padding: 20px 16px; }
a { color: #4a90d9; text-decoration: none; }
a:hover { text-decoration: underline; }

header { text-align: center; padding: 32px 0 24px; }
header h1 { font-size: 24px; font-weight: 700; color: #1a1a1a; }
header p { font-size: 14px; color: #888; margin-top: 4px; }
nav { padding: 8px 0 16px; }
nav a { font-size: 14px; }

.index-hero { text-align: center; padding: 40px 0; }
.index-hero h2 { font-size: 20px; font-weight: 700; color: #1a1a1a; }
.index-hero .subtitle { font-size: 14px; color: #888; margin-top: 8px; }

.categories { display: flex; flex-direction: column; gap: 12px; margin-bottom: 32px; }
.cat-card { display: block; background: #fff; border-radius: 10px; padding: 20px 18px; box-shadow: 0 1px 3px rgba(0,0,0,.06); transition: box-shadow .15s; text-decoration: none; color: #222; }
.cat-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.1); text-decoration: none; }
.cat-card .cat-icon { font-size: 24px; margin-bottom: 8px; }
.cat-card .cat-name { font-size: 17px; font-weight: 600; }
.cat-card .cat-count { font-size: 13px; color: #888; margin-top: 4px; }

.stats { text-align: center; padding: 16px 0; border-top: 1px solid #eee; }
.stats span { font-size: 13px; color: #888; }
.stats span + span { margin-left: 16px; }

.browse-header a { font-size: 14px; }
.browse-header h1 { font-size: 20px; }
.browse-header p { font-size: 13px; }

#search { margin-bottom: 20px; }

.doc-list { display: flex; flex-direction: column; gap: 10px; }
.doc-card { display: block; background: #fff; border-radius: 8px; padding: 16px 18px; box-shadow: 0 1px 3px rgba(0,0,0,.04); text-decoration: none; color: #222; transition: box-shadow .12s; border-left: 3px solid #4a90d9; }
.doc-card:hover { box-shadow: 0 2px 6px rgba(0,0,0,.08); text-decoration: none; }
.doc-card .doc-title { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
.doc-card .doc-preview { font-size: 13px; color: #999; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.doc-card .doc-info { font-size: 11px; color: #bbb; margin-top: 8px; display: flex; gap: 12px; align-items: center; }

.empty-state { text-align: center; padding: 40px 0; color: #bbb; font-size: 14px; }

.content { background: #fff; border-radius: 8px; padding: 24px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.08); line-height: 1.8; }
.content h1 { font-size: 20px; margin-bottom: 16px; }
.content h2 { font-size: 17px; margin: 20px 0 10px; }
.content h3 { font-size: 15px; margin: 16px 0 8px; }
.content p { margin: 8px 0; }
.content ul, .content ol { margin: 8px 0; padding-left: 24px; }
.content li { margin: 4px 0; }
.content blockquote { border-left: 3px solid #4a90d9; padding: 4px 12px; margin: 12px 0; color: #555; background: #f8f9fa; }
.content code { background: #f0f0f0; padding: 1px 4px; border-radius: 3px; font-size: 90%; }
.content pre { background: #2d2d2d; color: #d4d4d4; padding: 14px 16px; border-radius: 8px; overflow-x: auto; font-size: 88%; margin: 10px 0; line-height: 1.5; }
.content pre code { background: none; padding: 0; color: inherit; font-size: inherit; }

footer { text-align: center; padding: 32px 0; font-size: 12px; color: #bbb; }
footer a { color: #bbb; }

@media (max-width: 640px) {
  .container { padding: 16px 12px; }
  .content { padding: 18px 14px; }
  .cat-card { padding: 16px 14px; }
}
"""


def html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_markdown(text):
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


def discover_docs():
    docs = {key: [] for key in CATEGORIES}
    for key, cfg in CATEGORIES.items():
        dirpath = cfg["path"]
        if not os.path.isdir(dirpath):
            continue
        for fn in sorted(os.listdir(dirpath)):
            if not fn.endswith("_refined.md"):
                continue
            fp = os.path.join(dirpath, fn)
            if not os.path.isfile(fp):
                continue
            title, preview = extract_meta(fp)
            slug = fn.rsplit("_refined.md", 1)[0]
            mtime = os.path.getmtime(fp)
            docs[key].append({
                "slug": slug,
                "title": title,
                "preview": preview,
                "mtime": mtime,
                "filepath": fp,
                "rel_url": f"/detail/{key}/{slug}.html",
            })
        docs[key].sort(key=lambda d: d["mtime"], reverse=True)
    return docs


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
<title>{html_escape(title)} - Hermes</title>
<link rel="stylesheet" href="/assets/style.css">
<script src="/pagefind/pagefind-ui.js"></script>
</head>
<body>
<div class="container">
{back}
"""


def make_foot():
    return """<footer>Hermes KB · <a href="/">首页</a></footer>
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
        icons = {"insight": "💡", "technical": "⚙️", "question": "❓"}
        cats_html += f"""<a class="cat-card" href="/browse/{key}.html">
  <div class="cat-icon">{icons.get(key, "")}</div>
  <div class="cat-name">{cfg["label"]}</div>
  <div class="cat-count">{count} 篇文档</div>
</a>"""

    html = make_head("Hermes 知识库") + f"""
<header>
  <h1>Hermes 知识库</h1>
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
  <span>3 个分类</span>
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


def generate_browse(docs):
    for key, cfg in CATEGORIES.items():
        items = docs.get(key, [])
        path = os.path.join(PUBLIC_DIR, "browse", f"{key}.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        list_html = ""
        if not items:
            list_html = '<div class="empty-state">暂无文档</div>'
        else:
            for d in items:
                list_html += f"""<a class="doc-card" href="{d['rel_url']}">
  <div class="doc-title">{html_escape(d['title'])}</div>
  <div class="doc-preview">{html_escape(d['preview'])}</div>
  <div class="doc-info"><span>{_time_str(d['mtime'])}</span><span>{cfg['label']}</span></div>
</a>"""

        html = make_head(cfg["label"], "/") + f"""
<header class="browse-header">
  <h1>{cfg["label"]}</h1>
  <p>{len(items)} 篇文档</p>
</header>
<div class="doc-list">
  {list_html}
</div>
""" + make_foot()

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  {path}")


def generate_detail(docs):
    for key, items in docs.items():
        for d in items:
            path = os.path.join(PUBLIC_DIR, "detail", key, f"{d['slug']}.html")
            os.makedirs(os.path.dirname(path), exist_ok=True)

            try:
                with open(d["filepath"], "r", encoding="utf-8") as f:
                    raw = f.read()
            except Exception:
                raw = "（无法读取文件）"

            content = _render_detail_markdown(raw)

            cat_label = CATEGORIES[key]["label"]
            html = make_head(d["title"] + " - Hermes", f"/browse/{key}.html") + f"""
<header class="browse-header">
  <h1>{html_escape(d['title'])}</h1>
  <p>{cat_label} · {_time_str(d['mtime'])}</p>
</header>
<div class="content">
{content}
</div>
""" + make_foot()

            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  {path}")


def _render_detail_markdown(text):
    rendered = render_markdown(text)
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
    print("[build_static] 提示: 运行 'npx pagefind --site public' 生成搜索索引")


if __name__ == "__main__":
    main()

import os
import sys
import threading
import time
import hashlib
import json
import subprocess
from datetime import datetime

from flask import Flask, request, jsonify, Response, stream_with_context

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qa_engine
import semantic_index

app = Flask(__name__)

BASE_DIR = qa_engine.BASE_DIR
BROWSE_ROOTS = [
    ("core/insight", os.path.join(BASE_DIR, "core", "insight")),
    ("core/note", os.path.join(BASE_DIR, "core", "note")),
    ("core/question", os.path.join(BASE_DIR, "core", "question")),
    ("manual/technical", os.path.join(BASE_DIR, "manual", "technical")),
]

_reindex_lock = threading.Lock()
_reindex_interval = 300
_reindex_hash_file = os.path.join(semantic_index.CACHE_PATH + ".state")

_pipeline_state = {"running": False, "last_run": None, "last_result": None}
_pipeline_lock = threading.Lock()


def _watchdog_pipeline():
    engine_script = os.path.join(BASE_DIR, "scripts", "hermes_engine.py")
    while True:
        time.sleep(60)
        inbox_dir = os.path.join(BASE_DIR, "inbox")
        if not os.path.isdir(inbox_dir):
            continue
        md_files = [f for f in os.listdir(inbox_dir)
                    if os.path.isfile(os.path.join(inbox_dir, f))
                    and (f.endswith(".md") or f.endswith(".txt"))]
        if not md_files:
            continue
        try:
            _run_pipeline()
        except Exception:
            pass


def _run_pipeline():
    with _pipeline_lock:
        if _pipeline_state["running"]:
            return _pipeline_state
        _pipeline_state["running"] = True
        _pipeline_state["last_result"] = None

    try:
        engine_script = os.path.join(BASE_DIR, "scripts", "hermes_engine.py")
        cp = subprocess.run(
            [sys.executable, engine_script],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=180,
        )
        result = {"ok": cp.returncode == 0, "stdout": cp.stdout[-500:], "stderr": cp.stderr[-300:]}
        _do_reindex()
    except subprocess.TimeoutExpired:
        result = {"ok": False, "error": "pipeline timed out (180s)"}
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    finally:
        with _pipeline_lock:
            _pipeline_state["running"] = False
            _pipeline_state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _pipeline_state["last_result"] = result

    return result


def _watchdog_reindex():
    while True:
        time.sleep(_reindex_interval)
        try:
            _do_reindex()
        except Exception:
            pass


def _do_reindex():
    with _reindex_lock:
        result = semantic_index.build_index()
    if os.path.exists(semantic_index.CACHE_PATH):
        with open(semantic_index.CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        cache["last_result"] = result
        with open(semantic_index.CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    return result


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes 知识库</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #222; line-height: 1.6; }
.container { max-width: 640px; margin: 0 auto; padding: 20px 16px; }
header { text-align: center; padding: 32px 0 24px; }
header h1 { font-size: 24px; font-weight: 700; color: #1a1a1a; }
header p { font-size: 14px; color: #888; margin-top: 4px; }
.search-box { display: flex; gap: 8px; margin-bottom: 16px; }
.search-box input { flex: 1; padding: 12px 16px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; outline: none; transition: border-color .2s; }
.search-box input:focus { border-color: #4a90d9; }
.search-box button { padding: 12px 20px; background: #4a90d9; color: #fff; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; transition: background .2s; }
.search-box button:hover { background: #3a7bc8; }
.search-box button:disabled { background: #aaa; cursor: not-allowed; }
.index-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; font-size: 13px; color: #888; }
.index-bar button { background: none; border: 1px solid #ddd; padding: 4px 10px; border-radius: 4px; color: #888; cursor: pointer; font-size: 12px; }
.index-bar button:hover { border-color: #4a90d9; color: #4a90d9; }
.index-bar button:disabled { opacity: .5; cursor: not-allowed; }
.answer-area { display: none; background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.answer-area.show { display: block; }
.answer-area .answer-text { font-size: 15px; word-break: break-word; line-height: 1.7; }
.answer-area .answer-text p { margin: 0 0 8px 0; }
.answer-area .answer-text p:last-child { margin-bottom: 0; }
.answer-area .sources { margin-top: 16px; padding-top: 12px; border-top: 1px solid #eee; }
.answer-area .sources h3 { font-size: 13px; color: #888; margin-bottom: 6px; }
.answer-area .sources a { display: block; font-size: 14px; color: #4a90d9; text-decoration: none; padding: 3px 0; }
.answer-area .sources a:hover { text-decoration: underline; }
.loading { display: none; text-align: center; padding: 40px 0; color: #888; }
.loading.show { display: block; }
.footer { text-align: center; padding: 24px 0; }
.footer a { color: #4a90d9; text-decoration: none; font-size: 14px; }
.footer a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
<header>
  <h1>Hermes 知识库</h1>
  <p>基于语义搜索的智能问答</p>
</header>
<div class="search-box">
  <input id="question" type="text" placeholder="输入你的问题..." autofocus>
  <button id="ask-btn">提问</button>
</div>
<div class="index-bar">
  <div>
      <div id="pipeline-status" style="font-size:12px;color:#aaa;">管道: --</div>
    </div>
  <div>
    <button id="pipeline-btn">处理收件箱</button>
    <button id="reindex-btn">重建索引</button>
  </div>
</div>
<div class="loading" id="loading">正在思考...</div>
<div class="answer-area" id="answer-area">
  <div class="answer-text" id="answer-text"></div>
  <div class="sources" id="sources"></div>
</div>
<div class="footer">
  <a href="/browse">浏览知识库</a>
</div>
</div>
<script>
document.addEventListener('DOMContentLoaded', function() {
var input = document.getElementById('question');
var btn = document.getElementById('ask-btn');
var loading = document.getElementById('loading');
var answerArea = document.getElementById('answer-area');
var answerText = document.getElementById('answer-text');
var sources = document.getElementById('sources');
var reindexBtn = document.getElementById('reindex-btn');
var pipelineStatus = document.getElementById('pipeline-status');
var pipelineBtn = document.getElementById('pipeline-btn');

btn.addEventListener('click', doAsk);

function updatePipelineStatus() {
  fetch('/pipeline/status')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.running) {
        pipelineStatus.textContent = '管道: 处理中...';
        pipelineBtn.disabled = true;
      } else if (d.last_run) {
        pipelineStatus.textContent = '管道: ' + d.last_run;
        pipelineBtn.disabled = false;
      } else {
        pipelineStatus.textContent = '管道: 未运行';
        pipelineBtn.disabled = false;
      }
    })
    .catch(function() { pipelineStatus.textContent = '管道: --'; });
}
updatePipelineStatus();

function doPipeline() {
  pipelineBtn.disabled = true;
  pipelineBtn.textContent = '处理中...';
  pipelineStatus.textContent = '管道: 处理中...';
  fetch('/pipeline/run', {method:'POST'})
    .then(function(r) { return r.json(); })
    .then(function(d) {
      updatePipelineStatus();
    })
    .catch(function() {
      pipelineBtn.disabled = false;
      pipelineBtn.textContent = '处理收件箱';
      pipelineStatus.textContent = '管道: 失败';
    });
}

function doReindex() {
  reindexBtn.disabled = true;
  reindexBtn.textContent = '更新中...';
  fetch('/reindex', {method:'POST'})
    .then(function(r) { return r.json(); })
    .then(function(d) {
      reindexBtn.textContent = '重建索引';
      reindexBtn.disabled = false;
    })
    .catch(function() {
      reindexBtn.textContent = '重建索引';
      reindexBtn.disabled = false;
    });
}

pipelineBtn.addEventListener('click', doPipeline);
reindexBtn.addEventListener('click', doReindex);

input.addEventListener('keydown', function(e) {
  if (e.key === 'Enter') doAsk();
});

function doAsk() {
  var q = input.value.trim();
  if (!q) return;
  btn.disabled = true;
  answerText.textContent = '';
  sources.innerHTML = '';
  loading.classList.add('show');
  answerArea.classList.add('show');

  var sec = 0;
  var timer = setInterval(function() {
    sec++;
    loading.textContent = '正在思考... ' + sec + 's';
  }, 1000);

  fetch('/ask', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question: q})
  }).then(function(r) { return r.json(); })
  .then(function(d) {
    clearInterval(timer);
    loading.classList.remove('show');
    var answerHtml = d.answer
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
      .replace(/\\n\\n/g, '</p><p>')
      .replace(/\\n/g, '<br>');
    answerText.innerHTML = '<p>' + answerHtml + '</p>';
    if (d.sources && d.sources.length > 0) {
      var html = '<h3>引用来源</h3>';
      d.sources.forEach(function(s) {
        html += '<a href="/view/' + encodeURIComponent(s) + '">' + s + '</a>';
      });
      sources.innerHTML = html;
    }
    btn.disabled = false;
  }).catch(function(err) {
    clearInterval(timer);
    answerText.textContent = '请求失败：' + err.message;
    loading.classList.remove('show');
    btn.disabled = false;
  });
}
});
</script>
</body>
</html>"""

BROWSE_HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>浏览知识库 - Hermes</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #222; line-height: 1.6; }
.container { max-width: 640px; margin: 0 auto; padding: 20px 16px; }
header { text-align: center; padding: 32px 0 24px; }
header h1 { font-size: 22px; font-weight: 700; }
header a { font-size: 14px; color: #4a90d9; text-decoration: none; }
header a:hover { text-decoration: underline; }

.tab-bar { display: flex; gap: 4px; margin-bottom: 16px; border-bottom: 2px solid #eee; }
.tab { flex: 1; padding: 10px 4px; background: none; border: none; border-bottom: 2px solid transparent; margin-bottom: -2px; font-size: 14px; color: #999; cursor: pointer; transition: color .2s, border-color .2s; }
.tab:hover { color: #555; }
.tab.active { color: #4a90d9; border-bottom-color: #4a90d9; font-weight: 600; }

.tab-area {}

.filter-row { display: flex; gap: 8px; margin-bottom: 14px; }
.filter { padding: 4px 12px; background: #f0f0f0; border: none; border-radius: 12px; color: #888; cursor: pointer; font-size: 13px; transition: background .2s, color .2s; }
.filter:hover { background: #e0e0e0; }
.filter.active { background: #4a90d9; color: #fff; }

.section { margin-bottom: 24px; }
.section h2 { font-size: 13px; font-weight: 600; color: #999; padding: 8px 0; margin-bottom: 10px; border-bottom: 1px solid #eee; display: flex; align-items: center; gap: 8px; text-transform: uppercase; letter-spacing: .5px; }
.section h2 .count { font-size: 11px; font-weight: 400; color: #aaa; background: #f0f0f0; padding: 2px 8px; border-radius: 10px; }
.section .empty { color: #bbb; font-size: 14px; padding: 16px 0; text-align: center; }

.card-group { margin-bottom: 10px; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); background: #fff; }
.card { display: block; padding: 14px 16px; text-decoration: none; color: #222; transition: background .12s; }
.card:hover { background: #fafbff; }
.card:not(:last-child) { border-bottom: 1px solid #f2f2f2; }

.card.refined { background: linear-gradient(135deg, #f8faff 0%, #f0f5ff 100%); border-left: 3px solid #4a90d9; padding-left: 13px; }
.card.refined:hover { background: linear-gradient(135deg, #f0f4ff 0%, #e8efff 100%); }

.card.original { background: #fafafa; padding: 7px 13px; border-left: 3px solid #e0e0e0; }
.card.original:hover { background: #f5f5f5; }
.card.original .card-title { font-size: 13px; font-weight: 400; color: #888; margin-bottom: 0; }
.card.original .card-preview { display: none; }
.card.original .card-meta { font-size: 10px; color: #ddd; }
.card.original .badge { display: none; }

.card-title { font-size: 15px; font-weight: 600; color: #1a1a1a; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
.card-title .badge { display: inline-block; font-size: 10px; font-weight: 600; padding: 1px 7px; border-radius: 8px; white-space: nowrap; flex-shrink: 0; }
.badge-refined { color: #4a90d9; background: #dce8fc; }
.badge-original { color: #999; background: #eee; }

.card-preview { font-size: 13px; color: #999; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 6px; }
.card-meta { font-size: 12px; color: #ccc; }

@media (max-width: 640px) {
  .tab { font-size: 13px; padding: 8px 2px; }
  .card.refined { padding: 12px 10px; border-left-width: 3px; padding-left: 10px; }
  .card.original { padding: 6px 10px; }
}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>浏览知识库</h1>
  <a href="/">← 返回首页</a>
</header>
"""

BROWSE_HTML_TAIL = """</div>
</body>
</html>"""

VIEW_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} - Hermes</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #222; line-height: 1.8; }
.container { max-width: 640px; margin: 0 auto; padding: 20px 16px; }
nav { padding: 12px 0 20px; }
nav a { font-size: 14px; color: #4a90d9; text-decoration: none; }
nav a:hover { text-decoration: underline; }
.content { background: #fff; border-radius: 8px; padding: 24px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.content h1 { font-size: 20px; margin-bottom: 16px; }
.content h2 { font-size: 17px; margin: 20px 0 10px; }
.content h3 { font-size: 15px; margin: 16px 0 8px; }
.content p { margin: 8px 0; }
.content ul, .content ol { margin: 8px 0; padding-left: 24px; }
.content li { margin: 4px 0; }
.content blockquote { border-left: 3px solid #4a90d9; padding: 4px 12px; margin: 12px 0; color: #555; background: #f8f9fa; }
.content code { background: #f0f0f0; padding: 1px 4px; border-radius: 3px; font-size: 90%%; }
.content pre { background: #f0f0f0; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 90%%; margin: 10px 0; }
.answer-section { margin-top: 24px; border-top: 2px solid #4a90d9; padding-top: 16px; }
.answer-section h3 { font-size: 15px; color: #4a90d9; margin-bottom: 10px; }
.answer-text { background: #f8faff; padding: 14px 16px; border-radius: 8px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; margin-bottom: 10px; }
.answer-btn { padding: 8px 20px; background: #4a90d9; color: #fff; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; }
.answer-btn:hover { background: #3a7bc8; }
.answer-editor { display: none; margin-top: 10px; }
.answer-editor.show { display: block; }
.answer-editor textarea { width: 100%; min-height: 120px; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; font-family: inherit; resize: vertical; outline: none; }
.answer-editor textarea:focus { border-color: #4a90d9; }
.answer-editor .actions { display: flex; gap: 8px; margin-top: 10px; }
.answer-editor .cancel-btn { padding: 8px 20px; background: #f0f0f0; color: #666; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; }
.answer-badge { display: inline-block; font-size: 12px; font-weight: 600; color: #22a45a; background: #e6f7ee; padding: 2px 8px; border-radius: 8px; }
@media (max-width: 640px) { .answer-editor textarea { min-height: 144px; } }
</style>
</head>
<body>
<div class="container">
<nav><a href="/browse">← 返回浏览</a></nav>
<div class="content">{{ content|safe }}</div>
<div class="answer-section" id="answer-section" {{ answer_display|safe }}>
  <h3>💬 我的思考</h3>
  <div class="answer-text" id="answer-text" {{ answer_text_display|safe }}>{{ answer_text|safe }}</div>
  <div id="answer-empty" {{ answer_empty_display|safe }}>
    <button class="answer-btn" onclick="showEditor()">写回答</button>
  </div>
  <div id="answer-has" {{ answer_has_display|safe }}>
    <button class="answer-btn" onclick="showEditor()">编辑回答</button>
  </div>
  <div class="answer-editor" id="answer-editor">
    <textarea id="answer-input">{{ answer_edit_text|safe }}</textarea>
    <div class="actions">
      <button class="answer-btn" onclick="saveAnswer()">保存</button>
      <button class="cancel-btn" onclick="hideEditor()">取消</button>
    </div>
  </div>
</div>
</div>
<script>
var answerFilePath = "{{ answer_filepath|safe }}";
function htmlDecode(s) {
  var ta = document.createElement('textarea');
  ta.innerHTML = s;
  return ta.value;
}
function showEditor() {
  document.getElementById('answer-editor').classList.add('show');
}
function hideEditor() {
  document.getElementById('answer-editor').classList.remove('show');
}
function saveAnswer() {
  var content = document.getElementById('answer-input').value;
  fetch('/answer/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: answerFilePath, content: content})
  }).then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.ok) { window.location.reload(); }
    else { alert('保存失败'); }
  })
  .catch(function() { alert('保存失败'); });
}
</script>
</html>"""


@app.route("/")
def index():
    return INDEX_HTML


@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(silent=True)
    if not data or "question" not in data:
        return jsonify({"answer": "请提供问题。", "sources": []}), 400
    question = data["question"].strip()
    if not question:
        return jsonify({"answer": "问题不能为空。", "sources": []}), 400
    result = qa_engine.ask(question)
    return jsonify(result)


@app.route("/ask/stream", methods=["POST"])
def ask_stream():
    data = request.get_json(silent=True)
    if not data or "question" not in data:
        return jsonify({"answer": "请提供问题。", "sources": []}), 400
    question = data["question"].strip()
    if not question:
        return jsonify({"answer": "问题不能为空。", "sources": []}), 400

    def generate():
        for event in qa_engine.ask_stream(question):
            yield f"data: {event}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.route("/index/status")
def index_status():
    cache_path = semantic_index.CACHE_PATH
    if not os.path.exists(cache_path):
        return jsonify({"age": "never", "files": 0})
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        return jsonify({"age": "never", "files": 0})
    files = cache.get("files", {})
    updated_at = cache.get("updated_at", "")
    if updated_at:
        from datetime import datetime, timezone
        dt = datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        diff = int((datetime.now(timezone.utc) - dt).total_seconds())
        if diff < 60:
            age = "刚刚"
        elif diff < 3600:
            age = f"{diff // 60} 分钟前"
        elif diff < 86400:
            age = f"{diff // 3600} 小时前"
        else:
            age = f"{diff // 86400} 天前"
    else:
        age = "未知"
    return jsonify({"age": age, "files": len(files)})


@app.route("/reindex", methods=["POST"])
def trigger_reindex():
    try:
        result = _do_reindex()
        return jsonify({"ok": True, "updated": result.get("updated", 0), "total": result.get("total", 0)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/pipeline/status")
def pipeline_status():
    with _pipeline_lock:
        return jsonify({
            "running": _pipeline_state["running"],
            "last_run": _pipeline_state["last_run"],
            "last_result": _pipeline_state["last_result"],
        })


@app.route("/pipeline/run", methods=["POST"])
def trigger_pipeline():
    try:
        result = _run_pipeline()
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _parse_filename(fn):
    name = fn[:-3] if fn.endswith(".md") else fn
    if name.endswith("_refined"):
        return name[:-8], True
    return name, False


def _extract_meta(fp):
    title = None
    preview_lines = []
    try:
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if title is None and stripped.startswith("# "):
                    title = stripped[2:].strip()
                elif title is not None and stripped and not stripped.startswith("#"):
                    preview_lines.append(stripped)
                    if len(preview_lines) >= 2:
                        break
    except Exception:
        pass
    return title, "\n".join(preview_lines)


def _time_ago(timestamp):
    diff = time.time() - timestamp
    if diff < 60:
        return "刚刚"
    elif diff < 3600:
        return "%d分钟前" % int(diff // 60)
    elif diff < 86400:
        return "%d小时前" % int(diff // 3600)
    elif diff < 604800:
        return "%d天前" % int(diff // 86400)
    elif diff < 2592000:
        return "%d周前" % int(diff // 604800)
    else:
        return time.strftime("%m-%d", time.localtime(timestamp))


def _html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _check_answered(fp):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
        idx = content.find("## 我的思考")
        if idx == -1:
            return False
        after = content[idx + len("## 我的思考"):]
        next_heading = after.find("\n## ")
        section = after[:next_heading] if next_heading != -1 else after
        return len(section.strip()) > 0
    except Exception:
        return False


def _extract_answer(fp):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
        idx = content.find("## 我的思考")
        if idx == -1:
            return ""
        after = content[idx + len("## 我的思考"):]
        next_heading = after.find("\n## ")
        section = after[:next_heading] if next_heading != -1 else after
        return section.strip()
    except Exception:
        return ""


@app.route("/browse")
def browse():
    sections = []
    for label, dirpath in BROWSE_ROOTS:
        entries = []
        if os.path.isdir(dirpath):
            for fn in os.listdir(dirpath):
                fp = os.path.join(dirpath, fn)
                if not os.path.isfile(fp) or not fn.endswith(".md"):
                    continue
                base, is_refined = _parse_filename(fn)
                title, preview = _extract_meta(fp)
                mtime = os.path.getmtime(fp)
                entries.append({
                    "fn": fn,
                    "base": base,
                    "is_refined": is_refined,
                    "title": title or base,
                    "preview": preview,
                    "mtime": mtime,
                    "rel": "%s/%s" % (label, fn)
                })

        groups = {}
        for e in entries:
            key = e["base"]
            if key not in groups:
                groups[key] = []
            groups[key].append(e)

        ordered_groups = []
        for base, items in groups.items():
            refined = [e for e in items if e["is_refined"]]
            originals = [e for e in items if not e["is_refined"]]
            ordered_groups.append(refined + originals)

        ordered_groups.sort(key=lambda g: max(e["mtime"] for e in g), reverse=True)
        sections.append((label, ordered_groups))

    TAB_LABELS = ["硬知识", "软智慧", "问题拷问"]
    LABEL_TO_TAB = {
        "core/insight": "软智慧",
        "core/note": "软智慧",
        "core/question": "问题拷问",
        "manual/technical": "硬知识",
    }

    tab_sections = {t: [] for t in TAB_LABELS}
    for label, groups in sections:
        tab = LABEL_TO_TAB.get(label, label)
        tab_sections[tab].append((label, groups))

    html = BROWSE_HTML_HEAD

    html += '<div class="tab-bar">'
    for i, tab in enumerate(TAB_LABELS):
        active = ' active' if i == 0 else ''
        html += '<button class="tab%s" data-tab="%s">%s</button>' % (active, tab, tab)
    html += '</div>'

    for tab_idx, tab_name in enumerate(TAB_LABELS):
        display = '' if tab_idx == 0 else ' style="display:none"'
        html += '<div class="tab-area" id="tab-area-%s"%s>' % (tab_name, display)

        html += '<div class="filter-row"><button class="filter active" data-filter="refined">精炼</button><button class="filter" data-filter="original">原始</button><button class="filter" data-filter="all">全部</button></div>'

        for label, groups in tab_sections.get(tab_name, []):
            total = sum(len(g) for g in groups)
            short_label = label.split("/")[-1]
            html += '<div class="section"><h2>%s<span class="count">%d篇</span></h2>' % (short_label, total)
            if not groups:
                html += '<div class="empty">（无文件）</div>'
            else:
                for group in groups:
                    group_html = ''
                    for e in group:
                        extra_class = " refined" if e["is_refined"] else " original"
                        data_type = "refined" if e["is_refined"] else "original"

                        badge_html = ""
                        preview_html = ""
                        title_display = e["title"]

                        if e["is_refined"]:
                            badge_html = '<span class="badge badge-refined">精炼</span>'
                            title_display = "✨ " + title_display
                            if e["preview"]:
                                preview_html = '<div class="card-preview">%s</div>' % _html_escape(e["preview"])
                        else:
                            badge_html = '<span class="badge badge-original">原始</span>'

                        if label == "core/question":
                            fp = os.path.join(BASE_DIR, e["rel"])
                            if _check_answered(fp):
                                badge_html += ' <span class="answer-badge">✓ 已回答</span>'

                        meta = '%s · %s' % (short_label, _time_ago(e["mtime"]))

                        group_html += '<a href="/view/%s" class="card%s" data-type="%s"><div class="card-title">%s%s</div>%s<div class="card-meta">%s</div></a>' % (
                            e["rel"], extra_class, data_type,
                            _html_escape(title_display), badge_html,
                            preview_html,
                            meta
                        )
                    html += '<div class="card-group">%s</div>' % group_html
            html += '</div>'
        html += '</div>'

    html += '<script>'
    html += 'document.querySelectorAll(".tab").forEach(function(t){t.addEventListener("click",function(){var n=this.dataset.tab;document.querySelectorAll(".tab").forEach(function(x){x.classList.remove("active")});this.classList.add("active");document.querySelectorAll(".tab-area").forEach(function(a){a.style.display="none"});document.getElementById("tab-area-"+n).style.display=""})});'
    html += 'document.querySelectorAll(".filter").forEach(function(f){f.addEventListener("click",function(){var fl=this.dataset.filter;var ta=this.closest(".tab-area");ta.querySelectorAll(".filter").forEach(function(x){x.classList.remove("active")});this.classList.add("active");ta.querySelectorAll(".card-group").forEach(function(g){var cards=g.querySelectorAll(".card");var vis=false;cards.forEach(function(c){if(fl==="all"||c.dataset.type===fl){c.style.display="";vis=true}else{c.style.display="none"}});g.style.display=vis?"":"none"})})});'
    html += 'document.querySelectorAll(".tab-area").forEach(function(ta){var af=ta.querySelector(".filter.active");if(af)af.click()})'
    html += '</script>'

    html += BROWSE_HTML_TAIL
    return html


@app.route("/answer/save", methods=["POST"])
def answer_save():
    data = request.get_json(silent=True)
    if not data or "path" not in data or "content" not in data:
        return jsonify({"ok": False, "error": "缺少参数"}), 400

    rel_path = data["path"]
    answer_content = data["content"]

    full = os.path.normpath(os.path.join(BASE_DIR, rel_path))
    if not full.startswith(os.path.normpath(BASE_DIR) + os.sep):
        return jsonify({"ok": False, "error": "禁止访问"}), 403
    if not os.path.isfile(full):
        return jsonify({"ok": False, "error": "文件不存在"}), 404

    with open(full, "r", encoding="utf-8") as f:
        raw = f.read()

    marker = "## 我的思考"
    idx = raw.find(marker)
    if idx == -1:
        raw = raw.rstrip() + "\n\n" + marker + "\n\n" + answer_content + "\n"
    else:
        after_marker = raw[idx + len(marker):]
        next_heading = after_marker.find("\n## ")
        if next_heading == -1:
            raw = raw[:idx + len(marker)] + "\n\n" + answer_content + "\n"
        else:
            raw = raw[:idx + len(marker)] + "\n\n" + answer_content + "\n" + after_marker[next_heading:]

    with open(full, "w", encoding="utf-8") as f:
        f.write(raw)

    title, _ = _extract_meta(full)
    title = title or os.path.basename(full).replace(".md", "")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    inbox_dir = os.path.join(BASE_DIR, "inbox")
    os.makedirs(inbox_dir, exist_ok=True)
    inbox_fp = os.path.join(inbox_dir, "answer_%s.md" % ts)

    inbox_content = "# [回答] %s\n" % title
    inbox_content += "> 源问题: [%s](%s)\n" % (title, os.path.basename(full))
    inbox_content += "> 回答时间: %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M")
    inbox_content += "\n"
    inbox_content += answer_content
    inbox_content += "\n"

    with open(inbox_fp, "w", encoding="utf-8") as f:
        f.write(inbox_content)

    return jsonify({"ok": True, "answered": True})


@app.route("/view/<path:filepath>")
def view(filepath):
    full = os.path.normpath(os.path.join(BASE_DIR, filepath))
    if not full.startswith(os.path.normpath(BASE_DIR) + os.sep) and full != os.path.normpath(BASE_DIR):
        return "禁止访问", 403
    if not os.path.isfile(full):
        return "文件不存在", 404
    with open(full, "r", encoding="utf-8") as f:
        raw = f.read()
    title = filepath.split("/")[-1]
    content = _render_markdown(raw)

    is_question = "core/question/" in filepath
    if is_question:
        has_answer = _check_answered(full)
        answer_text = _html_escape(_extract_answer(full)) if has_answer else ""
        answer_display = 'style="display:block"'
        answer_text_display = '' if has_answer else 'style="display:none"'
        answer_empty_display = 'style="display:none"' if has_answer else ''
        answer_has_display = '' if has_answer else 'style="display:none"'
        answer_edit_text = _html_escape(_extract_answer(full))
        answer_filepath = filepath
    else:
        answer_display = 'style="display:none"'
        answer_text_display = 'style="display:none"'
        answer_empty_display = 'style="display:none"'
        answer_has_display = 'style="display:none"'
        answer_edit_text = ""
        answer_text = ""
        answer_filepath = ""

    html = VIEW_HTML
    html = html.replace("{{ title }}", title)
    html = html.replace("{{ content|safe }}", content)
    html = html.replace("{{ answer_display|safe }}", answer_display)
    html = html.replace("{{ answer_text|safe }}", answer_text)
    html = html.replace("{{ answer_text_display|safe }}", answer_text_display)
    html = html.replace("{{ answer_empty_display|safe }}", answer_empty_display)
    html = html.replace("{{ answer_has_display|safe }}", answer_has_display)
    html = html.replace("{{ answer_edit_text|safe }}", answer_edit_text)
    html = html.replace("{{ answer_filepath|safe }}", answer_filepath)
    return html


def _render_markdown(text):
    import re
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = text.split("\n")
    out = []
    in_list = False
    in_ol = False
    in_blockquote = False
    in_code_block = False
    code_lang = ""

    for line in lines:
        if in_code_block:
            if line.strip().startswith("```"):
                out.append("</code></pre>")
                in_code_block = False
            else:
                out.append(line + "\n")
            continue

        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = True
            code_lang = stripped[3:].strip()
            out.append('<pre><code class="language-{}">'.format(code_lang))
            continue

        if stripped.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if in_blockquote:
                out.append("</blockquote>")
                in_blockquote = False
            out.append("<h1>" + stripped[2:] + "</h1>")
            continue
        if stripped.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if in_blockquote:
                out.append("</blockquote>")
                in_blockquote = False
            out.append("<h2>" + stripped[3:] + "</h2>")
            continue
        if stripped.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if in_blockquote:
                out.append("</blockquote>")
                in_blockquote = False
            out.append("<h3>" + stripped[4:] + "</h3>")
            continue

        if stripped.startswith("> "):
            if not in_blockquote:
                if in_list:
                    out.append("</ul>")
                    in_list = False
                if in_ol:
                    out.append("</ol>")
                    in_ol = False
                out.append("<blockquote>")
                in_blockquote = True
            out.append(stripped[2:] + "<br>")
            continue
        else:
            if in_blockquote:
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
        else:
            if in_ol:
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
        else:
            if in_list:
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
    return rendered


if __name__ == "__main__":
    import semantic_index
    print("预加载语义模型...")
    semantic_index._get_model()
    print("模型就绪，启动服务")

    t = threading.Thread(target=_watchdog_reindex, daemon=True)
    t.start()
    print("索引看门狗已启动 (每 300 秒检查)")

    t2 = threading.Thread(target=_watchdog_pipeline, daemon=True)
    t2.start()
    print("管道看门狗已启动 (每 60 秒检查收件箱)")

    app.run(host="0.0.0.0", port=5000, debug=False)

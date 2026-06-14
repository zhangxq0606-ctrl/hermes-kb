import os
import sys
import threading
import time
import hashlib
import json
import random
import subprocess
from datetime import datetime

from flask import Flask, request, jsonify, Response, stream_with_context, redirect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qa_engine
import semantic_index

app = Flask(__name__)

BASE_DIR = qa_engine.BASE_DIR
BROWSE_ROOTS = [
    ("core/topic", os.path.join(BASE_DIR, "core", "topic")),
    ("core/insight", os.path.join(BASE_DIR, "core", "insight")),
    ("core/note", os.path.join(BASE_DIR, "core", "note")),
    ("core/question", os.path.join(BASE_DIR, "core", "question")),
    ("manual/technical", os.path.join(BASE_DIR, "manual", "technical")),
]

CARD_COLORS = [
    "#2563eb", "#d97706", "#7c3aed", "#059669", "#dc2626",
    "#0891b2", "#c026d3", "#65a30d", "#e11d48", "#4f46e5",
]

_reindex_lock = threading.Lock()
_reindex_interval = 300
_reindex_hash_file = os.path.join(semantic_index.CACHE_PATH + ".state")

_pipeline_state = {"running": False, "last_run": None, "last_result": None}
_pipeline_lock = threading.Lock()

_file_index_cache = {"data": None, "timestamp": 0}
_FILE_INDEX_CACHE_TTL = 300


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
            _pipeline_state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
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
<title>Xq.KB</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fafbfc; color: #374151; line-height: 1.6; }
.container { max-width: 640px; margin: 0 auto; padding: 20px 16px; }
header { text-align: center; padding: 40px 0 28px; }
header h1 { font-size: 28px; font-weight: 700; color: #1a1a2e; }
header p { font-size: 14px; color: #9ca3af; margin-top: 6px; }

.browse-entry { margin-bottom: 24px; }
.browse-entry a { display: flex; align-items: center; gap: 12px; background: #fff; border-radius: 12px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.05); text-decoration: none; color: #374151; transition: background .15s, box-shadow .15s; border-left: 4px solid #2563eb; }
.browse-entry a:hover { box-shadow: 0 2px 6px rgba(0,0,0,.08); background: #f0f4ff; text-decoration: none; }
.browse-entry .be-icon { font-size: 22px; flex-shrink: 0; }
.browse-entry .be-label { font-size: 16px; font-weight: 600; color: #1a1a2e; flex: 1; }
.browse-entry .be-arrow { font-size: 18px; color: #2563eb; }

.search-box { display: flex; gap: 8px; margin-bottom: 16px; }
.search-box input { flex: 1; padding: 12px 16px; border: 1px solid #e5e7eb; border-radius: 8px; font-size: 16px; outline: none; transition: border-color .2s; background: #fff; }
.search-box input:focus { border-color: #2563eb; }
.search-box button { padding: 12px 20px; background: #2563eb; color: #fff; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; transition: background .2s; }
.search-box button:hover { background: #1d4ed8; }
.search-box button:disabled { background: #94a3b8; cursor: not-allowed; }
.index-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; font-size: 13px; color: #9ca3af; }
.index-bar button { background: none; border: 1px solid #e5e7eb; padding: 4px 10px; border-radius: 6px; color: #6b7280; cursor: pointer; font-size: 12px; }
.index-bar button:hover { border-color: #2563eb; color: #2563eb; }
.index-bar button:disabled { opacity: .5; cursor: not-allowed; }
.answer-area { display: none; background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.05); }
.answer-area.show { display: block; }
.answer-area .answer-text { font-size: 15px; word-break: break-word; line-height: 1.7; }
.answer-area .answer-text p { margin: 0 0 8px 0; }
.answer-area .answer-text p:last-child { margin-bottom: 0; }
.answer-area .sources { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f3f4f6; }
.answer-area .sources h3 { font-size: 13px; color: #9ca3af; margin-bottom: 6px; }
.answer-area .sources a { display: block; font-size: 14px; color: #2563eb; text-decoration: none; padding: 3px 0; }
.answer-area .sources a:hover { text-decoration: underline; }
.loading { display: none; text-align: center; padding: 40px 0; color: #9ca3af; }
.loading.show { display: block; }
</style>
</head>
<body>
<div class="container">
<header>
  <h1>Xq.KB</h1>
  <p>知识捕获 &middot; AI 提纯 &middot; 语义搜索</p>
</header>
<div class="browse-entry">
  <a href="/browse">
    <span class="be-icon">&#128218;</span>
    <span class="be-label">浏览知识库</span>
    <span class="be-arrow">&rarr;</span>
  </a>
</div>
<div class="browse-entry">
  <a href="/chat">
    <span class="be-icon">&#128172;</span>
    <span class="be-label">对话</span>
    <span class="be-arrow">&rarr;</span>
  </a>
</div>
<div class="search-box">
  <input id="question" type="text" placeholder="输入你的问题..." autofocus>
  <button id="ask-btn">提问</button>
</div>
<div class="index-bar">
  <div>
      <div id="pipeline-status" style="font-size:12px;color:#9ca3af;">管道: --</div>
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
        html += '<a href="/view/' + encodeURIComponent(s.path) + '">' + s.title + '</a>';
        html += ' <span style="font-size:11px;color:#9ca3af">[' + s.section + ']</span>';
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

CHAT_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>对话 - Xq.KB</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fafbfc; color: #374151; line-height: 1.6; }
.container { max-width: 640px; margin: 0 auto; padding: 0 16px; }
.top-bar { display: flex; justify-content: space-between; align-items: center; padding: 16px 0; border-bottom: 1px solid #e5e7eb; }
.top-bar h1 { font-size: 18px; font-weight: 700; color: #1a1a2e; }
.top-bar button { background: none; border: 1px solid #e5e7eb; padding: 5px 14px; border-radius: 6px; font-size: 13px; color: #6b7280; cursor: pointer; }
.top-bar button:hover { border-color: #2563eb; color: #2563eb; }

#chat-messages { padding: 16px 0; }
.msg { display: flex; margin-bottom: 16px; }
.msg.user { justify-content: flex-end; }
.msg.bot { justify-content: flex-start; }
.msg .bubble { max-width: 85%; padding: 10px 14px; border-radius: 10px; font-size: 14px; line-height: 1.65; word-break: break-word; }
.msg.user .bubble { background: #2563eb; color: #fff; border-bottom-right-radius: 4px; }
.msg.bot .bubble { background: #fff; color: #374151; box-shadow: 0 1px 3px rgba(0,0,0,.08); border-bottom-left-radius: 4px; }
.msg.bot .bubble p { margin: 0 0 6px 0; }
.msg.bot .bubble p:last-child { margin-bottom: 0; }
.msg.bot .bubble strong { color: #1a1a2e; }

.msg-sources { margin-top: 8px; padding-top: 8px; border-top: 1px solid #f3f4f6; }
.msg-sources .src-label { font-size: 11px; color: #9ca3af; margin-bottom: 4px; }
.msg-sources a { display: block; font-size: 13px; color: #2563eb; text-decoration: none; padding: 2px 0; }
.msg-sources a:hover { text-decoration: underline; }
.msg-sources .src-tag { font-size: 10px; color: #9ca3af; }

.msg .thinking { color: #9ca3af; font-size: 14px; padding: 10px 14px; }

.input-bar { display: flex; gap: 8px; padding: 12px 0; border-bottom: 1px solid #e5e7eb; margin-bottom: 16px; }
.input-bar textarea { flex: 1; padding: 10px 12px; border: 1px solid #e5e7eb; border-radius: 8px; font-size: 14px; outline: none; resize: none; font-family: inherit; line-height: 1.5; }
.input-bar textarea:focus { border-color: #2563eb; }
.input-bar button { padding: 10px 18px; background: #2563eb; color: #fff; border: none; border-radius: 8px; font-size: 14px; cursor: pointer; white-space: nowrap; align-self: flex-end; }
.input-bar button:hover { background: #1d4ed8; }
.input-bar button:disabled { background: #94a3b8; cursor: not-allowed; }

.back-link { text-align: center; padding: 0 0 12px; flex-shrink: 0; }
.back-link a { font-size: 13px; color: #9ca3af; text-decoration: none; }
.back-link a:hover { color: #2563eb; }
</style>
</head>
<body>
<div class="container">
<div class="top-bar">
  <h1>Xq.KB 对话</h1>
  <button id="new-chat-btn">新对话</button>
</div>
<div class="input-bar">
  <textarea id="chat-input" placeholder="输入你的问题..." rows="2"></textarea>
  <button id="send-btn">发送</button>
</div>
<div id="chat-messages"></div>
<div class="back-link"><a href="/">← 返回首页</a></div>
</div>
<script>
var sessionId = null;
var messagesEl = document.getElementById('chat-messages');
var inputEl = document.getElementById('chat-input');
var sendBtn = document.getElementById('send-btn');
var newChatBtn = document.getElementById('new-chat-btn');

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function addUserBubble(text) {
  var div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = '<div class="bubble">' + escapeHtml(text) + '</div>';
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addThinkingBubble() {
  var div = document.createElement('div');
  div.className = 'msg bot';
  div.innerHTML = '<div class="thinking">正在思考...</div>';
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function addBotBubble(answer, sources) {
  var html = escapeHtml(answer)
    .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
    .replace(/\\n\\n/g, '</p><p>')
    .replace(/\\n/g, '<br>');
  var body = '<p>' + html + '</p>';

  if (sources && sources.length > 0) {
    body += '<div class="msg-sources"><div class="src-label">引用来源</div>';
    sources.forEach(function(s) {
      body += '<a href="/view/' + encodeURIComponent(s.path) + '">' + escapeHtml(s.title) + '</a>';
      body += ' <span class="src-tag">[' + escapeHtml(s.section) + ']</span>';
    });
    body += '</div>';
  }

  var div = document.createElement('div');
  div.className = 'msg bot';
  div.innerHTML = '<div class="bubble">' + body + '</div>';
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function doSend() {
  var q = inputEl.value.trim();
  if (!q) return;
  inputEl.value = '';
  sendBtn.disabled = true;

  addUserBubble(q);
  var thinkEl = addThinkingBubble();

  fetch('/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question: q, session_id: sessionId})
  }).then(function(r) { return r.json(); })
  .then(function(d) {
    thinkEl.remove();
    sessionId = d.session_id;
    addBotBubble(d.answer, d.sources);
    sendBtn.disabled = false;
  }).catch(function(err) {
    thinkEl.remove();
    addBotBubble('请求失败：' + err.message, []);
    sendBtn.disabled = false;
  });
}

sendBtn.addEventListener('click', doSend);
inputEl.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    doSend();
  }
});

newChatBtn.addEventListener('click', function() {
  if (!sessionId) { messagesEl.innerHTML = ''; return; }
  fetch('/chat/clear', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: sessionId})
  }).then(function(r) { return r.json(); })
  .then(function() {
    sessionId = null;
    messagesEl.innerHTML = '';
  });
});
</script>
</body>
</html>"""

BROWSE_HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>浏览 - Xq.KB</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fafbfc; color: #374151; line-height: 1.6; }
.container { max-width: 640px; margin: 0 auto; padding: 20px 16px; }
header { text-align: center; padding: 32px 0 24px; }
header h1 { font-size: 22px; font-weight: 700; }
header a { font-size: 14px; color: #2563eb; text-decoration: none; }
header a:hover { text-decoration: underline; }

.tab-bar { display: flex; gap: 4px; margin-bottom: 16px; border-bottom: 2px solid #f3f4f6; }
.tab { flex: 1; padding: 10px 4px; background: none; border: none; border-bottom: 2px solid transparent; margin-bottom: -2px; font-size: 14px; color: #9ca3af; cursor: pointer; transition: color .2s, border-color .2s; text-decoration: none; text-align: center; display: inline-block; }
.tab:hover { color: #6b7280; }
.tab.active { color: #2563eb; border-bottom-color: #2563eb; font-weight: 600; }
.tab.active[data-tab="编译论点"] { color: #d97706; border-bottom-color: #d97706; }
.tab.active[data-tab="硬知识"] { color: #2563eb; border-bottom-color: #2563eb; }
.tab.active[data-tab="软智慧"] { color: #d97706; border-bottom-color: #d97706; }
.tab.active[data-tab="问题拷问"] { color: #7c3aed; border-bottom-color: #7c3aed; }

.tab-area {}

.section { margin-bottom: 24px; }
.section h2 { font-size: 13px; font-weight: 600; color: #9ca3af; padding: 8px 0; margin-bottom: 10px; border-bottom: 1px solid #f3f4f6; display: flex; align-items: center; gap: 8px; text-transform: uppercase; letter-spacing: .5px; }
.section h2 .count { font-size: 11px; font-weight: 400; color: #9ca3af; background: #f3f4f6; padding: 2px 8px; border-radius: 10px; }
.section .empty { color: #d1d5db; font-size: 14px; padding: 16px 0; text-align: center; }

.card-group { margin-bottom: 10px; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); background: #fff; }
.card { display: block; padding: 14px 16px; text-decoration: none; color: #374151; transition: background .12s; }
.card:hover { background: #f8fafc; }
.card:not(:last-child) { border-bottom: 1px solid #f3f4f6; }

.card.refined { background: #fff; border-left: 3px solid; padding-left: 13px; }
.card.refined:hover { background: #f0f4ff; }

.card.original { background: #fafafa; padding: 7px 13px; border-left: 3px solid #e5e7eb; }
.card.original:hover { background: #f3f4f6; }
.card.original .card-title { font-size: 13px; font-weight: 400; color: #6b7280; margin-bottom: 0; }
.card.original .card-preview { display: none; }
.card.original .card-meta { font-size: 10px; color: #d1d5db; }
.card.original .badge { display: none; }
.card-group .card.original { border-left: none; padding-left: 16px; }

.card-title { font-size: 15px; font-weight: 600; color: #1a1a2e; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
.card-title .badge { display: inline-block; font-size: 10px; font-weight: 600; padding: 1px 7px; border-radius: 8px; white-space: nowrap; flex-shrink: 0; }
.badge-refined { }
.badge-original { color: #9ca3af; background: #f3f4f6; }

.card-preview { font-size: 13px; color: #9ca3af; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 6px; }
.card-meta { font-size: 12px; color: #d1d5db; }

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
<title>{{ title }} - Xq.KB</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fafbfc; color: #374151; line-height: 1.8; }
.container { max-width: 640px; margin: 0 auto; padding: 20px 16px; }
nav { padding: 12px 0 20px; }
nav a { font-size: 14px; color: #2563eb; text-decoration: none; }
nav a:hover { text-decoration: underline; }
.content { max-width: 680px; background: #fff; border-radius: 12px; padding: 24px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.05); }
.content h1 { font-size: 20px; margin-bottom: 16px; }
.content h2 { font-size: 17px; margin: 20px 0 10px; }
.content h3 { font-size: 15px; margin: 16px 0 8px; }
.content p { margin: 8px 0; }
.content ul, .content ol { margin: 8px 0; padding-left: 24px; }
.content li { margin: 4px 0; }
.content blockquote { border-left: 3px solid #7c3aed; padding: 4px 12px; margin: 12px 0; color: #6b7280; background: #faf5ff; border-radius: 0 6px 6px 0; }
.content code { background: #f1f5f9; color: #334155; padding: 1px 4px; border-radius: 3px; font-size: 90%%; }
.content pre { background: #1e293b; color: #e2e8f0; padding: 14px 16px; border-radius: 8px; overflow-x: auto; font-size: 88%%; margin: 10px 0; line-height: 1.5; }
.content pre code { background: none; padding: 0; color: inherit; font-size: inherit; }
.answer-section { margin-top: 24px; border-top: 2px solid #2563eb; padding-top: 16px; }
.answer-section h3 { font-size: 15px; color: #2563eb; margin-bottom: 10px; }
.answer-text { background: #f0f4ff; padding: 14px 16px; border-radius: 8px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; margin-bottom: 10px; }
.answer-btn { padding: 8px 20px; background: #2563eb; color: #fff; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; }
.answer-btn:hover { background: #1d4ed8; }
.answer-editor { display: none; margin-top: 10px; }
.answer-editor.show { display: block; }
.answer-editor textarea { width: 100%%; min-height: 120px; padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; font-size: 14px; font-family: inherit; resize: vertical; outline: none; }
.answer-editor textarea:focus { border-color: #2563eb; }
.answer-editor .actions { display: flex; gap: 8px; margin-top: 10px; }
.answer-editor .cancel-btn { padding: 8px 20px; background: #f3f4f6; color: #6b7280; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; }
.discard-btn { padding: 6px 16px; background: #dc2626; color: #fff; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; margin-top: 12px; }
.discard-btn:hover { background: #b91c1c; }
.answer-badge { display: inline-block; font-size: 12px; font-weight: 600; color: #16a34a; background: #f0fdf4; padding: 2px 8px; border-radius: 8px; }
.wikilink { color: #7c3aed; border-bottom: 1px dashed #c4b5fd; text-decoration: none; } .wikilink:hover { color: #6d28d9; border-bottom-style: solid; }
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
  <div>
    <button class="discard-btn" onclick="discardQuestion()">丢弃问题</button>
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
function discardQuestion() {
  if (!confirm('确认丢弃该问题？此操作不可撤销。')) return;
  fetch('/question/discard', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: answerFilePath})
  }).then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.ok) { window.location.href = '/browse'; }
    else { alert('丢弃失败'); }
  })
  .catch(function() { alert('丢弃失败'); });
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


@app.route("/chat", methods=["GET", "POST"])
def chat():
    if request.method == "GET":
        return CHAT_HTML
    data = request.get_json(silent=True)
    if not data or "question" not in data:
        return jsonify({"answer": "请提供问题。", "sources": [], "session_id": None}), 400
    question = data["question"].strip()
    if not question:
        return jsonify({"answer": "问题不能为空。", "sources": [], "session_id": None}), 400
    session_id = data.get("session_id", None)
    result = qa_engine.chat(question, session_id)
    return jsonify(result)


@app.route("/chat/clear", methods=["POST"])
def chat_clear():
    data = request.get_json(silent=True)
    if not data or "session_id" not in data:
        return jsonify({"ok": False, "error": "缺少 session_id"}), 400
    qa_engine.SessionManager.clear_session(data["session_id"])
    return jsonify({"ok": True})


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


def _is_derived_file(fn):
    """系统派生文件（tech_/insight_ 分裂 + _source_ URL冷备），不进入浏览页。"""
    if not fn.endswith(".md"):
        return False
    name = fn[:-3]
    if name.startswith("tech_") or name.startswith("insight_"):
        return True
    if "_source_" in name:
        return True
    return False


def _canonical_key(fn):
    """归一化文件名：去掉 _refined、tech_/insight_ 前缀、_source_<hash> 后缀。"""
    import re
    name = fn[:-3] if fn.endswith(".md") else fn
    if name.endswith("_refined"):
        name = name[:-8]
    if name.startswith("tech_"):
        name = name[5:]
    if name.startswith("insight_"):
        name = name[8:]
    name = re.sub(r"_source_[a-f0-9]+$", "", name)
    return name


def _entry_role(fn):
    """判断文件在 canonical group 中的角色。"""
    name = fn[:-3] if fn.endswith(".md") else fn
    if name.endswith("_refined"):
        return "refined"
    if name.startswith("tech_"):
        return "tech_split"
    if name.startswith("insight_"):
        return "insight_split"
    if "_source_" in name:
        return "source"
    return "original"


ROLE_LABEL = {
    "refined": "精炼",
    "original": "原文",
    "tech_split": "技术拆分",
    "insight_split": "认知拆分",
    "source": "冷备",
}
ROLE_ORDER = ["refined", "original", "tech_split", "insight_split", "source"]


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
    TAB_LABELS = ["编译论点", "硬知识", "软智慧", "问题拷问"]
    LABEL_TO_TAB = {
        "core/topic": "编译论点",
        "core/insight": "软智慧",
        "core/note": "软智慧",
        "core/question": "问题拷问",
        "manual/technical": "硬知识",
    }
    SECTION_LABEL = {
        "core/topic": "主题页",
        "core/insight": "洞察",
        "core/note": "笔记",
        "core/question": "问题",
        "manual/technical": "技术手册",
    }

    tab_data = {t: {} for t in TAB_LABELS}

    for label, dirpath in BROWSE_ROOTS:
        tab = LABEL_TO_TAB.get(label, label)
        is_topic = (label == "core/topic")
        is_question = (label == "core/question")

        if is_topic:
            entries = []
            if os.path.isdir(dirpath):
                for fn in os.listdir(dirpath):
                    fp = os.path.join(dirpath, fn)
                    if not os.path.isfile(fp) or not fn.endswith(".md") or not fn.startswith("topic_"):
                        continue
                    title, preview = _extract_meta(fp)
                    mtime = os.path.getmtime(fp)
                    entries.append({"fn": fn, "title": title or fn[:-3], "preview": preview, "mtime": mtime, "rel": "%s/%s" % (label, fn)})
            entries.sort(key=lambda e: e["mtime"], reverse=True)
            tab_data[tab][label] = {"topics": entries}
        elif is_question:
            entries = []
            if os.path.isdir(dirpath):
                for fn in os.listdir(dirpath):
                    fp = os.path.join(dirpath, fn)
                    if not os.path.isfile(fp) or not fn.endswith(".md"):
                        continue
                    if _is_derived_file(fn):
                        continue
                    title, preview = _extract_meta(fp)
                    mtime = os.path.getmtime(fp)
                    entries.append({"fn": fn, "title": title or (fn[:-11] if fn.endswith("_refined.md") else fn[:-3]), "preview": preview, "mtime": mtime, "rel": "%s/%s" % (label, fn)})
            entries.sort(key=lambda e: e["mtime"], reverse=True)
            tab_data[tab][label] = {"questions": entries}
        else:
            # 按 canonical_key 分组，每组精炼在上原文在下
            entries = []
            if os.path.isdir(dirpath):
                for fn in os.listdir(dirpath):
                    fp = os.path.join(dirpath, fn)
                    if not os.path.isfile(fp) or not fn.endswith(".md"):
                        continue
                    if _is_derived_file(fn):
                        continue
                    ckey = _canonical_key(fn)
                    role = _entry_role(fn)
                    title, preview = _extract_meta(fp)
                    mtime = os.path.getmtime(fp)
                    entries.append({"fn": fn, "ckey": ckey, "role": role, "title": title or (fn[:-11] if fn.endswith("_refined.md") else fn[:-3]), "preview": preview, "mtime": mtime, "rel": "%s/%s" % (label, fn)})

            # 按 canonical key 分组
            groups = {}
            for e in entries:
                groups.setdefault(e["ckey"], []).append(e)

            # 每组精炼优先排序
            grouped = []
            for ckey, items in groups.items():
                refined_item = None
                original_item = None
                for e in items:
                    if e["role"] == "refined":
                        refined_item = e
                    elif e["role"] == "original":
                        original_item = e
                latest_mtime = max(e["mtime"] for e in items)
                grouped.append({"ckey": ckey, "refined": refined_item, "original": original_item, "mtime": latest_mtime})

            grouped.sort(key=lambda g: g["mtime"], reverse=True)
            tab_data[tab][label] = {"groups": grouped}

    html = BROWSE_HTML_HEAD
    selected_tab = request.args.get("tab", "编译论点")
    if selected_tab not in TAB_LABELS:
        selected_tab = TAB_LABELS[0]

    html += '<div class="tab-bar">'
    for tab in TAB_LABELS:
        active = ' active' if tab == selected_tab else ''
        html += '<a class="tab%s" data-tab="%s" href="/browse?tab=%s">%s</a>' % (active, tab, tab, tab)
    html += '</div>'

    html += '<div class="tab-area">'
    for label, ld in tab_data.get(selected_tab, {}).items():
        short_label = SECTION_LABEL.get(label, label.split("/")[-1])

        if "topics" in ld:
            topics = ld["topics"]
            html += '<div class="section"><h2>%s<span class="count">%d篇</span></h2>' % (short_label, len(topics))
            if not topics:
                html += '<div class="empty">（无文件）</div>'
            else:
                for e in topics:
                    preview_html = ''
                    if e["preview"]:
                        preview_html = '<div class="card-preview">%s</div>' % _html_escape(e["preview"])
                    card_html = '<a href="/view/%s" class="card refined" style="border-left-color:#d97706"><div class="card-title">📖 %s</div>%s<div class="card-meta">%s</div></a>' % (
                        e["rel"], _html_escape(e["title"]), preview_html, _time_ago(e["mtime"]))
                    html += '<div class="card-group">%s</div>' % card_html
        elif "questions" in ld:
            qs = ld["questions"]
            html += '<div class="section"><h2>%s<span class="count">%d篇</span></h2>' % (short_label, len(qs))
            if not qs:
                html += '<div class="empty">（无文件）</div>'
            else:
                for e in qs:
                    badge_html = '<span class="badge badge-original">原始</span>'
                    fp = os.path.join(BASE_DIR, e["rel"])
                    if _check_answered(fp):
                        badge_html += ' <span class="answer-badge">✓ 已回答</span>'
                    card_html = '<a href="/view/%s" class="card original" data-type="original"><div class="card-title">%s%s</div><div class="card-meta">%s</div></a>' % (
                        e["rel"], _html_escape(e["title"]), badge_html, _time_ago(e["mtime"]))
                    html += '<div class="card-group">%s</div>' % card_html
        else:
            groups = ld["groups"]
            total = len(groups)
            html += '<div class="section"><h2>%s<span class="count">%d篇</span></h2>' % (short_label, total)
            if not groups:
                html += '<div class="empty">（无文件）</div>'
            else:
                for g in groups:
                    color = random.choice(CARD_COLORS)
                    html += '<div class="card-group">'
                    if g["refined"]:
                        e = g["refined"]
                        preview_html = ''
                        if e["preview"]:
                            preview_html = '<div class="card-preview">%s</div>' % _html_escape(e["preview"])
                        html += '<a href="/view/%s" class="card refined" data-type="refined" style="border-left-color:%s"><div class="card-title">✨ %s <span class="badge badge-refined" style="color:%s;background:%s1a">精炼</span></div>%s<div class="card-meta">%s</div></a>' % (
                            e["rel"], color, _html_escape(e["title"]), color, color, preview_html, _time_ago(e["mtime"]))
                    if g["original"]:
                        e = g["original"]
                        html += '<a href="/view/%s" class="card original" data-type="original"><div class="card-title">%s</div><div class="card-meta">%s</div></a>' % (
                            e["rel"], _html_escape(e["title"]), _time_ago(e["mtime"]))
                    html += '</div>'
            html += '</div>'

    html += '</div>'

    html += BROWSE_HTML_TAIL
    resp = app.make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


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

    return jsonify({"ok": True, "answered": True})


@app.route("/question/discard", methods=["POST"])
def question_discard():
    data = request.get_json(silent=True)
    if not data or "path" not in data:
        return jsonify({"ok": False, "error": "缺少参数"}), 400

    rel_path = data["path"]
    full = os.path.normpath(os.path.join(BASE_DIR, rel_path))
    question_dir = os.path.normpath(os.path.join(BASE_DIR, "core", "question"))

    if not full.startswith(question_dir + os.sep):
        return jsonify({"ok": False, "error": "只能删除 core/question/ 下的文件"}), 403
    if not os.path.isfile(full):
        return jsonify({"ok": False, "error": "文件不存在"}), 404

    os.remove(full)

    filename = os.path.basename(rel_path)
    state_path = os.path.join(BASE_DIR, "logs", ".weekly_scan_state.json")
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            changed = False
            for zone in ("active", "backlog"):
                items = state.get(zone, [])
                state[zone] = [it for it in items if it.get("file") != filename]
                if len(state[zone]) != len(items):
                    changed = True
            qfiles = state.get("question_files", {})
            keys_to_del = [k for k in qfiles.keys() if k == filename]
            for k in keys_to_del:
                del qfiles[k]
                changed = True
            if changed:
                with open(state_path, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return jsonify({"ok": True})


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


def build_file_index():
    """构建文件名→相对路径索引，带 5 分钟内存缓存。"""
    now = time.time()
    if _file_index_cache["data"] is not None and (now - _file_index_cache["timestamp"]) < _FILE_INDEX_CACHE_TTL:
        return _file_index_cache["data"]

    index = {}
    skip_dirs = {"processing", "raw", "logs"}

    for label, dirpath in BROWSE_ROOTS:
        if not os.path.isdir(dirpath):
            continue
        for fn in os.listdir(dirpath):
            fp = os.path.join(dirpath, fn)
            # 跳过非内容子目录
            if os.path.isdir(fp):
                if fn in skip_dirs:
                    continue
                else:
                    continue  # 只索引一级目录文件，不递归
            if not fn.endswith(".md"):
                continue
            base, is_refined = _parse_filename(fn)
            rel = "%s/%s" % (label, fn)
            # _refined.md 优先于 .md（同名时保留精炼版路径）
            if base not in index or is_refined:
                index[base] = rel

    _file_index_cache["data"] = index
    _file_index_cache["timestamp"] = now
    return index


@app.route("/wikilink/<name>")
def wikilink(name):
    index = build_file_index()
    if name in index:
        return redirect("/view/" + index[name], code=302)
    return redirect("/browse?q=" + name, code=302)


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
    rendered = re.sub(r"\[\[([^\]]+)\]\]", r'<a href="/wikilink/\1" class="wikilink">\1</a>', rendered)
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

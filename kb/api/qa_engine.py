import os
import sys
import json
import time
import hashlib
import uuid
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import semantic_index

BASE_DIR = semantic_index.BASE_DIR
ENV_PATH = os.path.join(BASE_DIR, ".env")


def _load_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and value:
                    env[key] = value
    return env


def _get_deepseek_config():
    env = _load_env()
    api_key = env.get("DEEPSEEK_API_KEY", "")
    base_url = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = env.get("DEEPSEEK_MODEL", "deepseek-chat")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY 未在 .env 中配置")
    return api_key, base_url, model


SYSTEM_PROMPT = """你是 Xq.KB 知识库助手。基于检索到的文档回答用户问题。
规则：
- 如果文档内容足以回答问题，直接回答并在末尾标注引用的文档来源
- 如果部分相关但不完整，先回答已知部分，再告知缺失什么
- 如果文档与问题完全无关或为空，明确说"知识库中暂无相关内容"，不要编造
- 回答简洁直接，不铺垫背景，不重复问题
- 中文回答，专业术语保留原文"""


class SessionManager:
    _sessions = {}
    _MAX_MESSAGES = 20

    @classmethod
    def create_session(cls):
        session_id = uuid.uuid4().hex[:8]
        cls._sessions[session_id] = []
        return session_id

    @classmethod
    def get_history(cls, session_id):
        return cls._sessions.get(session_id, [])

    @classmethod
    def add_message(cls, session_id, role, content):
        if session_id not in cls._sessions:
            cls._sessions[session_id] = []
        cls._sessions[session_id].append({"role": role, "content": content})
        if len(cls._sessions[session_id]) > cls._MAX_MESSAGES:
            cls._sessions[session_id] = cls._sessions[session_id][2:]

    @classmethod
    def clear_session(cls, session_id):
        cls._sessions.pop(session_id, None)

_ANSWER_CACHE = {}
_CACHE_TTL = 300


def _cache_key(question):
    return hashlib.sha256(question.strip().encode("utf-8")).hexdigest()


def _extract_title(filepath):
    """读取文件第一行 # 标题，失败返回文件名"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped[2:].strip()
    except Exception:
        pass
    name = os.path.basename(filepath).replace(".md", "")
    if name.endswith("_refined"):
        name = name[:-8]
    return name


def _section_label(rel_path):
    """将相对路径映射为分类标签"""
    mapping = {
        "core/insight": "洞察",
        "core/note": "笔记",
        "core/question": "问题",
        "manual/technical": "技术手册",
    }
    normalized = rel_path.replace("\\", "/")
    for prefix, label in mapping.items():
        if normalized.startswith(prefix + "/") or normalized == prefix:
            return label
    parts = normalized.split("/")
    return parts[0] if parts else rel_path


def _get_cached(question):
    key = _cache_key(question)
    if key in _ANSWER_CACHE:
        answer, sources, ts = _ANSWER_CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return answer, sources
        else:
            del _ANSWER_CACHE[key]
    return None


def _set_cache(question, answer, sources):
    _ANSWER_CACHE[_cache_key(question)] = (answer, sources, time.time())


def _call_deepseek(api_key, base_url, model, messages):
    url = f"{base_url}/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2000,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    resp = urllib.request.urlopen(req, timeout=90)
    raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    return data["choices"][0]["message"]["content"].strip()


def _call_deepseek_stream(api_key, base_url, model, messages):
    url = f"{base_url}/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2000,
        "stream": True,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    resp = urllib.request.urlopen(req, timeout=90)

    for chunk in resp:
        chunk = chunk.decode("utf-8")
        if not chunk.startswith("data: "):
            continue
        data_str = chunk[len("data: "):].strip()
        if data_str == "[DONE]":
            break
        try:
            data = json.loads(data_str)
            choices = data.get("choices", [])
            if choices and choices[0].get("delta", {}).get("content"):
                yield choices[0]["delta"]["content"]
        except (json.JSONDecodeError, KeyError):
            continue


def ask(question):
    cached = _get_cached(question)
    if cached:
        return {"answer": cached[0], "sources": cached[1]}

    api_key, base_url, model = _get_deepseek_config()

    results = semantic_index.search(question, top_k=3)
    if not results:
        return {"answer": "没有找到相关文档，无法回答此问题。", "sources": []}

    sources = []
    doc_parts = []

    for rel_path, score, mtime in results:
        full_path = os.path.join(BASE_DIR, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        doc_parts.append(f"【文档 {len(doc_parts) + 1}】{rel_path}\n{content}")
        title = _extract_title(full_path)
        section = _section_label(rel_path)
        mtime_str = time.strftime("%Y-%m-%d", time.localtime(mtime)) if mtime else ""
        sources.append({"path": rel_path, "title": title, "section": section, "mtime": mtime_str})

    if not doc_parts:
        return {"answer": "无法读取相关文档内容。", "sources": []}

    user_content = "\n\n---\n\n".join(doc_parts) + f"\n\n问题：{question}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    answer = _call_deepseek(api_key, base_url, model, messages)
    _set_cache(question, answer, sources)
    return {"answer": answer, "sources": sources}


def ask_stream(question):
    cached = _get_cached(question)
    if cached:
        yield json.dumps({"type": "sources", "sources": cached[1]}, ensure_ascii=False)
        for i in range(0, len(cached[0]), 10):
            yield json.dumps({"type": "token", "content": cached[0][i:i+10]}, ensure_ascii=False)
        yield json.dumps({"type": "done"})
        return

    api_key, base_url, model = _get_deepseek_config()

    results = semantic_index.search(question, top_k=3)
    if not results:
        yield json.dumps({"type": "error", "message": "没有找到相关文档，无法回答此问题。"})
        return

    sources = []
    doc_parts = []

    for rel_path, score, mtime in results:
        full_path = os.path.join(BASE_DIR, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        doc_parts.append(f"【文档 {len(doc_parts) + 1}】{rel_path}\n{content}")
        title = _extract_title(full_path)
        section = _section_label(rel_path)
        mtime_str = time.strftime("%Y-%m-%d", time.localtime(mtime)) if mtime else ""
        sources.append({"path": rel_path, "title": title, "section": section, "mtime": mtime_str})

    if not doc_parts:
        yield json.dumps({"type": "error", "message": "无法读取相关文档内容。"})
        return

    yield json.dumps({"type": "sources", "sources": sources}, ensure_ascii=False)

    user_content = "\n\n---\n\n".join(doc_parts) + f"\n\n问题：{question}"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    full_answer = ""
    for token in _call_deepseek_stream(api_key, base_url, model, messages):
        full_answer += token
        yield json.dumps({"type": "token", "content": token}, ensure_ascii=False)

    _set_cache(question, full_answer, sources)
    yield json.dumps({"type": "done"})


def chat(question, session_id=None):
    if session_id is None or session_id not in SessionManager._sessions:
        session_id = SessionManager.create_session()

    api_key, base_url, model = _get_deepseek_config()

    results = semantic_index.search(question, top_k=3)

    sources = []
    doc_parts = []

    for rel_path, score, mtime in results:
        full_path = os.path.join(BASE_DIR, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        mtime_str = time.strftime("%Y-%m-%d", time.localtime(mtime)) if mtime else ""
        doc_parts.append(f"【文档 {len(doc_parts) + 1} - {mtime_str}】{rel_path}\n{content}")
        title = _extract_title(full_path)
        section = _section_label(rel_path)
        sources.append({"path": rel_path, "title": title, "section": section, "mtime": mtime_str})

    history = SessionManager.get_history(session_id)

    if doc_parts:
        user_content = "\n\n---\n\n".join(doc_parts) + f"\n\n问题：{question}"
    else:
        user_content = f"问题：{question}"

    chat_system = SYSTEM_PROMPT + "\n\n" + (
        "演进检测规则：当检索到的文档中存在同一主题但不同时期的内容时，请执行：\n"
        "1. 对比各文档的核心观点，识别是否发生了变化\n"
        "2. 如果观点一致，正常回答即可，无需标注\n"
        "3. 如果观点存在明显的递进/修正/反转，在回答末尾用分隔线列出演进轨迹：\n"
        "   ---\n"
        "   观点变化轨迹：\n"
        "   - [日期]：原观点摘要\n"
        "   - [日期]：新观点摘要\n"
        "   变化类型：[递进 / 修正 / 反转]\n"
        "4. 如果变化程度较大（修正或反转），末尾追加：\n"
        "   ---\n"
        "   该主题观点存在较大变化。是否需要整合成一篇更新后的笔记？"
    )

    messages = [
        {"role": "system", "content": chat_system},
    ] + history + [
        {"role": "user", "content": user_content},
    ]

    answer = _call_deepseek(api_key, base_url, model, messages)

    SessionManager.add_message(session_id, "user", question)
    SessionManager.add_message(session_id, "assistant", answer)

    return {"answer": answer, "sources": sources, "session_id": session_id}


if __name__ == "__main__":
    test_question = "什么是好的AI产品"
    print(f"问题：{test_question}")
    print("正在检索相关文档并调用 DeepSeek 回答...")
    print()

    result = ask(test_question)

    print(f"回答：{result['answer']}")
    print()
    print("引用来源：")
    for s in result["sources"]:
        print(f"  - {s}")

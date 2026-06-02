import os
import sys
import json
import time
import hashlib
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


SYSTEM_PROMPT = "你是一个知识库助手。基于以下检索到的文档回答用户问题。如果文档中没有相关信息，明确告知用户。"

_ANSWER_CACHE = {}
_CACHE_TTL = 300


def _cache_key(question):
    return hashlib.sha256(question.strip().encode("utf-8")).hexdigest()


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

    results = semantic_index.search(question, top_k=5)
    if not results:
        return {"answer": "没有找到相关文档，无法回答此问题。", "sources": []}

    sources = []
    doc_parts = []

    for rel_path, score in results:
        full_path = os.path.join(BASE_DIR, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        doc_parts.append(f"【文档 {len(doc_parts) + 1}】{rel_path}\n{content}")
        sources.append(rel_path)

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

    results = semantic_index.search(question, top_k=5)
    if not results:
        yield json.dumps({"type": "error", "message": "没有找到相关文档，无法回答此问题。"})
        return

    sources = []
    doc_parts = []

    for rel_path, score in results:
        full_path = os.path.join(BASE_DIR, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        doc_parts.append(f"【文档 {len(doc_parts) + 1}】{rel_path}\n{content}")
        sources.append(rel_path)

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

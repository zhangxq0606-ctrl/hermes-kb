import os
import json
import time
import hashlib
import math
import glob as _glob

import numpy as np
from sentence_transformers import SentenceTransformer

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index_cache.json")

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
MODEL = None


def _find_local_model():
    candidates = []

    default_cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    repo_dir = os.path.join(default_cache, "models--BAAI--bge-small-zh-v1.5", "snapshots")
    if os.path.isdir(repo_dir):
        for name in os.listdir(repo_dir):
            p = os.path.join(repo_dir, name)
            if os.path.isdir(p) and os.path.isfile(os.path.join(p, "model.safetensors")):
                candidates.append(p)

    for cache_root in os.environ.get("HF_HOME", ""), "C:\\Users\\qqmin06\\.cache\\huggingface":
        if not cache_root:
            continue
        repo_dir = os.path.join(cache_root, "hub", "models--BAAI--bge-small-zh-v1.5", "snapshots")
        if os.path.isdir(repo_dir):
            for name in os.listdir(repo_dir):
                p = os.path.join(repo_dir, name)
                if os.path.isdir(p) and p not in candidates and os.path.isfile(os.path.join(p, "model.safetensors")):
                    candidates.append(p)

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0]

    local_project = os.path.join(BASE_DIR, "models", "bge-small-zh-v1.5")
    if os.path.isdir(local_project) and os.path.isfile(os.path.join(local_project, "model.safetensors")):
        return local_project

    return None


def _get_model():
    global MODEL
    if MODEL is None:
        local_path = _find_local_model()
        if local_path:
            os.environ["HF_HOME"] = os.path.dirname(os.path.dirname(os.path.dirname(local_path)))
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            MODEL = SentenceTransformer(local_path, local_files_only=True)
        else:
            MODEL = SentenceTransformer(MODEL_NAME)
    return MODEL


def _cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _file_hash(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def embed(text):
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def _iter_refined_files():
    refined_files = []
    for root_dir in ["core", "manual"]:
        scan_dir = os.path.join(BASE_DIR, root_dir)
        if not os.path.isdir(scan_dir):
            continue
        for dirpath, _, filenames in os.walk(scan_dir):
            for fn in filenames:
                if fn.endswith("_refined.md"):
                    refined_files.append(os.path.join(dirpath, fn))
    return refined_files


def _load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"files": {}}


def _save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def build_index():
    cache = _load_cache()
    existing = cache.get("files", {})
    refined_files = _iter_refined_files()

    updated = 0
    skipped = 0
    files_result = {}

    for filepath in refined_files:
        current_hash = _file_hash(filepath)
        rel_path = os.path.relpath(filepath, BASE_DIR).replace("\\", "/")

        if rel_path in existing and existing[rel_path].get("hash") == current_hash:
            skipped += 1
            files_result[rel_path] = existing[rel_path]
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.strip():
            skipped += 1
            files_result[rel_path] = existing.get(rel_path, {"hash": current_hash, "vector": []})
            continue

        vector = embed(content)
        updated += 1
        files_result[rel_path] = {"hash": current_hash, "vector": vector}

    cache["files"] = files_result
    cache["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save_cache(cache)

    return {"updated": updated, "skipped": skipped, "total": len(refined_files)}


def search(query, top_k=5):
    cache = _load_cache()
    files = cache.get("files", {})
    if not files:
        return []

    query_vec = embed(query)

    scored = []
    for path, entry in files.items():
        vec = entry.get("vector")
        if not vec:
            continue
        sim = _cosine_similarity(query_vec, vec)
        scored.append((path, sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


if __name__ == "__main__":
    result = build_index()
    print(f"索引构建完成：新增/更新 {result['updated']} 个，跳过 {result['skipped']} 个，共 {result['total']} 个文件")
    print(f"缓存路径：{CACHE_PATH}")

    cache = _load_cache()
    file_list = list(cache.get("files", {}).keys())
    if file_list:
        print(f"已缓存文件列表：")
        for f in file_list:
            entry = cache["files"][f]
            dims = len(entry["vector"]) if entry.get("vector") else 0
            print(f"  {f}  (向量维度: {dims})")

import json
from pathlib import Path

import jieba
import numpy as np
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi


# ============================================================
# 1. 文件位置
# ============================================================

CHUNK_FILE = Path("../data/chunks/all_chunks.jsonl")


# ============================================================
# 2. 读取Chunk
# ============================================================

print("=" * 60)
print("正在读取Chunk...")
print("=" * 60)

chunks = []

with open(CHUNK_FILE, "r", encoding="utf-8") as f:
    for line in f:
        chunks.append(json.loads(line))

print(f"共读取 {len(chunks)} 个Chunk")


texts = [chunk["text"] for chunk in chunks]


# ============================================================
# 3. BM25：使用中文分词
# ============================================================

print("\n正在建立BM25索引...")

tokenized_texts = [
    list(jieba.cut(text))
    for text in texts
]

bm25 = BM25Okapi(tokenized_texts)

print("BM25索引建立完成")


# ============================================================
# 4. 加载向量模型
# ============================================================

print("\n正在加载向量模型...")

model = SentenceTransformer(
    "BAAI/bge-small-zh-v1.5"
)

print("向量模型加载完成")


# ============================================================
# 5. 生成所有Chunk的向量
# ============================================================

print("\n正在生成文本向量...")

embeddings = model.encode(
    texts,
    normalize_embeddings=True,
    show_progress_bar=True
)

embeddings = np.array(embeddings)

print("向量生成完成")


# ============================================================
# 6. 向量检索
# ============================================================

def vector_search(query, top_k=10):

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True
    )[0]

    scores = embeddings @ query_embedding

    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []

    for rank, index in enumerate(top_indices, start=1):

        results.append({
            "index": int(index),
            "rank": rank,
            "score": float(scores[index])
        })

    return results


# ============================================================
# 7. BM25检索
# ============================================================

def bm25_search(query, top_k=10):

    query_tokens = list(jieba.cut(query))

    scores = bm25.get_scores(query_tokens)

    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []

    for rank, index in enumerate(top_indices, start=1):

        results.append({
            "index": int(index),
            "rank": rank,
            "score": float(scores[index])
        })

    return results


# ============================================================
# 8. RRF混合检索
# ============================================================

def hybrid_search(query, top_k=5):

    vector_results = vector_search(
        query,
        top_k=10
    )

    bm25_results = bm25_search(
        query,
        top_k=10
    )

    # Reciprocal Rank Fusion
    # 排名越靠前，得到的分数越高

    fusion_scores = {}

    for result in vector_results:

        index = result["index"]

        fusion_scores[index] = (
            fusion_scores.get(index, 0)
            + 1 / (60 + result["rank"])
        )

    for result in bm25_results:

        index = result["index"]

        fusion_scores[index] = (
            fusion_scores.get(index, 0)
            + 1 / (60 + result["rank"])
        )

    # 按混合分数排序

    sorted_indices = sorted(
        fusion_scores,
        key=fusion_scores.get,
        reverse=True
    )

    final_results = []

    for index in sorted_indices[:top_k]:

        result = chunks[index].copy()

        result["hybrid_score"] = fusion_scores[index]

        final_results.append(result)

    return final_results


# ============================================================
# 9. 显示结果
# ============================================================

def print_results(results):

    print("\n")
    print("=" * 60)
    print("混合检索结果")
    print("=" * 60)

    for i, result in enumerate(results, start=1):

        print(f"\n【结果 {i}】")

        print("公司：", result["company"])
        print("页码：", result["page"])
        print("章节：", result["section"])

        print(
            "混合得分：",
            round(result["hybrid_score"], 6)
        )

        print("\n内容：")

        print(result["text"][:500])

        print("-" * 60)


# ============================================================
# 10. 测试
# ============================================================

if __name__ == "__main__":

    query = input(
        "\n请输入你的问题："
    )

    results = hybrid_search(
        query,
        top_k=5
    )

    print_results(results)
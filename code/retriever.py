import json
from pathlib import Path

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

print(f"读取完成，共 {len(chunks)} 个Chunk")


# ============================================================
# 3. 准备文本
# ============================================================

texts = [chunk["text"] for chunk in chunks]


# ============================================================
# 4. 建立BM25
# ============================================================

print("\n正在建立BM25索引...")

tokenized_texts = [
    list(text)
    for text in texts
]

bm25 = BM25Okapi(tokenized_texts)

print("BM25建立完成")


# ============================================================
# 5. 加载中文向量模型
# ============================================================

print("\n正在加载中文向量模型...")

model = SentenceTransformer(
    "BAAI/bge-small-zh-v1.5"
)

print("向量模型加载完成")


# ============================================================
# 6. 把所有Chunk转换成向量
# ============================================================

print("\n正在生成向量，请稍等...")

embeddings = model.encode(
    texts,
    normalize_embeddings=True,
    show_progress_bar=True
)

embeddings = np.array(embeddings)

print("向量生成完成")
print("向量矩阵大小：", embeddings.shape)


# ============================================================
# 7. 向量检索
# ============================================================

def vector_search(query, top_k=5):

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True
    )[0]

    scores = embeddings @ query_embedding

    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []

    for index in top_indices:

        result = chunks[index].copy()

        result["score"] = float(scores[index])

        results.append(result)

    return results


# ============================================================
# 8. BM25检索
# ============================================================

def bm25_search(query, top_k=5):

    tokenized_query = list(query)

    scores = bm25.get_scores(tokenized_query)

    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []

    for index in top_indices:

        result = chunks[index].copy()

        result["score"] = float(scores[index])

        results.append(result)

    return results


# ============================================================
# 9. 打印检索结果
# ============================================================

def print_results(title, results):

    print("\n")
    print("=" * 60)
    print(title)
    print("=" * 60)

    for i, result in enumerate(results, start=1):

        print(f"\n【结果 {i}】")

        print("公司：", result["company"])
        print("页码：", result["page"])
        print("章节：", result["section"])
        print("分数：", round(result["score"], 4))

        print("\n内容：")

        print(result["text"][:300])

        print("-" * 60)


# ============================================================
# 10. 测试问题
# ============================================================

if __name__ == "__main__":

    query = input(
        "\n请输入你想查询的问题："
    )

    # 向量检索
    vector_results = vector_search(
        query,
        top_k=5
    )

    # BM25检索
    bm25_results = bm25_search(
        query,
        top_k=5
    )

    # 打印结果
    print_results(
        "向量检索结果",
        vector_results
    )

    print_results(
        "BM25检索结果",
        bm25_results
    )
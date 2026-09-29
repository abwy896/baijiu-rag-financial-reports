import json
from pathlib import Path

import jieba
import numpy as np
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi


# ============================================================
# 1. 读取Chunk
# ============================================================

CHUNK_FILE = Path("../data/chunks/all_chunks.jsonl")

chunks = []

with open(CHUNK_FILE, "r", encoding="utf-8") as f:
    for line in f:
        chunks.append(json.loads(line))

texts = [chunk["text"] for chunk in chunks]

print(f"共读取 {len(chunks)} 个Chunk")


# ============================================================
# 2. 公司名称
# ============================================================

COMPANIES = [
    "贵州茅台",
    "五粮液",
    "山西汾酒",
    "泸州老窖",
    "洋河股份",
    "今世缘",
    "古井贡酒",
    "舍得酒业",
    "口子窖",
    "金徽酒"
]


# ============================================================
# 3. BM25
# ============================================================

print("正在建立BM25索引...")

tokenized_texts = [
    list(jieba.cut(text))
    for text in texts
]

bm25 = BM25Okapi(tokenized_texts)

print("BM25完成")


# ============================================================
# 4. 向量模型
# ============================================================

print("正在加载向量模型...")

model = SentenceTransformer(
    "BAAI/bge-small-zh-v1.5"
)

print("模型加载完成")


# ============================================================
# 5. 向量
# ============================================================

print("正在生成向量...")

embeddings = model.encode(
    texts,
    normalize_embeddings=True,
    show_progress_bar=True
)

embeddings = np.array(embeddings)

print("向量生成完成")


# ============================================================
# 6. 找出问题中的公司
# ============================================================

def detect_company(query):

    for company in COMPANIES:

        if company in query:
            return company

    return None


# ============================================================
# 7. 改进版混合检索
# ============================================================

def improved_search(query, top_k=5):

    company = detect_company(query)

    print("\n识别到的公司：", company)

    # -----------------------------
    # 向量检索
    # -----------------------------

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True
    )[0]

    vector_scores = embeddings @ query_embedding


    # -----------------------------
    # BM25
    # -----------------------------

    query_tokens = list(jieba.cut(query))

    bm25_scores = bm25.get_scores(query_tokens)


    # -----------------------------
    # 综合评分
    # -----------------------------

    final_scores = []

    for i, chunk in enumerate(chunks):

        score = (
            0.5 * vector_scores[i]
            + 0.5 * (
                bm25_scores[i]
                / (max(bm25_scores) + 1e-8)
            )
        )

        # 公司匹配加分
        if company is not None:

            if chunk["company"] == company:

                score += 0.20

        final_scores.append(score)


    # -----------------------------
    # 排序
    # -----------------------------

    top_indices = np.argsort(
        final_scores
    )[::-1][:top_k]


    results = []

    for index in top_indices:

        result = chunks[index].copy()

        result["score"] = float(
            final_scores[index]
        )

        results.append(result)

    return results


# ============================================================
# 8. 显示结果
# ============================================================

def show_results(results):

    print("\n")
    print("=" * 70)
    print("改进后的检索结果")
    print("=" * 70)

    for i, result in enumerate(results, start=1):

        print(f"\n【结果 {i}】")

        print("公司：", result["company"])
        print("页码：", result["page"])
        print("章节：", result["section"])
        print("得分：", round(result["score"], 4))

        print("\n内容：")
        print(result["text"][:600])

        print("-" * 70)


# ============================================================
# 9. 测试
# ============================================================

if __name__ == "__main__":

    query = input(
        "\n请输入你的问题："
    )

    results = improved_search(
        query,
        top_k=5
    )

    show_results(results)
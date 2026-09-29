import os
import json
import jieba
import numpy as np

from openai import OpenAI
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer


# ============================================================
# 1. 路径
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

CHUNK_FILE = os.path.join(
    BASE_DIR,
    "data",
    "chunks",
    "all_chunks.jsonl"
)


# ============================================================
# 2. 读取财报文本
# ============================================================

print("正在读取财报数据...")

chunks = []

with open(CHUNK_FILE, "r", encoding="utf-8") as f:

    for line in f:
        chunks.append(json.loads(line))

print(f"共读取 {len(chunks)} 个文本块")


# ============================================================
# 3. 建立 BM25
# ============================================================

print("正在建立 BM25 索引...")

tokenized_corpus = [
    list(jieba.cut(chunk["text"]))
    for chunk in chunks
]

bm25 = BM25Okapi(tokenized_corpus)


# ============================================================
# 4. 加载向量模型
# ============================================================

print("正在加载向量模型...")

model = SentenceTransformer(
    "BAAI/bge-small-zh-v1.5"
)

texts = [
    chunk["text"]
    for chunk in chunks
]

print("正在计算文本向量...")

embeddings = model.encode(
    texts,
    normalize_embeddings=True,
    show_progress_bar=True
)

embeddings = np.array(embeddings)


# ============================================================
# 5. 公司列表
# ============================================================

companies = [
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


def detect_company(question):

    for company in companies:

        if company in question:
            return company

    return None


# ============================================================
# 6. 财报检索
# ============================================================

def retrieve(question, top_k=5):

    print("\n正在进行混合检索...")

    # -------------------------
    # 向量检索
    # -------------------------

    query_embedding = model.encode(
        [question],
        normalize_embeddings=True
    )[0]

    vector_scores = embeddings @ query_embedding


    # -------------------------
    # BM25检索
    # -------------------------

    query_tokens = list(
        jieba.cut(question)
    )

    bm25_scores = bm25.get_scores(
        query_tokens
    )


    # -------------------------
    # 分数归一化
    # -------------------------

    vector_norm = (
        (vector_scores - vector_scores.min())
        /
        (
            vector_scores.max()
            - vector_scores.min()
            + 1e-8
        )
    )

    bm25_norm = (
        (bm25_scores - bm25_scores.min())
        /
        (
            bm25_scores.max()
            - bm25_scores.min()
            + 1e-8
        )
    )


    # -------------------------
    # 混合评分
    # -------------------------

    scores = (
        0.5 * vector_norm
        +
        0.5 * bm25_norm
    )


    # -------------------------
    # 公司匹配加分
    # -------------------------

    detected_company = detect_company(
        question
    )

    if detected_company:

        print(
            f"识别到公司：{detected_company}"
        )

        for i, chunk in enumerate(chunks):

            if chunk.get("company") == detected_company:

                scores[i] += 0.20


    # -------------------------
    # 取得分最高的文本
    # -------------------------

    top_indices = np.argsort(
        scores
    )[::-1][:top_k]


    results = []

    for idx in top_indices:

        chunk = chunks[idx]

        results.append({

            "score": float(
                scores[idx]
            ),

            "company": chunk.get(
                "company",
                "未知公司"
            ),

            "report": chunk.get(
                "report",
                ""
            ),

            "page": chunk.get(
                "page",
                ""
            ),

            "section": chunk.get(
                "section",
                "待识别"
            ),

            "text": chunk.get(
                "text",
                ""
            )

        })


    return results


# ============================================================
# 7. DeepSeek
# ============================================================

api_key = os.environ.get(
    "DEEPSEEK_API_KEY"
)

if not api_key:

    raise ValueError(
        "没有找到 DEEPSEEK_API_KEY"
    )


client = OpenAI(

    api_key=api_key,

    base_url="https://api.deepseek.com"

)


# ============================================================
# 8. 让 DeepSeek 根据检索结果回答
# ============================================================

def generate_answer(
    question,
    results
):

    context = ""

    for i, result in enumerate(
        results,
        start=1
    ):

        context += f"""

[来源{i}]

公司：{result["company"]}

报告：{result["report"]}

页码：{result["page"]}

章节：{result["section"]}

财报内容：
{result["text"]}

"""


    prompt = f"""
你是一名上市公司财报分析助手。

请严格根据下面提供的财报检索结果回答用户问题。

用户问题：

{question}


财报检索结果：

{context}


回答要求：

1. 只能使用上面的财报内容。
2. 不要使用你自己的记忆补充数据。
3. 不要编造数字。
4. 如果财报内容无法确定答案，请明确说明。
5. 回答尽量简洁。
6. 如果涉及具体数字，请在答案后标明来源。
7. 使用[来源1]、[来源2]这样的格式标记来源。
"""


    response = client.chat.completions.create(

        model="deepseek-flash",

        messages=[

            {
                "role": "system",

                "content":
                "你是一个严谨的上市公司财报分析助手。"
            },

            {
                "role": "user",

                "content": prompt
            }

        ],

        stream=False

    )


    return response.choices[0].message.content


# ============================================================
# 9. 主程序
# ============================================================

if __name__ == "__main__":

    print("\n")
    print("=" * 70)
    print("白酒行业上市公司财报 RAG 问答系统")
    print("=" * 70)

    question = input(
        "\n请输入你的问题："
    )


    # -------------------------
    # 检索
    # -------------------------

    results = retrieve(
        question,
        top_k=5
    )


    # -------------------------
    # 显示检索结果
    # -------------------------

    print("\n")
    print("=" * 70)
    print("检索到的财报内容")
    print("=" * 70)


    for i, result in enumerate(
        results,
        start=1
    ):

        print(
            f"\n【来源{i}】"
        )

        print(
            f"公司：{result['company']}"
        )

        print(
            f"报告：{result['report']}"
        )

        print(
            f"页码：{result['page']}"
        )

        print(
            f"相关度：{result['score']:.4f}"
        )

        print(
            "内容："
        )

        print(
            result["text"][:400]
        )


    # -------------------------
    # DeepSeek回答
    # -------------------------

    print("\n")
    print("=" * 70)
    print("DeepSeek回答")
    print("=" * 70)


    answer = generate_answer(
        question,
        results
    )


    print(answer)


    print("\n")
    print("=" * 70)
    print("RAG问答完成")
    print("=" * 70)
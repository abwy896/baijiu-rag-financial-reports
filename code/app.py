import os
import json
import jieba
import numpy as np
import streamlit as st

from openai import OpenAI
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer


# ============================================================
# 页面设置
# ============================================================

st.set_page_config(
    page_title="白酒行业财报RAG",
    page_icon="📊",
    layout="wide"
)


st.title("📊 白酒行业上市公司财报 RAG 问答系统")

st.write(
    "基于10家白酒上市公司2025年年度报告，"
    "通过 BM25 + 向量检索获取相关财报内容，"
    "并使用 DeepSeek 生成答案。"
)


# ============================================================
# 路径
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
# 加载数据和模型
# ============================================================

@st.cache_resource
def load_data():

    chunks = []

    with open(
        CHUNK_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        for line in f:
            chunks.append(json.loads(line))


    # BM25

    tokenized_corpus = [
        list(jieba.cut(chunk["text"]))
        for chunk in chunks
    ]

    bm25 = BM25Okapi(
        tokenized_corpus
    )


    # 向量模型

    model = SentenceTransformer(
        "BAAI/bge-small-zh-v1.5"
    )


    texts = [
        chunk["text"]
        for chunk in chunks
    ]


    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True
    )


    embeddings = np.array(
        embeddings
    )


    return (
        chunks,
        bm25,
        model,
        embeddings
    )


# ============================================================
# 加载
# ============================================================

with st.spinner(
    "正在加载财报知识库，请稍候..."
):

    chunks, bm25, model, embeddings = load_data()


st.success(
    f"知识库加载完成，共 {len(chunks)} 个文本块"
)


# ============================================================
# 公司列表
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
# 检索
# ============================================================

def retrieve(
    question,
    top_k=5
):

    # 向量

    query_embedding = model.encode(
        [question],
        normalize_embeddings=True
    )[0]

    vector_scores = (
        embeddings @ query_embedding
    )


    # BM25

    query_tokens = list(
        jieba.cut(question)
    )

    bm25_scores = bm25.get_scores(
        query_tokens
    )


    # 归一化

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


    # 混合评分

    scores = (
        0.5 * vector_norm
        +
        0.5 * bm25_norm
    )


    # 公司加分

    detected_company = detect_company(
        question
    )

    if detected_company:

        for i, chunk in enumerate(chunks):

            if chunk.get("company") == detected_company:

                scores[i] += 0.20


    # Top K

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
# DeepSeek
# ============================================================

api_key = os.environ.get(
    "DEEPSEEK_API_KEY"
)


if not api_key:

    st.error(
        "没有检测到 DEEPSEEK_API_KEY，请先配置 API Key。"
    )

    st.stop()


client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com"
)


# ============================================================
# 生成答案
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

1. 只能使用提供的财报内容。
2. 不要使用自己的记忆补充数据。
3. 不要编造数字。
4. 如果无法从材料确定答案，请明确说明。
5. 回答尽量简洁。
6. 涉及具体数字时必须标明来源。
7. 使用[来源1]、[来源2]这样的格式。
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
# 网页输入
# ============================================================

st.divider()

st.subheader("🔎 财报问答")


question = st.text_input(
    "请输入你的问题",
    placeholder="例如：贵州茅台2025年营业收入是多少？"
)


if st.button(
    "开始检索",
    type="primary"
):

    if not question.strip():

        st.warning(
            "请输入问题后再进行检索。"
        )

    else:

        # 检索

        with st.spinner(
            "正在检索相关财报..."
        ):

            results = retrieve(
                question,
                top_k=5
            )


        # 回答

        with st.spinner(
            "DeepSeek正在生成答案..."
        ):

            answer = generate_answer(
                question,
                results
            )


        # ====================================================
        # 答案
        # ====================================================

        st.divider()

        st.subheader("💡 回答")

        st.write(answer)


        # ====================================================
        # 来源
        # ====================================================

        st.divider()

        st.subheader("📚 检索到的财报来源")


        for i, result in enumerate(
            results,
            start=1
        ):

            with st.expander(
                f"来源{i}｜{result['company']}｜第 {result['page']} 页"
            ):

                st.write(
                    f"**公司：** {result['company']}"
                )

                st.write(
                    f"**报告：** {result['report']}"
                )

                st.write(
                    f"**页码：** {result['page']}"
                )

                st.write(
                    f"**相关度：** {result['score']:.4f}"
                )

                st.write(
                    "**财报内容：**"
                )

                st.write(
                    result["text"]
                )
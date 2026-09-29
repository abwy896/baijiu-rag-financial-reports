import os
import json

from openai import OpenAI


# =========================
# 1. 读取财报文本块
# =========================

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

CHUNK_FILE = os.path.join(
    BASE_DIR,
    "data",
    "chunks",
    "all_chunks.jsonl"
)

chunks = []

with open(CHUNK_FILE, "r", encoding="utf-8") as f:
    for line in f:
        chunks.append(json.loads(line))

print("成功读取文本块：", len(chunks))


# =========================
# 2. 先手动选择一个已经确认正确的财报片段
# =========================

question = "贵州茅台2025年营业收入是多少？"

context = """
公司：贵州茅台

报告：2025年年度报告

页码：54

财报内容：
贵州茅台酒股份有限公司2025年年度报告。
2025年度，贵州茅台公司的营业收入为人民币16,883,810.25万元。
其中主营业务收入为人民币16,877,158.52万元，占营业收入的99.96%。
"""


# =========================
# 3. 读取 API Key
# =========================

api_key = os.environ.get("DEEPSEEK_API_KEY")

if not api_key:
    raise ValueError(
        "没有找到 DEEPSEEK_API_KEY"
    )


# =========================
# 4. 创建 DeepSeek 客户端
# =========================

client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com"
)


# =========================
# 5. 发送 RAG 请求
# =========================

prompt = f"""
你是一名上市公司财报分析助手。

请根据下面提供的财报内容回答问题。

问题：
{question}

财报内容：
{context}

要求：
1. 只能根据提供的财报内容回答。
2. 不要自己补充其他数据。
3. 给出明确的数字。
4. 最后标明来源页码。
"""

print("\n正在调用 DeepSeek...\n")

response = client.chat.completions.create(
    model="deepseek-flash",
    messages=[
        {
            "role": "system",
            "content": "你是一个严谨的上市公司财报分析助手。"
        },
        {
            "role": "user",
            "content": prompt
        }
    ],
    stream=False
)


# =========================
# 6. 输出结果
# =========================

print("=" * 60)
print("RAG测试结果")
print("=" * 60)

print(response.choices[0].message.content)

print("=" * 60)
print("测试完成")
print("=" * 60)
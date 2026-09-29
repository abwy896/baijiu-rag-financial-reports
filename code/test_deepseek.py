import os
from openai import OpenAI


# 从系统环境变量读取 API Key
api_key = os.environ.get("DEEPSEEK_API_KEY")


if not api_key:
    raise ValueError(
        "没有找到 DEEPSEEK_API_KEY，请先在终端设置 API Key"
    )


# 创建 DeepSeek 客户端
client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com"
)


# 调用 DeepSeek
response = client.chat.completions.create(
    model="deepseek-flash",
    messages=[
        {
            "role": "system",
            "content": "你是一个帮助分析上市公司年报的助手。"
        },
        {
            "role": "user",
            "content": "请用一句话告诉我，RAG是什么？"
        }
    ],
    stream=False
)


# 输出答案
print("\nDeepSeek回答：")
print(response.choices[0].message.content)
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("ASI_ONE_API_KEY"),
    base_url="https://api.asi1.ai/v1"
)

response = client.chat.completions.create(
    model="asi1",
    messages=[
        {
            "role": "user",
            "content": "你好，请回复：ASI连接成功"
        }
    ]
)

print(response.choices[0].message.content)
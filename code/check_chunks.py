import json
from pathlib import Path


# Chunk文件位置
CHUNK_FILE = Path("../data/chunks/all_chunks.jsonl")


# 读取全部Chunk
chunks = []

with open(CHUNK_FILE, "r", encoding="utf-8") as f:

    for line in f:
        chunks.append(json.loads(line))


print("=" * 60)
print("Chunk检查程序")
print("=" * 60)

print(f"Chunk总数量：{len(chunks)}")


# =========================
# 1. 检查前5个Chunk
# =========================

print("\n")
print("=" * 60)
print("前5个Chunk")
print("=" * 60)


for i, chunk in enumerate(chunks[:5], start=1):

    print(f"\n【Chunk {i}】")

    print("Chunk ID：", chunk["chunk_id"])
    print("公司：", chunk["company"])
    print("报告：", chunk["report"])
    print("页码：", chunk["page"])
    print("章节：", chunk["section"])

    print("\n文字内容：")
    print(chunk["text"][:500])

    print("\n" + "-" * 60)


# =========================
# 2. 统计每家公司Chunk数量
# =========================

company_count = {}

for chunk in chunks:

    company = chunk["company"]

    if company not in company_count:
        company_count[company] = 0

    company_count[company] += 1


print("\n")
print("=" * 60)
print("各公司Chunk数量")
print("=" * 60)


for company, count in company_count.items():

    print(f"{company}: {count}")


# =========================
# 3. 检查有没有未知公司
# =========================

unknown = [
    chunk for chunk in chunks
    if chunk["company"] == "未知公司"
]


print("\n")
print("=" * 60)
print("异常检查")
print("=" * 60)

print(f"未知公司Chunk数量：{len(unknown)}")


if len(unknown) == 0:

    print("✓ 公司识别全部正常")

else:

    print("⚠ 有Chunk没有识别出公司")


# =========================
# 4. 检查空文本
# =========================

empty_text = [
    chunk for chunk in chunks
    if not chunk["text"].strip()
]


print(f"空文本Chunk数量：{len(empty_text)}")


if len(empty_text) == 0:

    print("✓ 没有发现空文本")

else:

    print("⚠ 发现空文本，请检查")


print("\n")
print("=" * 60)
print("检查完成")
print("=" * 60)
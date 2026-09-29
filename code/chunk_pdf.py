import json
from pathlib import Path


# =========================
# 1. 文件夹位置
# =========================

RAW_DIR = Path("../data/raw")
OUTPUT_DIR = Path("../data/chunks")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# =========================
# 2. Chunk参数
# =========================

CHUNK_SIZE = 800
OVERLAP = 120


# =========================
# 3. 根据文件名判断公司
# =========================

COMPANY_NAMES = {
    "安徽古井贡酒股份有限公司": "古井贡酒",
    "贵州口子酒业股份有限公司": "口子窖",
    "贵州茅台酒股份有限公司": "贵州茅台",
    "江苏今世缘酒业股份有限公司": "今世缘",
    "江苏洋河酒厂股份有限公司": "洋河股份",
    "金徽酒股份有限公司": "金徽酒",
    "泸州老窖股份有限公司": "泸州老窖",
    "山西杏花村汾酒厂股份有限公司": "山西汾酒",
    "舍得酒业股份有限公司": "舍得酒业",
    "宜宾五粮液股份有限公司": "五粮液"
}


def get_company(filename):
    """
    从文件名中识别公司名称
    """
    for full_name, short_name in COMPANY_NAMES.items():
        if full_name in filename:
            return short_name

    return "未知公司"


# =========================
# 4. 文本切块函数
# =========================

def split_text(text, chunk_size=800, overlap=120):

    text = text.strip()

    if not text:
        return []

    chunks = []

    start = 0

    while start < len(text):

        end = start + chunk_size

        chunk = text[start:end]

        if chunk.strip():
            chunks.append(chunk.strip())

        start += chunk_size - overlap

    return chunks


# =========================
# 5. 处理所有JSON
# =========================

all_chunks = []

json_files = list(RAW_DIR.glob("*.json"))

print(f"一共发现 {len(json_files)} 个JSON文件")
print("=" * 60)


for json_path in json_files:

    print(f"正在处理：{json_path.name}")

    company = get_company(json_path.name)

    # 读取JSON
    with open(json_path, "r", encoding="utf-8") as f:
        pages = json.load(f)

    file_chunk_count = 0

    # 遍历每一页
    for page_data in pages:

        page_number = page_data["page"]
        text = page_data["text"]

        # 对这一页进行切块
        chunks = split_text(
            text,
            chunk_size=CHUNK_SIZE,
            overlap=OVERLAP
        )

        for chunk_index, chunk in enumerate(chunks):

            item = {
                "chunk_id": f"{company}_{page_number}_{chunk_index}",
                "company": company,
                "report": "2025年年度报告",
                "page": page_number,
                "section": "待识别",
                "text": chunk
            }

            all_chunks.append(item)

            file_chunk_count += 1

    print(f"公司：{company}")
    print(f"生成Chunk：{file_chunk_count}")
    print("-" * 60)


# =========================
# 6. 保存全部Chunk
# =========================

output_file = OUTPUT_DIR / "all_chunks.jsonl"

with open(output_file, "w", encoding="utf-8") as f:

    for item in all_chunks:
        f.write(
            json.dumps(item, ensure_ascii=False)
            + "\n"
        )


print("=" * 60)
print("全部处理完成！")
print(f"总Chunk数量：{len(all_chunks)}")
print(f"保存位置：{output_file}")
import fitz
from pathlib import Path
import json

# PDF文件所在位置
PDF_DIR = Path("../reports")

# 输出文件夹
OUTPUT_DIR = Path("../data/raw")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def extract_pdf(pdf_path):
    """提取PDF中的文字，并保留页码"""
    
    doc = fitz.open(pdf_path)
    pages = []

    for page_number, page in enumerate(doc, start=1):
        text = page.get_text("text")

        pages.append({
            "page": page_number,
            "text": text
        })

    return pages


# 处理reports文件夹中的所有PDF
for pdf_path in PDF_DIR.glob("*.pdf"):

    print(f"正在处理：{pdf_path.name}")

    pages = extract_pdf(pdf_path)

    output_name = pdf_path.stem + ".json"
    output_path = OUTPUT_DIR / output_name

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    print(f"完成：{output_path}")
    print(f"共提取 {len(pages)} 页")
    print("-" * 50)

print("全部PDF处理完成！")
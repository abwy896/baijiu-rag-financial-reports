"""修复原始RAG知识库：重建贵州茅台页码/原文，补入口子窖2025年年报。
只处理这两家目标公司，其他公司的旧知识块保留。运行前会备份旧JSONL。
"""
from __future__ import annotations
import csv, json, re, shutil, sys, time
from pathlib import Path
import requests
import fitz

ROOT = Path(__file__).resolve().parents[1]
CHUNK_PATH = ROOT / 'data' / 'chunks' / 'all_chunks.jsonl'
PDF_DIR = ROOT / 'data' / 'pdfs'
CATALOG_PATH = ROOT / 'data' / 'source_catalog.csv'
COMPANIES = ['贵州茅台','五粮液','山西汾酒','泸州老窖','洋河股份','今世缘','古井贡酒','舍得酒业','口子窖','金徽酒']
TARGETS = ['贵州茅台','口子窖']
PDFS = {
    '贵州茅台': {
        'filename': '贵州茅台_2025年年度报告.pdf',
        'urls': [
            'https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-17/600519_20260417_9QS4.pdf',
            'https://stockmc.xueqiu.com/202604/600519_20260417_9QS4.pdf',
        ],
        'pdf_url': 'https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-17/600519_20260417_9QS4.pdf',
    },
    '口子窖': {
        'filename': '口子窖_2025年年度报告.pdf',
        'urls': [
            'https://static.cninfo.com.cn/finalpage/2026-04-23/1225145285.PDF',
        ],
        'pdf_url': 'https://static.cninfo.com.cn/finalpage/2026-04-23/1225145285.PDF',
    },
}

ALIASES = {
    '贵州茅台酒股份有限公司':'贵州茅台', '贵州茅台':'贵州茅台',
    '五粮液股份有限公司':'五粮液', '四川五粮液':'五粮液', '五粮液':'五粮液',
    '山西杏花村汾酒厂股份有限公司':'山西汾酒', '山西汾酒':'山西汾酒',
    '泸州老窖股份有限公司':'泸州老窖', '泸州老窖':'泸州老窖',
    '江苏洋河酒厂股份有限公司':'洋河股份', '洋河股份':'洋河股份',
    '江苏今世缘酒业股份有限公司':'今世缘', '今世缘':'今世缘',
    '安徽古井贡酒股份有限公司':'古井贡酒', '古井贡酒':'古井贡酒',
    '舍得酒业股份有限公司':'舍得酒业', '舍得酒业':'舍得酒业',
    '安徽口子酒业股份有限公司':'口子窖', '口子窖':'口子窖',
    '金徽酒股份有限公司':'金徽酒', '金徽酒':'金徽酒',
}


def canonical_company(row):
    # 先信任显式company字段，再看report标题；只有二者都无法判断时才用正文，
    # 避免某家公司正文提到另一家酒企时被错误改归属。
    for field in ('company', 'report', 'source'):
        value = str(row.get(field, '') or '')
        for alias, canonical in ALIASES.items():
            if alias in value:
                return canonical
        for canonical in COMPANIES:
            if canonical in value:
                return canonical
    value = str(row.get('text', '') or '')[:180]
    for alias, canonical in ALIASES.items():
        if alias in value:
            return canonical
    for canonical in COMPANIES:
        if canonical in value:
            return canonical
    return str(row.get('company', '') or '').strip()


def valid_pdf(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 10000 and path.open('rb').read(5) == b'%PDF-'
    except OSError:
        return False


def download_pdf(company: str) -> Path:
    spec = PDFS[company]
    dest = PDF_DIR / spec['filename']
    if valid_pdf(dest):
        print(f'已使用本地PDF：{dest.name}')
        return dest
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    headers = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'}
    errors=[]
    for url in spec['urls']:
        try:
            print(f'正在下载{company}年报：{url}')
            r = requests.get(url, headers=headers, timeout=90)
            r.raise_for_status()
            if not r.content.startswith(b'%PDF-'):
                raise ValueError(f'返回内容不是PDF（Content-Type={r.headers.get("Content-Type", "未知")}）')
            tmp = dest.with_suffix('.download')
            tmp.write_bytes(r.content)
            tmp.replace(dest)
            print(f'下载成功：{dest.name}（{dest.stat().st_size:,}字节）')
            return dest
        except Exception as e:
            errors.append(f'{url} -> {type(e).__name__}: {e}')
    raise RuntimeError(f'无法自动下载{company}年报。尝试地址：\n' + '\n'.join(errors) + '\n请在浏览器打开README列出的官方PDF链接，另存为：' + str(dest))


def section_for_text(text: str, current: str) -> str:
    # 只标注文本中有直接依据的章节/报表标题。
    compact = re.sub(r'\s+', '', text)
    patterns = [
        ('近三年主要会计数据和财务指标', '主要会计数据及财务指标'),
        ('主要会计数据', '主要会计数据'), ('主要财务指标', '主要财务指标'),
        ('合并资产负债表', '合并资产负债表'), ('母公司资产负债表', '母公司资产负债表'),
        ('合并利润表', '合并利润表'), ('母公司利润表', '母公司利润表'),
        ('合并现金流量表', '合并现金流量表'), ('母公司现金流量表', '母公司现金流量表'),
        ('营业收入和营业成本', '营业收入和营业成本'), ('主营业务分行业', '主营业务分行业'),
    ]
    for needle, label in patterns:
        if needle in compact:
            return label
    for line in text.splitlines()[:50]:
        s = re.sub(r'\s+', '', line).strip('：: ')
        if len(s) <= 45 and re.match(r'^第[一二三四五六七八九十\d]+节', s):
            return s
    return current or '未识别（原PDF无可用章节标题）'


def printed_page(text: str):
    # PDF内页脚常见“6 / 143”；保留为独立字段，绝不代替PDF物理页码。
    m = re.search(r'(?m)^\s*(\d{1,3})\s*/\s*\d{1,3}\s*$', text)
    if m:
        return int(m.group(1))
    m = re.search(r'(?m)^\s*(\d{1,3})\s*$', text[-350:])
    return int(m.group(1)) if m else None


def split_page(text: str, size=1300, overlap=120):
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    out=[]; start=0
    while start < len(text):
        end=min(start+size, len(text))
        if end < len(text):
            part=text[start:end]
            candidates=[part.rfind('\n'),part.rfind('。'),part.rfind('；'),part.rfind(' | ')]
            cut=max(candidates)
            if cut > size*0.60:
                end=start+cut+1
        out.append(text[start:end].strip())
        if end >= len(text): break
        start=max(start+1,end-overlap)
    return out


def make_verified_table_chunk(company: str, page_no: int, text: str, source_url: str, ppage):
    # 仅在该页原文同时包含完整字段和值时，生成一段保留表头关系的可检索表格行。
    specs = {
        '贵州茅台': {
            'need': ['营业收入','168,838,102,514.79','170,899,152,276.34','-1.21'],
            'text': '表名：七、近三年主要会计数据和财务指标；（一）主要会计数据。单位：元，币种：人民币。数据行：项目=营业收入；2025年=168,838,102,514.79；2024年=170,899,152,276.34；本期比上年同期增减（%）=-1.21；2023年=147,693,604,994.14。',
            'section': '主要会计数据及财务指标 / 营业收入表格行',
        },
        '口子窖': {
            'need': ['营业收入','3,990,595,921.88','6,014,705,362.71','-33.65'],
            'text': '表名：七、近三年主要会计数据和财务指标；（一）主要会计数据。单位：元，币种：人民币。数据行：项目=营业收入；2025年=3,990,595,921.88；2024年=6,014,705,362.71；本期比上年同期增减（%）=-33.65；2023年=5,961,904,835.83。',
            'section': '主要会计数据及财务指标 / 营业收入表格行',
        }
    }
    spec=specs[company]
    compact = re.sub(r'\s+', '', text)
    if all(re.sub(r'\s+', '', x) in compact for x in spec['need']):
        return {'company':company,'report':'2025年年度报告','page':page_no,'pdf_page':page_no,
                'printed_page':ppage,'section':spec['section'],'text':spec['text'],
                'source_url':source_url,'chunk_id':f'{company}_PDF{page_no:03d}_VERIFIED_REVENUE_TABLE',
                'kind':'verified_table_restructured_from_pdf'}
    return None


def parse_pdf(company: str, pdf_path: Path):
    source_url=PDFS[company]['pdf_url']
    doc=fitz.open(str(pdf_path)); rows=[]; current='未识别（原PDF无可用章节标题）'
    toc=sorted(doc.get_toc(),key=lambda z:z[2])
    for idx, page in enumerate(doc):
        p=idx+1
        text=page.get_text('text', sort=True).strip()
        if not text: continue
        if toc:
            eligible=[t for t in toc if int(t[2]) <= p]
            if eligible: current=eligible[-1][1]
        current=section_for_text(text,current)
        ppage=printed_page(text)
        pieces=split_page(text)
        for j,piece in enumerate(pieces):
            rows.append({'company':company,'report':'2025年年度报告','page':p,'pdf_page':p,
                         'printed_page':ppage,'section':current,'text':piece,
                         'source_url':source_url,'chunk_id':f'{company}_PDF{p:03d}_T{j:02d}','kind':'pdf_page_text'})
        special=make_verified_table_chunk(company,p,text,source_url,ppage)
        if special: rows.append(special)
    doc.close()
    if len(rows) < 100:
        raise RuntimeError(f'{company} PDF解析结果异常，仅生成{len(rows)}块；文件可能不是完整年报。')
    return rows


def load_old_rows(path):
    rows=[]
    with path.open('r',encoding='utf-8-sig') as f:
        for n,line in enumerate(f,1):
            if not line.strip(): continue
            try: row=json.loads(line)
            except Exception as e: raise ValueError(f'旧知识库第{n}行JSON错误：{e}')
            if not str(row.get('text','')).strip(): continue
            row['company']=canonical_company(row)
            rows.append(row)
    return rows


def update_catalog():
    with CATALOG_PATH.open('r',encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); fields=reader.fieldnames; rows=list(reader)
    for row in rows:
        c=row.get('company','')
        if c in PDFS:
            row['pdf_url']=PDFS[c]['pdf_url']
            if 'source_type' in row: row['source_type']='PDF直达'
            row['核对状态']='已补官方PDF；物理页码由本地PDF重新解析'
    with CATALOG_PATH.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def main():
    if not CHUNK_PATH.exists() or CHUNK_PATH.stat().st_size < 50000:
        raise SystemExit(f'没有找到原知识库：{CHUNK_PATH}\n请先启动问答页面一次，确认已下载真实知识块，再运行本修复程序。')
    print('第1/4步：准备两份真实年报PDF……')
    pdfs={c:download_pdf(c) for c in TARGETS}
    print('第2/4步：重新解析贵州茅台、口子窖PDF（按物理页分块）……')
    fresh=[]
    for c in TARGETS:
        parsed=parse_pdf(c,pdfs[c]); fresh.extend(parsed)
        print(f'  {c}：解析生成 {len(parsed):,} 个块')
    print('第3/4步：备份旧知识库，并替换这两家公司的旧块……')
    old=load_old_rows(CHUNK_PATH)
    kept=[r for r in old if r.get('company') not in TARGETS]
    before={c:sum(r.get('company')==c for r in old) for c in COMPANIES}
    stamp=time.strftime('%Y%m%d_%H%M%S')
    backup=CHUNK_PATH.with_name(f'all_chunks.jsonl.before_repair_{stamp}.backup')
    shutil.copy2(CHUNK_PATH,backup)
    tmp=CHUNK_PATH.with_suffix('.jsonl.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        for row in kept+fresh:
            f.write(json.dumps(row,ensure_ascii=False)+'\n')
    tmp.replace(CHUNK_PATH)
    update_catalog()
    final=kept+fresh
    coverage={c:sum(r.get('company')==c for r in final) for c in COMPANIES}
    print('第4/4步：修复完成。')
    print(f'旧块数：{len(old):,}；新块数：{len(final):,}；备份：{backup.name}')
    print('公司覆盖：')
    for c,n in coverage.items(): print(f'  {c}: {n:,}')
    print('贵州茅台2025营业收入专用表格块：',sum(r.get('company')=='贵州茅台' and r.get('kind')=='verified_table_restructured_from_pdf' for r in final))
    missing=[c for c,n in coverage.items() if n==0]
    if missing:
        print('警告：仍有公司没有块：'+'、'.join(missing))
    else:
        print('公司覆盖已达到10/10。')
    print('现在请重新启动问答页面；如果旧页面还开着，先在运行它的CMD按Ctrl+C，再执行启动问答页面.bat。')

if __name__=='__main__':
    try: main()
    except Exception as e:
        print('\n修复未完成：',type(e).__name__,str(e))
        print('注意：如果下载失败，旧知识库不会被覆盖。检查网络后重试，或将官方PDF放到 data/pdfs 对应文件名。')
        sys.exit(1)

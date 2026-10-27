"""从10份真实PDF重新提取章节、页码、文本及表格，覆盖旧库。不会上传原PDF。"""
import csv, json, re, argparse
from pathlib import Path
import fitz
from rag_core import ROOT, COMPANIES

def heading(line):
    s = re.sub(r'\s+', '',line)
    if len(s) > 48: return False
    return bool(re.match(r'^第[一二三四五六七八九十\d]+节',s)) or s in {
       '合并资产负债表','母公司资产负债表','合并利润表','母公司利润表',
       '合并现金流量表','母公司现金流量表','主要会计数据','主要财务指标'}

def chunk_text(text, size=850, overlap=130):
    text = text.strip()
    if not text: return []
    output=[]; start=0
    while start<len(text):
        end=min(start+size,len(text)); block=text[start:end]
        if end<len(text):
            pos=max(block.rfind('。'),block.rfind('\n'),block.rfind('；'))
            if pos>int(size*.65):end=start+pos+1;block=text[start:end]
        output.append(block)
        if end>=len(text):break
        start=max(start+1,end-overlap)
    return output

def parse_pdf(path, company, pdf_url=''):
    doc=fitz.open(str(path)); chunks=[]; current='未识别（原PDF无可用章节标题）'
    toc=sorted(doc.get_toc(),key=lambda z:z[2])
    for pageid, page in enumerate(doc):
        p=pageid+1
        if toc:
            eligible=[t for t in toc if t[2]<=p]
            if eligible: current=eligible[-1][1]
        txt=page.get_text('text',sort=True)
        lines=txt.splitlines()
        for ln in lines[:100]:
            if heading(ln): current=ln.strip()
        for j,text in enumerate(chunk_text(txt)):
            chunks.append({'company':company,'report':'2025年年度报告','page':p,
                           'section':current,'text':text,'source_url':pdf_url,
                           'chunk_id':f'{company}-P{p:03d}-T{j:02d}','kind':'text'})
        # 对PDF表格保持“表头 + 每行字段”，避免只检索到孤立数字
        try:
            tables=page.find_tables()
            for ti,t in enumerate(tables.tables):
                rows=t.extract(); header=' | '.join(str(c or '').replace('\n',' ') for c in (rows[0] if rows else []))
                for ri in range(1,len(rows)):
                    row=' | '.join(str(c or '').replace('\n',' ') for c in rows[ri])
                    if row.strip(' |'):
                        chunks.append({'company':company,'report':'2025年年度报告','page':p,
                                       'section':current+' / 财务表格（页内提取）',
                                       'text':f'表头：{header}\n数据行：{row}', 'source_url':pdf_url,
                                       'chunk_id':f'{company}-P{p:03d}-TB{ti:02d}-R{ri:03d}', 'kind':'table'})
        except Exception:
            pass
    doc.close()
    return chunks

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--pdf-dir',default=str(ROOT/'data'/'pdfs')); ap.add_argument('--allow-partial',action='store_true',help='仅调试用，不建议：缺失公司也输出')
    args=ap.parse_args()
    directory=Path(args.pdf_dir)
    with (ROOT/'data'/'source_catalog.csv').open(encoding='utf-8-sig',newline='') as f:
        catalog={row['company']:row for row in csv.DictReader(f)}
    rows=[]; missing=[]
    for c in COMPANIES:
        path=directory/(c+'_2025年年度报告.pdf')
        if not path.exists():missing.append(path.name);continue
        out=parse_pdf(path,c,catalog.get(c,{}).get('pdf_url',''))
        rows.extend(out);print(c, '页/行块数:',len(out))
    if missing:
        print('未找到以下PDF：', '、'.join(missing))
        if not args.allow_partial: raise SystemExit('为避免覆盖原有10家公司，请先下载齐10份PDF；如明确要生成局部测试索引，可传--allow-partial。')
        if not rows:raise SystemExit('请先将真实原始PDF放入data/pdfs，命名为“公司_2025年年度报告.pdf”。')
    target=ROOT/'data'/'chunks'/'all_chunks.jsonl'
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():target.rename(target.with_suffix('.jsonl.backup'))
    with target.open('w',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print('完成：',target,'共',len(rows),'块；注意仅包含找到PDF的公司。')
if __name__=='__main__':main()

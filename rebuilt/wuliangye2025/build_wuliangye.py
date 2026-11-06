import fitz,json,hashlib,html,csv,os,sys
from pathlib import Path
P=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent / '五粮液_2025年年度报告.pdf'
O=Path(__file__).resolve().parent; O.mkdir(exist_ok=True)
doc=fitz.open(P); sha=hashlib.sha256(P.read_bytes()).hexdigest()
company='五粮液'; report='宜宾五粮液股份有限公司2025年度报告'
sec='第二节 公司简介和主要财务指标'
def cells(r):return {i:str(x).strip().replace('\n','') for i,x in enumerate(r) if x is not None and str(x).strip()}
def reconstruct(table, page, table_index, title, section, sub, columns, mapping, unit, source_page=None):
    raw=table.extract(); rows=[]; unresolved=[]
    for i,r in enumerate(raw):
        if i==0 and page!=8 or (page==8 and table_index==1 and i==0):continue
        c=cells(r)
        if not c:continue
        label=c.get(1,'')
        vals=[c.get(j,'') for j in mapping]
        if label and not any(vals):
            if rows:
                rows[-1]['indicator']+=label
                rows[-1]['source_row_indices'].append(i)
            else: unresolved.append({'row':i,'cells':c})
            continue
        if not label: unresolved.append({'row':i,'cells':c}); continue
        # Page 7 mid-table header for year-end balance-sheet metrics
        if page==7 and table_index==0 and i==12:continue
        rid=f'WLY2025_P{page:03d}_T{table_index:02d}_R{i:03d}'
        values=dict(zip(columns, vals))
        rows.append({'chunk_id':rid,'company':company,'report':report,'report_year':2025,'pdf_page':page,'printed_page':page,'section':section,'subsection':sub,'table_title':title,'table_id':f'WLY2025_P{page:03d}_T{table_index:02d}', 'row_index':len(rows)+1,'indicator':label,'unit':unit,'columns':columns,'values':values,'cells':[label]+vals,'source_row_indices':[i], 'source_pdf_sha256':sha,'extraction_method':'PyMuPDF find_tables().extract() + continuation-row merge','verification':'extracted_from_pdf; selected key figures visually checked against page image','source_pdf_filename':P.name,'source_url':None})
    return rows,unresolved
class Snapshot:
 def __init__(self, rows): self.rows=rows
 def extract(self): return self.rows
p7=[Snapshot(t.extract()) for t in doc[6].find_tables().tables]
p8=[Snapshot(t.extract()) for t in doc[7].find_tables().tables]
allrows=[]; notes=[]
def add(t,page,index,title,section,sub,columns,mapping,unit):
 rows,miss=reconstruct(t,page,index,title,section,sub,columns,mapping,unit)
 allrows.extend(rows);notes.append({'page':page,'table':title,'rows':len(rows),'unresolved':miss})
add(p7[0],7,0,'六、主要会计数据和财务指标',sec,'六、主要会计数据和财务指标',['2025年','2024年','本年比上年增减','2023年'],[3,6,9,12],'元（百分比指标除外）')
add(p7[1],7,1,'八、分季度主要财务指标',sec,'八、分季度主要财务指标',['第一季度','第二季度','第三季度','第四季度'],[3,6,9,12],'元')
add(p8[0],8,0,'八、分季度主要财务指标（续表）',sec,'八、分季度主要财务指标',['第一季度','第二季度','第三季度','第四季度'],[3,4,5,6],'元')
add(p8[1],8,1,'九、非经常性损益项目及金额',sec,'九、非经常性损益项目及金额',['2025年金额','2024年金额','2023年金额','说明'],[3,6,9,14],'元')
# Correct section for year end rows after internal header on page 7
for r in allrows:
 if r['pdf_page']==7 and r['table_id'].endswith('T00') and r['source_row_indices'][0]>12:
  r['columns']=['2025年末','2024年末','本年末比上年末增减','2023年末']
  r['values']=dict(zip(r['columns'],r['cells'][1:]))
# Attach a fully contextualized retrieval text to each row so header and data remain together.
for r in allrows:
 r['retrieval_text'] = (f"公司：{r['company']}；报告：{r['report']}；章节：{r['section']} / {r['subsection']}；"
   f"PDF第{r['pdf_page']}页；表格：{r['table_title']}；指标：{r['indicator']}；"
   + '；'.join(f"{k}：{v}" for k,v in r['values'].items()))
# Ensure PDF genuinely has the line items and digits as printed
q=[r for r in allrows if r['pdf_page']==7 and '归属于上市公司股东的净利润（元）'==r['indicator']]
assert len(q)==1, str([(r['indicator'],r['pdf_page']) for r in allrows])
assert q[0]['values']['2025年']=='8,954,257,202.51'
assert q[0]['values']['2024年']=='31,853,172,533.98'
assert q[0]['values']['本年比上年增减']=='-71.89%'
jsonl=O/'五粮液2025_PDF第7至8页_真实表格行块.jsonl'
with jsonl.open('w',encoding='utf8') as f:
 for r in allrows:f.write(json.dumps(r,ensure_ascii=False)+'\n')
# structured tables searchable: each row carries full header and source
csvpath=O/'五粮液2025_表格行列对照.csv'
with csvpath.open('w',encoding='utf-8-sig',newline='') as f:
 writer=csv.writer(f);writer.writerow(['块ID','公司','章节','子章节','PDF页码','表格名称','指标','列名','对应值'])
 for r in allrows:
  for k,v in r['values'].items():writer.writerow([r['chunk_id'],company,r['section'],r['subsection'],r['pdf_page'],r['table_title'],r['indicator'],k,v])
# html proof
s=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>五粮液2025 PDF 第7—8页真实表格核验</title>', '<style>body{font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif;max-width:1200px;margin:30px auto;color:#203142}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #bbc7d4;padding:8px;text-align:left}th{background:#e7edf4}code{font-size:12px}small{color:#555}h2{margin-top:40px}.flag{color:#a34b00}</style>', '<h1>五粮液2025年年度报告 · 真实PDF行列表格重建</h1>',f'<p>来源：用户提供原始PDF，共{len(doc)}页，SHA-256：<code>{sha}</code></p>', '<p>提取方法：PyMuPDF 的真实表格单元格坐标提取，将跨行指标名称与后续无数值单元格合并；每一数据行均附带公司、章节、PDF物理页码、表格标题、列名与完整数值。</p>','<p class="flag">注意：这是新增PDF解析证据；尚未重新跑旧版10道模型评测，也不能据此宣称整个10家公司知识库均已替换。</p>']
for page,idx,title in [(7,0,'六、主要会计数据和财务指标'),(7,1,'八、分季度主要财务指标'),(8,0,'八、分季度主要财务指标（续表）'),(8,1,'九、非经常性损益项目及金额')]:
 rr=[r for r in allrows if r['pdf_page']==page and r['table_id'].endswith(f'T{idx:02d}')]
 if not rr:continue
 s.append(f'<h2>{html.escape(title)}｜PDF第{page}页</h2><p><small>公司：五粮液｜章节：{sec}｜共{len(rr)}行</small></p>')
 # table first header based on first row; year-end change inside p7 adds header row
 s.append('<table><thead><tr><th>指标／科目</th>'+''.join(f'<th>{html.escape(c)}</th>' for c in rr[0]['columns'])+'</tr></thead><tbody>')
 for r in rr:
  if r['columns']!=rr[0]['columns']:
   s.append('<tr><th>指标／科目</th>'+''.join(f'<th>{html.escape(c)}</th>' for c in r['columns'])+'</tr>')
  s.append('<tr><td>'+html.escape(r['indicator'])+'</td>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r['values'].values())+'</tr>')
 s.append('</tbody></table><small>对应块ID：'+', '.join(r['chunk_id'] for r in rr)+'</small>')
s.append('</html>');(O/'五粮液2025_PDF表格核验页.html').write_text('\n'.join(s),encoding='utf8')
# query evidence, NOT an actual model output
q=q[0]
md=f'''# Q02 新旧切块与可回查出处对照\n\n## 原问题\n五粮液2025年归母净利润及同比增速是多少？\n\n## 旧知识块问题\n旧召回页面常将表格指标名称和数值打散；第7页即便进入召回范围，用户难以逐行检查数值与年度表头之间的对应。\n\n## 新PDF解析知识块（非新模型运行结果）\n- 块ID：`{q['chunk_id']}`\n- 公司：五粮液\n- 报告：宜宾五粮液股份有限公司2025年度报告\n- 章节：第二节 公司简介和主要财务指标 → 六、主要会计数据和财务指标\n- PDF物理页码：7（该PDF印刷页码也为7）\n- 指标：{q['indicator']}\n- 列名—数值：\n  - 2025年：{q['values']['2025年']}元\n  - 2024年：{q['values']['2024年']}元\n  - 本年比上年增减：{q['values']['本年比上年增减']}\n  - 2023年：{q['values']['2023年']}元\n- 提取方式：PyMuPDF实际PDF表格提取，将跨行指标名称合并；数值与PDF第7页原文核对。\n\n## 可基于此知识块组织的回答（仅证据演示，非模型重测）\n五粮液2025年度归属于上市公司股东的净利润为89.54亿元，上年为318.53亿元，同比下降71.89%。依据：五粮液2025年年度报告第二节第7页“六、主要会计数据和财务指标”，块 `{q['chunk_id']}`。\n\n## 未完成与边界\n本次新增的是五粮液原始PDF第7—8页结构化重建产物，并没有重新跑既有10题的问答检索，旧10题实测成绩不变。其余未成功重建的公司仍需要补PDF。\n'''
(O/'Q02_真实表格块引用演示_非模型重测.md').write_text(md,encoding='utf8')
report={'source_pdf':P.name,'pdf_pages':len(doc),'sha256':sha,'pages_rebuilt':[7,8],'tables':4,'table_row_chunks':len(allrows),'section':sec,'Q02_verified_chunk_id':q['chunk_id'],'Q02_exact_values':q['values'],'unresolved_cells':notes,'limitations':['仅重建五粮液第7—8页，并非完整年报','未更改旧知识库和既有评测记录','某些复杂合并单元格需要后续逐页校验']}
(O/'五粮液2025_重建验收.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print('files',len(allrows),'rows',q['chunk_id'])

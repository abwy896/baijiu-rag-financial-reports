# -*- coding: utf-8 -*-
"""安全接入：只从 v5 候选库挑选已核对的 Q03/Q05/Q08 核心行，另补已核对的 Q07 两行。
预览默认不改 data/chunks/all_chunks.jsonl；--apply 需输入 YES 且核对 SHA256。
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'data' / 'chunks' / 'all_chunks.jsonl'
V5 = ROOT / 'data' / 'rebuilt' / 'teacher_v5_targeted' / 'all_chunks.targeted.preview.jsonl'
OUT = ROOT / 'data' / 'rebuilt' / 'teacher_v6_reviewed_only'
PREVIEW = OUT / 'all_chunks.reviewed.preview.jsonl'
MANIFEST = OUT / '安全接入核验报告.json'
QUESTIONS = {
 'Q03': ('山西汾酒','山西汾酒2025年主营业务按产品分类的营业收入构成是什么？'),
 'Q05': ('洋河股份','洋河股份2025年销售费用是多少？与2024年相比如何变化？'),
 'Q07': ('古井贡酒','古井贡酒2025年营业收入和归母净利润分别是多少？'),
 'Q08': ('舍得酒业','舍得酒业2025年白酒业务毛利率是多少？'),
}
# 只准这些来源行进入默认库，其余自动候选行不接入
SELECT = {
 'REBUILT_V5_山西汾酒_P010_ROW001':('山西汾酒','汾酒','37,441,361,212.24'),
 'REBUILT_V5_山西汾酒_P010_ROW002':('山西汾酒','其他酒类','1,151,373,260.88'),
 'REBUILT_V5_舍得酒业_P013_ROW001':('舍得酒业','酒类','3,852,693,747.08'),
 '洋河股份_PDF018_TAB00_ROW001':('洋河股份','销售费用','5,205,631,990.16'),
 '洋河股份_PDF067_PROFIT_CONSOLIDATED_P068_ROW016':('洋河股份','销售费用','5,205,631,990.16'),
}
GUJING_VALUES = [
 ('营业收入（元）','18,831,982,591.24','23,577,928,065.99','-20.13%','20,253,526,598.02'),
 ('归属于上市公司股东的净利润（元）','3,549,108,530.34','5,517,251,073.10','-35.67%','4,589,164,052.80')]

def read_rows(path):
 with Path(path).open('r',encoding='utf-8-sig') as f:
  return [json.loads(s) for s in f if s.strip()]

def write_rows(path,rows):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_name(path.name+'.tmp')
 with tmp.open('w',encoding='utf-8') as f:
  for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 os.replace(tmp,path)

def write_json(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
 return h.hexdigest()

def gujing_rows():
 cols=['项目','2025年','2024年','本年比上年增减','2023年']
 out=[]
 for n,values in enumerate(GUJING_VALUES,1):
  label=values[0];rid=f'Q07_VERIFIED_古井贡酒_P007_ROW{n:03d}'
  text=f'公司：古井贡酒；报告：2025年年度报告；章节：六、主要会计数据和财务指标；PDF物理页：7。\n表格：近三年主要会计数据及指标；单位：元。\n列名：'+ ' | '.join(cols)+'\n数据行：'+ ' | '.join(values)
  out.append({'chunk_id':rid,'company':'古井贡酒','report':'2025年年度报告','page':7,'pdf_page':7,'kind':'pdf_table_row',
   'section':'六、主要会计数据和财务指标','table_title':'近三年主要会计数据及指标','column_names':cols,
   'cells':list(values),'row_index':n,'row_label':label,'text':text,
   'source_url':'https://static.cninfo.com.cn/finalpage/2026-04-29/1225237594.PDF',
   'source_pdf':'古井贡酒_2025年年度报告.pdf','rebuild_tag':'reviewed_only_v6',
   'review_scope':'Q07两个指标的截图数值人工对照；未核验年报其他数据',
   'needs_review':False,'verified_by_human':True,'verification_status':'screenshot_exact_cells_checked'})
 return out

def pick(available):
 byid={str(x.get('chunk_id')):x for x in available}
 out=[]
 for rid,(comp,label,val) in SELECT.items():
  if rid not in byid:raise RuntimeError('v5候选索引缺少核对过的块：'+rid)
  r=byid[rid]
  if r.get('company')!=comp or r.get('row_label')!=label or val not in r.get('cells',[]):
   raise RuntimeError('候选行的公司、行标签或数值不匹配：'+rid)
  if r.get('kind')!='pdf_table_row' or not r.get('source_url') or not r.get('column_names'):
   raise RuntimeError('候选行缺少表格属性/来源：'+rid)
  out.append({**r,'review_scope':'Q03/Q05/Q08截图关键单元格核对，不代表整份报告完整人工核验',
             'rebuild_tag':'reviewed_only_v6','verification_status':'key_values_screenshot_checked'})
 return out + gujing_rows()

def semantic_key(r):
 values=tuple(str(x) for x in r.get('cells',[]))
 return (r.get('company'),r.get('pdf_page',r.get('page')),r.get('row_label'),values)

def verify(path):
 sys.path.insert(0,str(ROOT/'code'))
 from rag_core import load_chunks,HybridIndex,retrieve_question
 chunks=load_chunks(path);index=HybridIndex(chunks,mode='tfidf')
 results={}
 for qid,(company,q) in QUESTIONS.items():
  ev,_,_=retrieve_question(index,q,required_companies=[company],single_top_k=6)
  results[qid]=[{'rank':i,'chunk_id':e.get('chunk_id'),'company':e.get('company'),
                 'page':e.get('page'),'row_label':e.get('row_label'),'kind':e.get('kind'),
                 'preview':str(e.get('text',''))[:300]} for i,e in enumerate(ev,1)]
  print('[检索]',qid,'Top6中本次精选行：',sum(e.get('rebuild_tag')=='reviewed_only_v6' for e in ev),flush=True)
 return results

def run_preview():
 if not DEFAULT.exists() or not V5.exists():raise FileNotFoundError('缺少默认库或v5预览库：请确认06已运行完毕')
 current=read_rows(DEFAULT);candidate=read_rows(V5)
 selected=pick(candidate)
 ids={str(x.get('chunk_id')) for x in current}
 keys={semantic_key(x) for x in current if x.get('kind')=='pdf_table_row'}
 additions=[];skipped=[]
 for row in selected:
  if row['chunk_id'] in ids or semantic_key(row) in keys:
   skipped.append(row['chunk_id']);continue
  additions.append(row);ids.add(row['chunk_id']);keys.add(semantic_key(row))
 merged=current+additions
 write_rows(PREVIEW,merged)
 results=verify(PREVIEW)
 manifest={'mode':'preview_only','original_sha256':sha(DEFAULT),'preview_sha256':sha(PREVIEW),
  'old_count':len(current),'selected_count':len(selected),'new_count':len(additions),
  'merged_count':len(merged),'added_ids':[r['chunk_id'] for r in additions],
  'skipped_already_present':skipped,'explicitly_excluded':'不接入其余v4/v5未经复核的自动候选块；金徽酒更正版未核验，继续保留局限',
  'limitations':['Q08可能仍未进入Top6，需如实记录','Q09/Q10不要求改对，保留既有失败分析',
                '仅接入已核对关键表格行，不代表全部公司和表格均已核验'], 'retrieval':results}
 write_json(MANIFEST,manifest)
 md=['# 仅已核对关键表格行：候选检索记录','',
  f'默认旧块：{len(current)}，本次新增：{len(additions)}，合计：{len(merged)}','',
  '未接入其余v4/v5自动候选块；金徽酒更正版未核验的范围继续保留局限。','']
 for qid,ev in results.items():
  md.extend([f'## {qid}', ''])
  for e in ev:md.append(f"- 排名{e['rank']}：{e['company']} PDF第{e['page']}页 {e['chunk_id']} — {e['preview'][:160].replace(chr(10),' / ')}")
  md.append('')
 (OUT/'候选检索复核.md').write_text('\n'.join(md),encoding='utf-8')
 print('[只生成预览，未修改默认库] 新增',len(additions),'块；报告：',MANIFEST,flush=True)

def run_apply():
 if not MANIFEST.exists() or not PREVIEW.exists():raise FileNotFoundError('请先双击08_SAFE_PREVIEW.bat')
 report=json.loads(MANIFEST.read_text(encoding='utf-8'))
 if report.get('mode')!='preview_only':raise RuntimeError('预览状态异常')
 if sha(DEFAULT)!=report['original_sha256']:raise RuntimeError('默认库已变化，请重新运行08生成预览；未做任何覆盖')
 if sha(PREVIEW)!=report['preview_sha256']:raise RuntimeError('预览文件已变化，未做任何覆盖')
 print('即将安全备份原始默认库并仅新增截图核对的关键行。')
 if input('确认执行请输入 YES：').strip()!='YES':print('已取消');return
 backup=DEFAULT.with_name('all_chunks_before_reviewed_v6_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.jsonl')
 shutil.copy2(DEFAULT,backup)
 tmp=DEFAULT.with_name('all_chunks.reviewed.v6.pending.jsonl')
 try:
  shutil.copy2(PREVIEW,tmp);os.replace(tmp,DEFAULT)
  results=verify(DEFAULT)
 except Exception:
  shutil.copy2(backup,DEFAULT)
  print('验证失败，已尝试从备份恢复默认库：',backup)
  raise
 write_json(OUT/'默认索引检索验收.json',{'backup':str(backup),'sha256':sha(DEFAULT),
  'count':len(read_rows(DEFAULT)),'retrieval':results,'limitations':report['limitations']})
 print('[默认索引安全接入完成] 备份：',backup)
 print('如已开启问答页面，请重启页面进程重新加载知识库')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');args=p.parse_args()
 run_apply() if args.apply else run_preview()

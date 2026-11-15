# -*- coding: utf-8 -*-
"""Q03/Q08 official-PDF anchored table rows, preserve Q07, preview original HybridIndex.
Never modify the default index unless --apply is explicitly invoked after review.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re, sys, subprocess, tempfile, os, shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CODE=ROOT/'code'
sys.path.insert(0,str(CODE))
DEFAULT=ROOT/'data'/'chunks'/'all_chunks.jsonl'
BASE_A=ROOT/'data'/'rebuilt'/'teacher_v4'/'gujing_q07_fix_v41'/'all_chunks.q07_corrected.preview.jsonl'
BASE_B=ROOT/'data'/'rebuilt'/'teacher_v4'/'all_chunks.preview.jsonl'
OUT=ROOT/'data'/'rebuilt'/'teacher_v5_targeted'
PREVIEW=OUT/'all_chunks.targeted.preview.jsonl'
REPORT=OUT/'修复及检索验收报告.json'
QUESTIONS={
 'Q03':'山西汾酒2025年主营业务按产品分类的营业收入构成是什么？',
 'Q05':'洋河股份2025年销售费用是多少？与2024年相比如何变化？',
 'Q07':'古井贡酒2025年营业收入和归母净利润分别是多少？',
 'Q08':'舍得酒业2025年白酒业务毛利率是多少？',
}
SOURCE={
 '山西汾酒':dict(page=10,sha='f824fbe77c0bf415d14b55fe951cc9fa27e326d700535d70e03a4ee009d47e6a',
             url='https://static.cninfo.com.cn/finalpage/2026-04-23/1225156714.PDF',
             section='第三节 管理层讨论与分析 / 2、收入和成本分析 / 主营业务分产品情况',
             table='主营业务分产品情况',
             cols=['分产品','营业收入（元）','营业成本（元）','毛利率（%）','营业收入比上年增减（%）','营业成本比上年增减（%）','毛利率比上年增减（%）'],
             rows=[
               ['汾酒','37,441,361,212.24','9,109,621,768.16','75.67','7.72','14.31','减少1.40个百分点'],
               ['其他酒类','1,151,373,260.88','556,994,824.86','51.62','3.09','4.32','减少0.57个百分点'],
             ]),
 '舍得酒业':dict(page=13,sha='ec55850d5fc0a873bbb285efd23d7b046b993fa9a7da19204ee534f736fec545',
             url='https://static.cninfo.com.cn/finalpage/2026-03-21/1225022707.PDF',
             section='第三节 管理层讨论与分析 / 2、收入和成本分析 / 主营业务分产品情况',
             table='主营业务分产品情况',
             cols=['分产品','营业收入（元）','营业成本（元）','毛利率（%）','营业收入比上年增减（%）','营业成本比上年增减（%）','毛利率比上年增减（%）'],
             rows=[
               ['酒类','3,852,693,747.08','1,245,411,782.09','67.67','-19.55','-10.55','减少3.26个百分点'],
               ['中高档酒','3,119,565,934.35','790,277,587.97','74.67','-23.83','-19.11','减少1.48个百分点'],
               ['普通酒','733,127,812.73','455,134,194.12','37.92','5.75','9.59','减少2.17个百分点'],
             ]),
}

def load(path):
    with Path(path).open('r',encoding='utf-8-sig') as f:
        return [json.loads(x) for x in f if x.strip()]

def save_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def save_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w',encoding='utf-8',newline='\n') as f:
        for x in rows:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    os.replace(tmp,path)

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def n(s):
    return re.sub(r'\s+','',str(s)).replace('－','-').replace('−','-').replace('–','-').replace('，',',')

def _worker():
    import pymupdf
    pdf=Path(sys.argv[2]); pg=int(sys.argv[3]); target=Path(sys.argv[4])
    d=pymupdf.open(str(pdf))
    if not (0<=pg<d.page_count):raise ValueError('页面越界')
    text=d[pg].get_text('text',sort=True)
    d.close()
    target.write_text(text,encoding='utf-8')

def read_page(pdf,page):
    with tempfile.TemporaryDirectory() as td:
        target=Path(td)/'p.txt'
        cmd=[sys.executable,str(Path(__file__).resolve()),'--_worker',str(pdf),str(page-1),str(target)]
        p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,errors='replace',timeout=90)
        if p.returncode!=0 or not target.exists():
            raise RuntimeError(f'PDF第{page}页正文提取失败: exit={p.returncode} {p.stderr[-180:]}')
        return target.read_text(encoding='utf-8')

def build_source_rows():
    built=[];summaries=[]
    for company,s in SOURCE.items():
        candidates=[ROOT/'data'/'pdfs'/(company+'_2025年年度报告'+suffix) for suffix in ('.pdf','.PDF')]
        path=next((x for x in candidates if x.is_file()),candidates[0])
        if not path.exists():
            raise FileNotFoundError(f'{company} 原始PDF缺失：{path}（支持.pdf和.PDF，不要用未核对版本替代）')
        actual=sha(path)
        if actual.lower()!=s['sha']:
            raise RuntimeError(f'{company} PDF SHA256不同，停止：{actual}。请核对年报版本。')
        raw=n(read_page(path,s['page']))
        # Source-content verification. No inference or fabricated missing numeric cells.
        if not ('营业收入' in raw and ('主营业务' in raw or '收入和成本' in raw)):
            raise RuntimeError(f'{company} PDF第{s["page"]}页章节文字未匹配，停止')
        for idx,cells in enumerate(s['rows'],1):
            # The exact values and label must be present in the PDF text layer.
            checks=[cells[0]]+cells[1:6]
            missing=[x for x in checks if n(x) not in raw]
            if missing:
                raise RuntimeError(f'{company} PDF第{s["page"]}页有值未匹配 {cells[0]}：{missing}，不写入候选块')
            # Avoid labeling automated source match as full human verification.
            rid=f'REBUILT_V5_{company}_P{s["page"]:03d}_ROW{idx:03d}'
            text=(f'公司：{company}；报告：2025年年度报告；章节：{s["section"]}；PDF物理页：{s["page"]}。\n'
                  f'表格：{s["table"]}；单位：元、%。\n'
                  '列名：'+' | '.join(s['cols'])+'\n'+'数据行：'+' | '.join(cells))
            built.append(dict(chunk_id=rid,company=company,report='2025年年度报告',
                 page=s['page'],pdf_page=s['page'],section=s['section'],section_method='source_page_verified',
                 table_title=s['table'],table_id=f'{company}_PDF{s["page"]:03d}_PRODUCT',kind='pdf_table_row',
                 column_names=s['cols'],row_index=idx,row_label=cells[0],cells=cells,text=text,
                 source_url=s['url'],source_pdf=path.name,pdf_sha256=actual,
                 extraction_method='original_pdf_text_row_anchor',column_alignment='source_page_match_candidate',
                 numeric_cells_valid=True,rebuild_tag='teacher_feedback_v5',verified_by_human=False,
                 needs_review=True,verification_status='PDF_page_values_matched_needs_human_review'))
        summaries.append({'company':company,'pdf_page':s['page'],'sha256':actual,'rows':len(s['rows']),
                          'status':'source_pdf_values_matched_candidate'})
        print('[PDF核对通过]',company,'第',s['page'],'页',len(s['rows']),'行',flush=True)
    return built,summaries

def safe_filter(base):
    removed=[];ans=[]
    for x in base:
        c=x.get('company');page=x.get('pdf_page',x.get('page'))
        try:page=int(page)
        except Exception:page=-1
        # Suspect rows were observed in the supplied previous review.
        if (c=='古井贡酒' and page in (14,63) and x.get('kind')=='pdf_table_row' and
            x.get('rebuild_tag')=='teacher_feedback_v4'):
            removed.append(x.get('chunk_id'));continue
        if (c=='洋河股份' and x.get('kind')=='pdf_table_row' and
            (not x.get('row_label') or len(str(x.get('row_label'))) > 65)):
            removed.append(x.get('chunk_id'));continue
        ans.append(x)
    return ans,removed

def verify(path):
    from rag_core import load_chunks,HybridIndex,retrieve_question
    cs=load_chunks(path); idx=HybridIndex(cs,mode='tfidf')
    results=[]
    for qid,question in QUESTIONS.items():
        company={'Q03':'山西汾酒','Q05':'洋河股份','Q07':'古井贡酒','Q08':'舍得酒业'}[qid]
        ev,_,_=retrieve_question(idx,question,required_companies=[company],per_company=2,single_top_k=6)
        evidence=[{'rank':i,'chunk_id':x.get('chunk_id'),'company':x.get('company'),
                   'kind':x.get('kind'),'page':x.get('page'),'rebuild_tag':x.get('rebuild_tag'),
                   'row_label':x.get('row_label'),'text':str(x.get('text',''))[:520]}
                  for i,x in enumerate(ev,1)]
        new=[e for e in evidence if e['rebuild_tag'] in ('teacher_feedback_v5','teacher_feedback_v4','yanghe_v3_real_pdf')]
        correct=[e for e in evidence if str(e['chunk_id']).startswith('REBUILT_V5_') or str(e['chunk_id']).startswith('REBUILT_V41_')]
        results.append({'qid':qid,'question':question,'new_hits':len(new),'targeted_hits':len(correct),
                        'evidence':evidence})
        print('[真实检索]',qid,'新块',len(new),'本次针对块',len(correct),flush=True)
    return results

def preview():
    if not DEFAULT.exists():raise FileNotFoundError(f'默认知识库不存在：{DEFAULT}')
    basis=BASE_A if BASE_A.exists() else BASE_B
    if not basis.exists():raise FileNotFoundError('没有v4或v4.1预览库。请保留已运行的01、02、05结果。')
    original=load(DEFAULT);raw=load(basis)
    filtered,removed=safe_filter(raw)
    new,source_check=build_source_rows() # source verified BEFORE any file write
    ids={str(x.get('chunk_id')) for x in filtered}
    new=[x for x in new if x['chunk_id'] not in ids]
    final=filtered+new
    # Require Q07 supplement if the user has run v4.1; otherwise don't silently claim it worked.
    has_q07=any(str(x.get('chunk_id','')).startswith(('REBUILT_V41_古井贡酒_P007','Q07_SUPPLEMENT_古井贡酒_P007'))
                for x in final)
    print('Q07第7页行是否已在候选库：',has_q07,flush=True)
    OUT.mkdir(parents=True,exist_ok=True)
    save_jsonl(PREVIEW,final)
    retrieval=verify(PREVIEW)
    report={'generated_at':datetime.now().isoformat(timespec='seconds'),
        'mode':'preview_no_default_write','source_base':str(basis),'default_index_sha256':sha(DEFAULT),
        'default_index_count':len(original),'preview_count':len(final),
        'new_targeted_rows':len(new),'q07_source_row_present':has_q07,
        'source_checks':source_check,'removed_known_bad_candidate_ids':removed,
        'new_rows_human_verified':False,'retrieval':retrieval,
        'limits':['候选索引仍有未完成人工复核的其它自动提取行',
                  '金徽酒更正版未核验时暂缓接入其新行',
                  '旧十题、Q09/Q10失败分析保留，不声称全部回答正确',
                  '只补充原Q03、Q08涉及的真实PDF行，不代表整份年报全部重建']}
    save_json(REPORT,report)
    md=['# 课程反馈 v5｜定向补块真实检索预览','',
        '用原项目 rag_core.HybridIndex TF-IDF + BM25/RRF，未调用模型回答。','',
        '所有自动重建行仍需人工复核，不自动标注合格。','']
    for r in retrieval:
        md += [f'## {r["qid"]} {r["question"]}',
               f'Top6 新增块={r["new_hits"]}，本次针对块={r["targeted_hits"]}。','']
        for e in r['evidence']:
            md.append(f'- {e["rank"]}. {e["company"]} PDF第{e["page"]}页；{e["chunk_id"]}；{e["kind"]}；{e["text"].replace(chr(10)," / ")[:200]}')
        md.append('')
    (OUT/'Q03_Q05_Q07_Q08_真实召回记录.md').write_text('\n'.join(md),encoding='utf-8')
    print('预览完成（默认索引未修改）：',PREVIEW)
    print('记录：',OUT/'Q03_Q05_Q07_Q08_真实召回记录.md')

def apply():
    if not PREVIEW.exists() or not REPORT.exists():raise FileNotFoundError('请先运行06生成预览并核验')
    meta=json.loads(REPORT.read_text(encoding='utf8'))
    if meta.get('mode')!='preview_no_default_write':raise RuntimeError('非合法预览')
    if sha(DEFAULT)!=meta['default_index_sha256']:
        raise RuntimeError('默认库已变化，停止；请重跑06，避免覆盖其他人修改')
    if not meta.get('q07_source_row_present'):
        raise RuntimeError('Q07补块缺失，请先运行原05_Q07_SAFE_VERIFY.bat')
    # Notice: candidate quality is not equivalent to human review. Explicit confirmation mandatory.
    print('警告：将用已预览的候选库替换默认 all_chunks.jsonl。新增行仍有人工复核标记。')
    confirm=input('确认已对照原PDF核对Q03/Q08表格并接受候选索引其他局限，输入 YES：').strip()
    if confirm!='YES':print('已取消，无修改');return
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    backup=DEFAULT.with_name('all_chunks_before_v5_'+stamp+'.jsonl')
    shutil.copy2(DEFAULT,backup)
    tmp=DEFAULT.with_name('all_chunks.v5.pending.jsonl')
    shutil.copy2(PREVIEW,tmp)
    os.replace(tmp,DEFAULT)
    results=verify(DEFAULT)
    save_json(OUT/'默认索引实测.json',{'backup':str(backup),'default_index_sha256':sha(DEFAULT),
                                   'retrieval':results,'source_preview':str(PREVIEW),'human_review_scope':'user_explicitly_confirmed'})
    print('[默认入口接入完成] 备份：',backup)
    print('若 Streamlit 已开启，请重启应用以重新加载知识库')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true',help='ONLY after manual review; makes backup and changes default index')
    args=parser.parse_args()
    if args.apply:apply()
    else:preview()

if __name__=='__main__':
    try:
        if len(sys.argv)>1 and sys.argv[1]=='--_worker':_worker()
        else:main()
    except Exception as e:
        print('[停止；未直接修改默认知识库]',type(e).__name__,str(e),file=sys.stderr)
        sys.exit(1)

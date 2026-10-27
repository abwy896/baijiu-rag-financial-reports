"""10题真实问答批测：保存实际召回块和实际回答，不自动捏造“回答正确”。"""
import argparse, csv, datetime, html, json, sys, time
from pathlib import Path
from dotenv import load_dotenv
from rag_core import ROOT, CHUNK_PATH, COMPANIES, load_chunks, load_catalog, HybridIndex, retrieve_question, attach_urls, generate_answer
from bootstrap import download_if_needed
from key_config import ensure_api_key

def html_page(q, answer, status, evidence, covered, missing):
    parts=[f'''<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>{html.escape(q['id'])} | RAG真实运行记录</title>
    <style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;max-width:1080px;margin:28px auto;background:#f4f6fa;color:#202c3c}}
    main{{padding:32px;background:white;border-radius:16px;box-shadow:0 6px 30px #dce2e955}}
    h1{{color:#244c69}}.meta{{color:#67788c}}.question{{background:#eaf3f8;padding:20px;border-radius:8px}}
    .answer{{white-space:pre-wrap;line-height:1.7;padding:16px;border-left:4px solid #2d8c80;background:#f4faf8}}
    details{{border:1px solid #d8e0e9;border-radius:8px;margin:12px 0;padding:12px}}
    summary{{font-weight:600;cursor:pointer}}pre{{white-space:pre-wrap;word-wrap:break-word;font-size:13px;line-height:1.6;background:#f8fafc;padding:12px}}a{{color:#116caa}}
    .warn{{color:#9a5212}}.pill{{background:#e3f0eb;border-radius:4px;padding:4px 10px}}
    </style></head><body><main><h1>财报RAG｜{html.escape(q['id'])} 实际运行记录</h1>
    <p class="meta">本页面由evaluate.py从实际运行日志自动生成。不是手工编造的演示图。</p>
    <div class="question"><strong>问题：</strong>{html.escape(q['question'])}</div>
    <h2>① 系统回答</h2><div class="answer">{html.escape(answer)}</div>
    <p class="meta">生成状态：{html.escape(status)}；要求覆盖：{html.escape('、'.join(covered)) or '未指定'}；缺少公司：{html.escape('、'.join(missing)) or '无'}。</p>
    <h2>② 实际召回证据（已全部展开）</h2>''']
    for i,x in enumerate(evidence,1):
        header=f'来源{i}｜{x["company"]}｜{x["report"]}｜PDF第{x["page"]}页｜{x["section"]}'
        url=x.get('source_url') or ''
        link=f'<a target="_blank" href="{html.escape(url,quote=True)}">打开原始PDF ↗</a>' if url.startswith(('https://','http://')) else '<span class="warn">未录入PDF直达链接</span>'
        parts.append(f'<details open><summary>{html.escape(header)}</summary><p class="meta">块ID {html.escape(x["chunk_id"])} | RRF {x["score"]:.5f} | {link}</p><pre>{html.escape(x["text"][:1400])}</pre></details>')
    parts.append('</main></body></html>')
    return '\n'.join(parts)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--mode',choices=('bge','tfidf'),default='bge')
    ap.add_argument('--skip-generation',action='store_true',help='仅测真实检索；无API key时等效')
    ap.add_argument('--pause',type=float,default=0.,help='调用DeepSeek两题之间的等待秒数')
    args=ap.parse_args()
    load_dotenv(ROOT/'.env')
    if not args.skip_generation: ensure_api_key(ROOT, allow_skip=True)
    if not CHUNK_PATH.exists():download_if_needed()
    data=load_chunks(); catalog=load_catalog()
    print(f'读取知识块：{len(data)}；构建{args.mode}向量+BM25索引…',flush=True)
    index=HybridIndex(data,mode=args.mode)
    questions=list(csv.DictReader((ROOT/'data'/'questions.csv').open(encoding='utf-8-sig',newline='')))
    dest=ROOT/'data'/'results'; dest.mkdir(exist_ok=True,parents=True)
    pages=dest/'qa_pages'; pages.mkdir(exist_ok=True)
    records=[]; reviews=[]
    for i,q in enumerate(questions,1):
        required=q['companies'].split('|') if q['scope']=='cross' else [q['companies']]
        evid, comps, missing=retrieve_question(index,q['question'],required_companies=required)
        evid=attach_urls(evid,catalog)
        if args.skip_generation:answer,status='未生成（本轮只评测真实召回）','skip_generation'
        else:
            try:answer,status=generate_answer(q['question'],evid,comps,missing)
            except Exception as e:answer,status=f'API调用失败：{type(e).__name__}: {e}','api_error'
        included=list(dict.fromkeys(x['company'] for x in evid))
        rec={'id':q['id'],'scope':q['scope'],'question':q['question'],'required_companies':comps,
             'evidence_company_names':included,'no_chunks_companies':missing,'generation_status':status,
             'answer':answer,'evidence':evid,'timestamp':datetime.datetime.now().isoformat(timespec='seconds')}
        records.append(rec)
        (pages/f'{q["id"]}.html').write_text(html_page(q,answer,status,evid,comps,missing),encoding='utf-8')
        # 人工判定字段预留空白，不把存在相关块就等同于正确召回
        reviews.append({'题号':q['id'],'类型':q['scope'],'题目':q['question'],'预期公司': '|'.join(comps),
          '实际召回公司':'|'.join(included),'未召回任何块的公司':'|'.join(missing),
          '实际召回明细': '；'.join(f'{v["company"]}/{v["report"]}/PDF页{v["page"]}/{v["section"]}/{v["chunk_id"]}' for v in evid),
          '生成状态':status,'系统实际回答':answer,'参考答案（人工从PDF核对）':'',
          '召回判定（完全/部分/失败）':'','答案判定（正确/部分/错误/不可判）':'',
          '失败原因及改进':'','PDF原文核对页码及URL':'','核验人':'','核验日期':''})
        print(f'{q["id"]}: 召回{len(evid)}块；实际覆盖{len(included)}/{len(comps)}家公司；生成={status}',flush=True)
        if args.pause and i<len(questions):time.sleep(args.pause)
    with (dest/'10题真实运行日志.jsonl').open('w',encoding='utf-8') as f:
        for rec in records:f.write(json.dumps(rec,ensure_ascii=False)+'\n')
    with (dest/'10题人工核验表.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=reviews[0].keys());wr.writeheader();wr.writerows(reviews)
    with (dest/'10题实际召回明细.json').open('w',encoding='utf-8') as f:
        json.dump([{k:v for k,v in r.items() if k!='answer'} for r in records],f,ensure_ascii=False,indent=2)
    print('运行完成！',dest)
    print('打开 data/results/qa_pages/Q01.html 和 Q09.html 查看真实回答及展开来源。')
    print('审阅10题人工核验表.csv后运行：python code/generate_report.py')
if __name__=='__main__':main()

# -*- coding: utf-8 -*-
"""按课程批改补齐实际章节/表格行块，预览并验证默认 RAG 检索；不虚构未解析内容。

运行位置：原项目根目录；只需放在 code 文件夹。
命令：build / preview / verify / apply / status
依赖：pymupdf>=2.1,<2.2、项目原有的 numpy/sklearn 等。
"""
from __future__ import annotations
import argparse, csv, hashlib, html, json, os, re, shutil, sys
from collections import Counter
from datetime import datetime
from pathlib import Path
import table_engine_v4 as E

ROOT = Path(__file__).resolve().parents[1]
PDFDIR = ROOT/'data'/'pdfs'
CATALOG = ROOT/'data'/'source_catalog.csv'
REVIEW = ROOT/'data'/'results'/'10题人工核验表.csv'
QUESTIONS = ROOT/'data'/'questions.csv'
OLD_INDEX = ROOT/'data'/'chunks'/'all_chunks.jsonl'
OUT = ROOT/'data'/'rebuilt'/'teacher_v4'
RESULTS = ROOT/'data'/'results'/'teacher_v4'
TARGETS = ['山西汾酒','洋河股份','古井贡酒','舍得酒业','金徽酒']
TO_BUILD = ['山西汾酒','古井贡酒','舍得酒业','金徽酒']
PREEXISTING_FOUR = ['贵州茅台','泸州老窖','今世缘','口子窖']
PREVIEW = OUT/'all_chunks.preview.jsonl'
MANIFEST = OUT/'预览合并报告.json'
REPORT = OUT/'重建总验收报告.json'


def read_jsonl(path):
    rows=[]
    with Path(path).open('r',encoding='utf-8-sig') as f:
        for ln,s in enumerate(f,1):
            if not s.strip():continue
            try: rows.append(json.loads(s))
            except Exception as exc:raise ValueError(f'{path} 第{ln}行有无效JSON：{exc}') from exc
    return rows


def write_jsonl(path, rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w',encoding='utf-8',newline='\n') as f:
        for x in rows:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    os.replace(tmp,path)


def save_json(path,x):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for buf in iter(lambda:f.read(1024*1024),b''):h.update(buf)
    return h.hexdigest()


def review_page_map():
    if not REVIEW.exists():raise FileNotFoundError(f'找不到原10题真实人工核验表：{REVIEW}')
    found={c:set() for c in E.COMPANIES}
    with REVIEW.open('r',encoding='utf-8-sig',newline='') as f:
        rd=csv.DictReader(f)
        if '实际召回明细' not in (rd.fieldnames or []):
            raise ValueError('核验表缺少“实际召回明细”列，不能猜测物理页码')
        for row in rd:
            detail=str(row.get('实际召回明细') or '')
            for c in found:
                found[c].update(int(p) for p in re.findall(re.escape(c)+r'/2025年年度报告/PDF页(\d+)',detail))
    return {c:sorted(v) for c,v in found.items()}


def catalog():
    if not CATALOG.exists():return {}
    with CATALOG.open('r',encoding='utf-8-sig',newline='') as f:
        return {r.get('company',''):r for r in csv.DictReader(f)}


def pdf_path(company):
    # 不替用户选择或偷偷下载另一种年报版本。
    candidates=[PDFDIR/(company+'_2025年年度报告.pdf'),PDFDIR/(company+'_2025年年度报告.PDF')]
    for path in candidates:
        if path.exists() and path.stat().st_size>10000 and path.open('rb').read(5)==b'%PDF-':
            return path
    return None


def corrected_version_signal(company,path):
    if company!='金徽酒':return 'not_applicable'
    payload,err=E._run_isolated_worker('page-text',[path,0],timeout=60)
    if payload is None:return 'unverifiable_first_page:'+err[:70]
    t=re.sub(r'\s+','',str(payload.get('text','')))
    # 仅把明确写在原始PDF封面上的版本标识作为自动核验信号。
    if re.search(r'(?:2025年(?:度)?年?报告|2025年年度报告)[（(]?更正版',t) or '2025年年度报告（更正版）' in t:
        return 'corrected_label_on_pdf_cover'
    if '更正版' in t[:2500] and ('2025年' in t[:2500]):
        return 'corrected_label_on_pdf_cover'
    return 'unverified_corrected_version'  # 不能默认为官方更正版


def heading(txt,toc_title,prev,adjacent):
    section,method=E.page_heading(txt, prev if adjacent else '', toc_title)
    section=str(section or '未识别（待人工复核）')
    # 检查是否错误把数据单元识别为标题。
    if (re.fullmatch(r'[\d\s,.%+\-−]+',section) or not re.search(r'[\u4e00-\u9fff]',section)
            or re.search(r'\d{1,3}(?:,\d{3})+|\d+\.\d{2,}',section)):
        return '未识别（待人工复核）','unrecognized'
    return section,method


def render_review_html(company,by_page,src):
    esc=html.escape
    out=['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
         '<title>原10题相关PDF页：章节与表格行块复核</title>',
         '<style>body{font:14px/1.65 system-ui,"Microsoft YaHei";max-width:1300px;margin:25px auto;padding:0 18px;color:#1e334b}table{border-collapse:collapse;width:100%;margin:10px 0 24px}th,td{border:1px solid #cbd6e1;padding:7px;vertical-align:top}th{background:#eef3f8;text-align:left}tr:nth-child(even){background:#f9fbfd}.warn{background:#fff4dc;padding:10px}small{color:#58708c}h2{margin-top:34px}</style>',
         f'<h1>{esc(company)}｜原10题真实召回页的PDF重建候选</h1>',
         '<p class="warn">候选行并非人工核验。无法识别的章节及表格会原样记录，不能用来声称全PDF已重建。</p>']
    for pg in by_page:
        p,views=pg['page'],pg['views']
        sec=pg['section']
        out.append(f'<h2>PDF物理第{p}页｜章节：{esc(sec)}</h2>')
        if src:out.append(f'<p><a href="{esc(src,quote=True)}">原年报PDF来源</a></p>')
        out.append(f'<p><small>实际自动生成表格行：{pg["table_rows"]}；表格数：{len(views)}；抽取状态：{esc(pg["status"])}</small></p>')
        if not views:
            out.append('<p class="warn">此页未恢复可用行列表格：仅保留正文；是否原本存在表格请对照PDF检查。</p>')
        for v in views:
            heads=v.get('headers',[]);rr=v.get('rows',[])
            out.append('<table><thead><tr>'+''.join('<th>'+esc(str(x))+'</th>' for x in heads)+'</tr></thead><tbody>')
            for r in rr[:80]:out.append('<tr>'+''.join('<td>'+esc(str(x))+'</td>' for x in r)+'</tr>')
            out.append('</tbody></table>')
    return '\n'.join(out)+'</html>'


def build(companies):
    pages_map=review_page_map();sources=catalog()
    OUT.mkdir(parents=True,exist_ok=True)
    summaries=[]
    for company in companies:
        if company not in TARGETS:
            print('[跳过非目标]',company);continue
        pages=pages_map.get(company,[])
        folder=OUT/'companies'/company;folder.mkdir(parents=True,exist_ok=True)
        p=pdf_path(company)
        base={'company':company,'requested_pages':pages,'source_pdf':str(p) if p else None,
              'source_url':sources.get(company,{}).get('pdf_url',''),
              'correction_url':sources.get(company,{}).get('更正说明URL',''),
              'source_status':'local' if p else 'missing_pdf','pages':[],
              'limitations':['仅重建10题实际召回涉及的PDF物理页，其他页面未覆盖',
                             '自动提取candidate不能视为已人工验证；空白和无法识别字段不推测']}
        if not p or not pages:
            base['status']='missing_pdf_or_recall_pages';base['page_count']=0; summaries.append(base)
            save_json(folder/'重建验收报告.json',base)
            print('[缺失]',company,'PDF或原召回页',flush=True);continue
        version=corrected_version_signal(company,p)
        metadata,err=E._run_isolated_worker('meta',[p],timeout=90)
        if metadata is None:
            base['status']='metadata_failed';base['reason']=err;save_json(folder/'重建验收报告.json',base);summaries.append(base)
            print('[元数据失败]',company,err[:100],flush=True);continue
        count=int(metadata['page_count']);toc=metadata.get('bookmarks') or []
        digest=sha(p);src=base['source_url'];base['pdf_sha256']=digest;base['pdf_page_count']=count
        base['corrected_version_status']=version
        chunks=[];tabrows=[];by_page=[];prev_sec='';prev_p=-5
        for n in pages:
            pg={'page':n,'table_rows':0,'text_chunks':0,'section':'未识别（待人工复核）',
                'section_method':'unrecognized','status':'not_processed','views':[]}
            if n<1 or n>count:
                pg['status']='out_of_pdf_range';by_page.append(pg);continue
            payload,why=E._run_isolated_worker('page-full',[p,n-1],timeout=100)
            fall_back=False
            if payload is None:
                fall_back=True
                payload,text_error=E._run_isolated_worker('page-text',[p,n-1],timeout=100)
                if payload is None:
                    pg['status']='page_text_failed';pg['reason']=text_error or why;by_page.append(pg);continue
            txt=str(payload.get('text') or '')
            toc_title=''
            for ent in toc:
                try:
                    if int(ent[2])<=n:toc_title=str(ent[1])
                except Exception:pass
            sec,method=heading(txt,toc_title,prev_sec,prev_p==n-1)
            prev_sec,prev_p=sec,n
            pg.update(section=sec,section_method=method,status='table_worker_fallback_text' if fall_back else 'parsed')
            if payload.get('table_errors'):pg['table_errors']=payload['table_errors']
            if not txt.strip():pg['status']='empty_text_layer'
            text=txt.strip();i=0;j=0
            while i<len(text):
                end=min(i+850,len(text))
                if end<len(text):
                    k=max(text.rfind('\n',i+550,end),text.rfind('。',i+550,end))
                    if k>i:end=k+1
                part=text[i:end].strip()
                if part:
                    cid=f'REBUILT_V4_{company}_P{n:03d}_T{j:03d}'
                    chunks.append({'chunk_id':cid,'company':company,'report':'2025年年度报告',
                       'page':n,'pdf_page':n,'section':sec,'section_method':method,
                       'kind':'pdf_text','text':f'公司：{company}；章节：{sec}；PDF物理页：{n}\n{part}',
                       'source_url':src,'source_pdf':p.name,'pdf_sha256':digest,
                       'rebuild_scope':'question_recall_pages','rebuild_tag':'teacher_feedback_v4',
                       'needs_review':method=='unrecognized','verified_by_human':False})
                    j+=1
                if end>=len(text):break
                i=max(i+1,end-110)
            pg['text_chunks']=j
            arr,views=E.make_table_rows(company,'2025年年度报告',src,n,sec,method,
                           payload.get('candidates') or [],txt,digest)
            # 不把解析出来的坏数字/未对齐的候选伪装为合格行；仍保存到候选JSONL并标注。
            for k,r in enumerate(arr,1):
                r.update(chunk_id=f'REBUILT_V4_{company}_P{n:03d}_ROW{k:03d}',
                         source_pdf=p.name,rebuild_tag='teacher_feedback_v4',
                         rebuild_scope='question_recall_pages',needs_review=True,
                         verified_by_human=False,verification_status='automatic_unverified')
                if not r.get('section') or r.get('section')=='待识别':r['section']='未识别（待人工复核）'
            chunks.extend(arr);tabrows.extend(arr)
            pg['table_rows']=len(arr);pg['views']=views
            by_page.append(pg)
            print('[重建]',company,'PDF页',n,'正文',j,'表格行',len(arr),'状态',pg['status'],flush=True)
        write_jsonl(folder/'2025重建全量知识块.jsonl',chunks)
        write_jsonl(folder/'2025重建表格行块.jsonl',tabrows)
        (folder/'表格重建核验页.html').write_text(render_review_html(company,by_page,src),encoding='utf-8')
        issues=[]
        for pg in by_page:
            if pg['status'] not in ('parsed','table_worker_fallback_text'):issues.append({'page':pg['page'],'reason':pg['status']})
            if pg['table_rows']==0:issues.append({'page':pg['page'],'reason':'no_table_row_candidate'})
            if pg['section_method']=='unrecognized' or '未识别' in pg['section']:
                issues.append({'page':pg['page'],'reason':'section_unrecognized'})
        base.update({'status':'built_candidates_pending_review','text_chunks':len(chunks)-len(tabrows),
                    'table_row_chunks':len(tabrows),'pages_processed':sum(pg['text_chunks']>0 for pg in by_page),
                    'pdf_page_count':count,'pdf_sha256':digest,'pages':[{k:v for k,v in x.items() if k!='views'} for x in by_page],
                    'issues':issues})
        save_json(folder/'重建验收报告.json',base);summaries.append(base)
        print('[完成]',company,'表格行',len(tabrows),'问题标记',len(issues),flush=True)
    report={'generated_at':datetime.now().isoformat(timespec='seconds'),
            'source':'原10题人工核验表实际召回明细 + 本地原始PDF',
            'companies_expected':len(companies),'companies_with_output':sum(x.get('status')=='built_candidates_pending_review' for x in summaries),
            'per_company':summaries,'note':'候选表格行并非自动通过人工复核；缺失和未识别范围均已记录'}
    save_json(REPORT,report)
    print('报告：',REPORT)


def add_clean(incoming,row,tag,page_map):
    c=row.get('company');p=row.get('pdf_page',row.get('page'))
    try:p=int(p)
    except Exception:return
    if c not in page_map or (p not in page_map[c] and not (c=='洋河股份' and 67<=p<=70 and row.get('extraction_method')=='pdf_vector_grid_words')):
        return
    x=dict(row)
    if not str(x.get('text') or '').strip():return
    if x.get('kind')=='pdf_table_row' and (not x.get('column_names') or not x.get('cells')):return
    if x.get('kind')=='pdf_table_row' and (x.get('numeric_cells_valid') is False
                                           or not E._numeric_cells_are_clean(x.get('cells') or [])):
        return  # 数字格式明确损坏，不放进默认检索候选
    if x.get('kind')=='pdf_table_row' and x.get('column_alignment')=='unverified':
        return  # 列对应明显未通过基本结构判定，保留在HTML和候选文件，不接入索引
    x['page']=p;x['pdf_page']=p
    x['rebuild_tag']=tag;x['verified_by_human']=False
    x['needs_review']=True
    x['verification_status']='automatic_candidate_not_human_verified'
    x['section']=str(x.get('section') or '未识别（待人工复核）')
    # 不在缺失的章节字段中补猜的章节
    if '未识别' in x['section'] and x.get('kind')=='pdf_table_row':return
    incoming.append(x)


def preview():
    if not OLD_INDEX.exists():raise FileNotFoundError(f'找不到原默认知识库：{OLD_INDEX}')
    page_map=review_page_map()
    old=read_jsonl(OLD_INDEX)
    old_sha=sha(OLD_INDEX)
    incoming=[];sources=[];limits=[]
    # 先收集已完成的洋河 v3 候选。它保留第67—70页101行跨页恢复结果。
    v3=ROOT/'data'/'rebuilt_safe_v3'/'2025重建全量知识块.jsonl'
    if v3.exists():
        before=len(incoming)
        v3_rows=read_jsonl(v3)
        yanghe=pdf_path('洋河股份')
        if yanghe and v3_rows and all(r.get('pdf_sha256')==sha(yanghe) for r in v3_rows):
            for row in v3_rows:add_clean(incoming,row,'yanghe_v3_real_pdf',page_map)
        else:
            limits.append('洋河v3块的PDF校验值与当前本地PDF不一致或无法验证，暂不接入')
        sources.append({'dataset':str(v3),'accepted_candidates':len(incoming)-before})
    else:
        limits.append('未找到洋河股份 v3 产物；请先完成既有 v3 修复')
    # 四个新增目标公司：每个只合并本轮真实PDF提取且结构基本可信的候选行和正文。
    summary={}
    for c in TO_BUILD:
        folder=OUT/'companies'/c;rp=folder/'重建验收报告.json';jp=folder/'2025重建全量知识块.jsonl'
        if not (rp.exists() and jp.exists()):
            limits.append(c+'缺少本轮重建产物');continue
        r=json.loads(rp.read_text(encoding='utf-8'))
        summary[c]={'pages_requested':r.get('requested_pages'), 'table_rows':r.get('table_row_chunks'),
                    'issues':r.get('issues',[]),'corrected_version_status':r.get('corrected_version_status')}
        if c=='金徽酒' and r.get('corrected_version_status')!='corrected_label_on_pdf_cover':
            limits.append('金徽酒报告是否为2026年10月更正版尚未确认；暂不接入该公司新块')
            continue
        before=len(incoming)
        for row in read_jsonl(jp):add_clean(incoming,row,'teacher_feedback_v4',page_map)
        sources.append({'dataset':str(jp),'accepted_candidates':len(incoming)-before})
    # 此前真实PDF提取的四家公司：仅选题目相关页，且只追加候选表格行块，旧答题记录不重写。
    old4=ROOT/'data'/'rebuilt'/'2025重建表格行块.jsonl'
    if old4.exists():
        before=len(incoming)
        for row in read_jsonl(old4):
            if row.get('company') in PREEXISTING_FOUR:
                add_clean(incoming,row,'prior_pdf_rebuilt_four',page_map)
        sources.append({'dataset':str(old4),'accepted_candidates':len(incoming)-before})
    else:
        limits.append('此前四家公司自动重建表格行块文件缺失，旧知识库保留不动')
    # 原知识库保持顺序，新增块只追加；与旧块ID重复的不写。
    old_ids={str(x.get('chunk_id','')) for x in old}
    seen=set(old_ids);new=[];duplicates=0
    for x in incoming:
        cid=str(x.get('chunk_id') or '')
        if not cid:
            duplicates+=1;continue
        if cid in seen:
            duplicates+=1;continue
        new.append(x);seen.add(cid)
    write_jsonl(PREVIEW,old+new)
    info={'generated_at':datetime.now().isoformat(timespec='seconds'),
          'old_index_sha256':old_sha,'old_index_count':len(old),'preview_index_count':len(old)+len(new),
          'added_count':len(new),'added_by_company':dict(Counter(x['company'] for x in new)),
          'added_by_kind':dict(Counter(x['kind'] for x in new)),
          'duplicates_skipped':duplicates,'sources':sources,'limits':limits,'target_report_summary':summary,
          'candidate_status':'all new rows unverified; human review required',
          'preview_file':str(PREVIEW),'default_index_not_modified':True}
    save_json(MANIFEST,info)
    print('[预览完成] 原有块',len(old),'新增候选块',len(new),'预览总数',len(old)+len(new))
    print('公司分布：',info['added_by_company']);print('未解决：',limits)
    print('预览文件：',PREVIEW)


def verify(use_default=False):
    index_file=OLD_INDEX if use_default else PREVIEW
    if not index_file.exists():raise FileNotFoundError('没有找到检索知识库，请先执行 preview')
    sys.path.insert(0,str(ROOT/'code'))
    from rag_core import load_chunks,HybridIndex,retrieve_question,attach_urls,load_catalog
    cs=load_chunks(index_file);idx=HybridIndex(cs,mode='tfidf')
    desired={'Q03','Q05','Q07','Q08','Q09','Q10'}
    with QUESTIONS.open('r',encoding='utf-8-sig',newline='') as f:
        questions=[r for r in csv.DictReader(f) if r.get('id') in desired]
    records=[]
    for q in questions:
        companies=[x for x in q.get('companies','').split('|') if x]
        cross=q.get('scope')=='cross'
        ev,req,missing=retrieve_question(idx,q['question'],required_companies=companies,
                                       per_company=2 if cross else 2,single_top_k=6)
        ev=attach_urls(ev,load_catalog())
        evidence=[{k:r.get(k) for k in ('chunk_id','company','page','section','kind','rebuild_tag',
                   'needs_review','verified_by_human','table_title','column_names','cells','text','source_url','score')}
                  for r in ev]
        newhits=[r for r in evidence if r.get('rebuild_tag') in ('teacher_feedback_v4','yanghe_v3_real_pdf','prior_pdf_rebuilt_four')]
        tabhits=[r for r in newhits if r.get('kind')=='pdf_table_row']
        rec={'id':q['id'],'question':q['question'],'requested_companies':req,'missing_companies':missing,
             'total_hits':len(ev),'new_hits':len(newhits),'new_table_hits':len(tabhits),
             'top_k_per_company':2 if cross else 6,'evidence':evidence}
        records.append(rec)
        print('[原检索]',q['id'],'候选新块',len(newhits),'其中表格',len(tabhits),flush=True)
    result={'type':'real_original_HybridIndex_search','not_generated_answers':True,
            'index_path':str(index_file),'index_sha256':sha(index_file),
            'retrieval_mode':'original HybridIndex TF-IDF+BM25/RRF',
            'timestamp':datetime.now().isoformat(timespec='seconds'), 'tests':records,
            'note':'原10题中只选择6题复核，未调用API；“进入索引”与“命中top-k”分别评价。'}
    RESULTS.mkdir(parents=True,exist_ok=True)
    label='默认索引实测' if use_default else '候选索引实测'
    save_json(RESULTS/(label+'.json'),result)
    md=['# 11月反馈补交：默认检索入口预览的真实召回记录','',
        '使用原项目 `rag_core.HybridIndex` 的 TF-IDF+BM25/RRF；读取候选索引，不调用大模型。','',
        '本文件不是重新回答原10题；自动PDF块仍需人工审核。','']
    for x in records:
        md.append(f'## {x["id"]} {x["question"]}')
        md.append(f'召回{ x["total_hits"]}块；本轮新增{ x["new_hits"]}块；新增表格行{ x["new_table_hits"]}块。')
        for i,r in enumerate(x['evidence'],1):
            md.append(f'- 来源{i}：{r.get("company")}，PDF第{r.get("page")}页，{r.get("section")}，kind={r.get("kind")}，新块标记={r.get("rebuild_tag") or "旧块"}，块ID={r.get("chunk_id")}')
            md.append(f'  - 原文片段：{str(r.get("text") or "")[:180].replace(chr(10)," / ")}')
            md.append(f'  - URL：{r.get("source_url") or "未记录"}')
        md.append('')
    md.append('重要：如某题新增表格块命中为0，说明本次只是接入候选索引，尚未证明题目能有效召回新块，不能报告为命中成功。')
    (RESULTS/(label+'.md')).write_text('\n'.join(md),encoding='utf-8')
    print('复核报告：',RESULTS/(label+'.md'))


def apply(confirm):
    if not confirm:raise RuntimeError('必须明确指定 --confirm-reviewed，且先对照HTML与原PDF人工复核')
    if not MANIFEST.exists() or not PREVIEW.exists():raise FileNotFoundError('先运行 preview 和 verify')
    check=RESULTS/'候选索引实测.json'
    if not check.exists():raise FileNotFoundError('尚无候选索引实测记录，请先运行 verify')
    test_result=json.loads(check.read_text(encoding='utf-8'))
    if test_result.get('index_sha256')!=sha(PREVIEW):
        raise RuntimeError('候选索引在测试后发生变化；请重新运行 verify')
    meta=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if sha(OLD_INDEX)!=meta['old_index_sha256']:
        raise RuntimeError('默认知识库在生成预览后发生变化；停止覆盖，请重新 preview 和 verify')
    if meta['added_count']<=0:raise RuntimeError('没有新增候选块，不进行无意义替换')
    # 旧文件永远保留时间戳备份；原索引写入一次且使用临时文件原子替换。
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    backup=OLD_INDEX.with_name('all_chunks_before_teacher_v4_'+stamp+'.jsonl')
    shutil.copy2(OLD_INDEX,backup)
    tmp=OLD_INDEX.with_name('all_chunks.v4.pending.jsonl')
    shutil.copy2(PREVIEW,tmp)
    os.replace(tmp,OLD_INDEX)
    print('[已接入默认入口] 备份：',backup)
    print('默认索引：',OLD_INDEX)
    print('请重启 Streamlit 应用，并重新运行 verify 以检查是否使用最新文件（当前记录基于预览索引）。')


def main():
    ap=argparse.ArgumentParser(description='老师11月10日反馈：目标PDF页重建+默认检索接入（逐阶段且默认不覆盖）')
    sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('build',help='只解析原10题实际召回的PDF页，不覆盖默认索引')
    p.add_argument('--companies',nargs='+',default=TO_BUILD,help='默认山西汾酒、古井贡酒、舍得酒业、金徽酒')
    sub.add_parser('preview',help='生成候选索引，不修改原all_chunks')
    v=sub.add_parser('verify',help='调用原HybridIndex真实检索6题（无API）')
    v.add_argument('--default',action='store_true',help='在apply后验证真正的默认all_chunks')
    q=sub.add_parser('apply',help='核验后备份并替换默认索引')
    q.add_argument('--confirm-reviewed',action='store_true')
    sub.add_parser('status',help='查看已存在的验收与合并报告')
    args=ap.parse_args()
    if args.command=='build':build(args.companies)
    elif args.command=='preview':preview()
    elif args.command=='verify':verify(args.default)
    elif args.command=='apply':apply(args.confirm_reviewed)
    else:
        for p in (REPORT,MANIFEST,RESULTS/'候选索引实测.json',RESULTS/'默认索引实测.json'):
            print(p,'存在' if p.exists() else '尚未生成')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('[操作未完成]',type(exc).__name__,str(exc),file=sys.stderr)
        sys.exit(1)

"""2025 annual report PDF -> traceable page/section/table-row chunks.
Requires PyMuPDF>=2.1,<2.2, requests. No API key required. Never silently fabricates cells.
Text-layer table fallback preserves raw numeric tokens and flags all automatic rows for review.
Standalone: place at project_root/code/rebuild_tables_v2_safe_v2.py.
"""
from __future__ import annotations
import argparse, csv, hashlib, html, json, re, shutil, sys, time, subprocess, tempfile
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PDFDIR=ROOT/'data'/'pdfs'
OUTDIR=ROOT/'data'/'rebuilt_safe_v2'
CATALOG=ROOT/'data'/'source_catalog.csv'
CHUNKFILE=ROOT/'data'/'chunks'/'all_chunks.jsonl'
COMPANIES=['贵州茅台','五粮液','山西汾酒','泸州老窖','洋河股份','今世缘','古井贡酒','舍得酒业','口子窖','金徽酒']
FALLBACK={
 '贵州茅台':'https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-17/600519_20260417_9QS4.pdf',
 '五粮液':'https://static.cninfo.com.cn/finalpage/2026-04-30/1225273091.PDF',
 '泸州老窖':'https://static.cninfo.com.cn/finalpage/2026-04-29/1225240660.PDF',
 '洋河股份':'https://www.chinayanghe.com/static/upload/2026/07/28/202607282530.pdf',
 '今世缘':'https://www.jinshiyuan.com.cn/upload/2026-04/177746868076223400.pdf',
 '口子窖':'https://static.cninfo.com.cn/finalpage/2026-04-23/1225145285.PDF',
}
LABELS=('营业收入','营业总收入','归属于上市公司股东的净利润','归属于母公司所有者的净利润',
        '归属于母公司股东的净利润','经营活动产生的现金流量净额','合同负债','销售费用','毛利率',
        '净利润','总资产','营业成本','主营业务')
# Numeric data such as "4.62% 12.07% ..." must never be treated as a chapter title.
TITLE_PATTERNS=[
 re.compile(r'^第[一二三四五六七八九十0-9]+节\s*[\u4e00-\u9fff][^\n]{0,32}'),
 re.compile(r'^[一二三四五六七八九十]+[、.．]\s*[\u4e00-\u9fff][^\n]{1,35}'),
 re.compile(r'^\(?[一二三四五六七八九十]+\)?[、.．]\s*[\u4e00-\u9fff][^\n]{1,36}'),
 re.compile(r'^\d{1,2}[、.．]\s*[\u4e00-\u9fff][^\n]{1,32}'),
]
RECOGNIZED_TITLES=[
 '主要会计数据和财务指标','近三年主要会计数据和财务指标','主要会计数据','主要财务指标',
 '合并利润表','母公司利润表','合并现金流量表','母公司现金流量表',
 '合并资产负债表','母公司资产负债表','营业收入和营业成本',
 '主营业务分行业','主营业务分产品','主营业务分地区','主营业务分销售模式',
 '按产品档次','收入和成本分析','营业收入、营业成本的分解信息'
]

def norm(s): return re.sub(r'\s+','',str(s or '')).strip()
def clean(s):return re.sub(r'\s+',' ',str(s or '')).strip()
def is_financial_table(rows):
    if not rows or len(rows)<2:return False
    pieces=[' '.join(clean(c) for c in row) for row in rows if row]
    alltxt=' '.join(pieces)
    n_digits=sum(bool(re.search(r'\d[\d,.%\-]{2,}',line)) for line in pieces)
    has_label=any(k in alltxt for k in LABELS)
    has_year=any(y in alltxt for y in ['2025','2024','本期','上期','本年','上年','营业收入','净利润'])
    return (has_label and has_year and n_digits>=1) or (n_digits>=3 and len(rows)>=5 and any(k in alltxt for k in ['收入','费用','资产','利润','现金流量','成本']))

def page_heading(text, previous, toc_title):
    # Prefer actual Chinese chapter headings; reject numeric/percentage rows.
    found=[]
    for raw in text.splitlines()[:150]:
        line=clean(raw)
        if not line or len(line)>64:
            continue
        cjk=len(re.findall(r'[\u4e00-\u9fff]',line))
        if cjk < 2:
            continue
        if re.fullmatch(r'[\d\s.,%+\-−]+',line) or re.match(r'^\d+\.\d',line):
            continue
        if any(t in line for t in RECOGNIZED_TITLES):
            found.append(line)
        elif any(p.match(line) for p in TITLE_PATTERNS):
            found.append(line)
    if found:
        return found[-1], 'page_text'
    if toc_title and len(re.findall(r'[\u4e00-\u9fff]',toc_title)) >= 2:
        return toc_title,'pdf_bookmark'
    return previous if previous else '未识别（待人工复核）', 'previous_page' if previous else 'unrecognized'

def detect_table_name(text, bbox=None, fallback='表格（标题未确认）'):
    # The caption is an exact nearby line from PDF text; avoid invented captions.
    if bbox is not None:
        t=clean(text)
        for x in reversed(t.split('  ')):
            if any(z in x for z in RECOGNIZED_TITLES) and len(x)<100:
                return x
    for ln in reversed(text.splitlines()[-60:]):
        line=clean(ln)
        if any(k in line for k in RECOGNIZED_TITLES) and len(line)<85:
            return line
    return fallback

def schema_rows(raw):
    rows=[]
    for row in raw or []:
        if row is None:continue
        rr=[clean(c) for c in row]
        if any(rr):rows.append(rr)
    if not rows:return []
    cols=max(map(len,rows))
    return [r+['']*(cols-len(r)) for r in rows]

def plausible_header(rows, page_text):
    first=rows[:min(4,len(rows))]
    # Preserve original cells; adding a page-level year label is only a hint, not a rewrite.
    for i,r in enumerate(first):
        s=' '.join(r)
        if any(w in s for w in ['2025','2024','本期','上期','本年','上年','项目','指标','类别','分产品','营业收入']):
            return i
    return 0


_NUM_CELL_RE=re.compile(r'^[−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?$')

def _split_layout_columns(line):
    # PDF text layer usually preserves column gaps as 2+ spaces.
    return [x.strip() for x in re.split(r'\s{2,}',str(line).strip()) if x.strip()]

def _is_numeric_cell(value):
    value=str(value or '').strip().replace('−','-')
    return bool(_NUM_CELL_RE.fullmatch(value))

def _is_year_header(parts):
    years=sum(bool(re.search(r'20\d{2}',x)) for x in parts)
    return years>=2 and len(parts)>=3 and any('年' in x for x in parts)

def _is_label_line(line):
    s=clean(line)
    if not s or not re.search(r'[\u4e00-\u9fff]',s):
        return False
    if re.fullmatch(r'[□☑\s是是否否]+',s):
        return False
    return True

def _label_is_incomplete(label):
    s=str(label or '').strip()
    return bool(s) and s.endswith((
        '股东','现金','净资产','收益','损益','（元/','（','的','产生的','活动','/'
    ))

def _is_label_continuation(label):
    s=str(label or '').strip()
    return s.startswith(('的','股）','股)','流量','净利润','率','）',')'))

def extract_text_layout_tables(page_text):
    """
    Conservative fallback using the PDF's own text layer and column gaps.
    It does not infer missing values: unclear rows are retained with a review flag later.
    """
    lines=str(page_text or '').splitlines()
    header_positions=[]
    for i,line in enumerate(lines):
        parts=_split_layout_columns(line)
        if _is_year_header(parts):
            header_positions.append((i,parts))
    tables=[]
    for hi,(line_i,parts) in enumerate(header_positions):
        end=header_positions[hi+1][0] if hi+1<len(header_positions) else len(lines)
        if parts and parts[0] in ('项目','指标','类别'):
            headers=parts
        else:
            headers=['项目']+parts
        rows=[]
        pending_labels=[]
        last_row=None
        for line in lines[line_i+1:end]:
            cols=_split_layout_columns(line)
            numeric_cells=[x for x in cols if _is_numeric_cell(x)]
            nonnumeric_cells=[x for x in cols if not _is_numeric_cell(x)]
            if len(numeric_cells)>=2:
                inline_label=' '.join(nonnumeric_cells).strip()
                prefix=' '.join(pending_labels).strip()
                pending_labels=[]
                label=' '.join(x for x in (prefix,inline_label) if x).strip()
                if not label:
                    label='行标签未识别（待复核）'
                row=[label]+numeric_cells
                rows.append(row)
                last_row=row
            elif _is_label_line(line):
                label=clean(line)
                if last_row and _label_is_incomplete(last_row[0]) and _is_label_continuation(label):
                    last_row[0]=clean(last_row[0]+' '+label)
                else:
                    pending_labels.append(label)
        candidate_rows=[headers]+rows
        if len(rows)>=1 and is_financial_table(schema_rows(candidate_rows)):
            tables.append({
                'rows':candidate_rows,
                'method':'pymupdf_text_layout',
                'name':'表格标题待复核'
            })
    return tables

def _numeric_cells_are_clean(cells):
    for cell in cells[1:]:
        s=str(cell or '').strip()
        if re.search(r'\d',s) and not _is_numeric_cell(s):
            return False
    return True

def _table_signature(table):
    rows=schema_rows(table.get('rows') or [])
    if not rows:
        return ''
    h=plausible_header(rows,'')
    headers='|'.join(norm(x) for x in rows[h])
    labels='|'.join(norm(r[0]) for r in rows[h+1:h+5] if r)
    return headers+'#'+labels

def make_table_rows(company, report, source_url, page_num, section, sec_method, tables, page_text, fingerprint):
    result=[]; tableviews=[]
    native_tables=[t for t in (tables or []) if is_financial_table(schema_rows(t.get('rows') or []))]
    text_tables=extract_text_layout_tables(page_text)

    # Prefer clean, column-separated text-layer reconstruction when available.
    # Keep additional native tables only when their signatures do not duplicate text-layer tables
    # and their numeric cells are structurally clean.
    selected=list(text_tables)
    text_signatures={_table_signature(t) for t in text_tables}
    for t in native_tables:
        sig=_table_signature(t)
        if sig and sig in text_signatures:
            continue
        raw_rows=schema_rows(t.get('rows') or [])
        h=plausible_header(raw_rows,page_text) if raw_rows else 0
        if raw_rows and h<len(raw_rows) and all(_numeric_cells_are_clean(r) for r in raw_rows[h+1:]):
            selected.append(t)
    if not selected:
        selected=native_tables

    for ti,t in enumerate(selected):
        rows=schema_rows(t['rows'])
        if not is_financial_table(rows):
            continue
        header_i=plausible_header(rows,page_text)
        heads=rows[header_i]
        if len(heads)<2:
            continue

        # Do not label a table with nearby boilerplate. Use a real recognized section title,
        # otherwise preserve an explicit "title pending review" marker.
        if sec_method in ('page_text','pdf_bookmark') and section and not section.startswith('未识别'):
            table_name=section
        else:
            table_name='财务表格（标题待复核）'

        for ri in range(header_i+1,len(rows)):
            cells=rows[ri]
            if not any(cells):
                continue
            numeric=sum(bool(re.search(r'\d',x)) for x in cells[1:])
            if not cells[0] or numeric==0:
                continue
            numeric_clean=_numeric_cells_are_clean(cells)
            relation_valid=(len(heads)==len(cells) and len(heads)>=3 and numeric>=1 and numeric_clean)
            head_line=' | '.join(heads)
            row_line=' | '.join(cells)
            text=(f'公司：{company}；报告：{report}；章节：{section}；PDF物理页：{page_num}。\n'
                  f'表格：{table_name}。\n列名：{head_line}\n数据行：{row_line}')
            rid=f'{company}_PDF{page_num:03d}_TAB{ti:02d}_ROW{ri:03d}'
            result.append({
                'company':company,'report':report,'page':page_num,'pdf_page':page_num,
                'section':section,'section_method':sec_method,'table_title':table_name,
                'table_id':f'{company}_PDF{page_num:03d}_TAB{ti:02d}',
                'column_names':heads,'cells':cells,'row_index':ri,'row_label':cells[0],
                'kind':'pdf_table_row','chunk_id':rid,'text':text,'source_url':source_url,
                'pdf_sha256':fingerprint,'extraction_method':t['method'],
                'column_alignment':'candidate' if relation_valid else 'unverified',
                'numeric_cells_valid':numeric_clean,
                'verification_status':'automatic_candidate_not_human_verified',
                'needs_review':True
            })
        tableviews.append({
            'table_title':table_name,'page':page_num,'headers':heads,'rows':rows[header_i+1:],
            'method':t['method'],'section':section,'source_url':source_url,'company':company
        })
    return result,tableviews


def _worker_meta(pdf_path, output_path):
    """Run all PyMuPDF metadata work in an isolated process."""
    import pymupdf
    doc=pymupdf.open(pdf_path)
    payload={'page_count':doc.page_count,'bookmarks':doc.get_toc(simple=True)}
    doc.close()
    Path(output_path).write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')


def _worker_page(pdf_path, page_index, output_path, mode):
    """Extract one PDF page in a disposable process to contain native crashes."""
    import pymupdf
    doc=pymupdf.open(pdf_path)
    page=doc.load_page(int(page_index))
    txt=page.get_text('text',sort=True)
    candidates=[]
    table_errors=[]
    if mode == 'full':
        for strategy in ('lines_strict','lines','text'):
            try:
                result=page.find_tables(strategy=strategy)
                for tb in result.tables:
                    rows=tb.extract()
                    if not is_financial_table(schema_rows(rows)):continue
                    signature=norm(str(rows))
                    if any(signature==x['signature'] for x in candidates):continue
                    bbox=getattr(tb,'bbox',None)
                    prefix=txt[:int(len(txt)*0.8)]
                    if bbox:
                        try:
                            prefix=page.get_text('text',clip=(0,max(0,bbox[1]-110),page.rect.width,bbox[1]))
                        except Exception as exc:
                            table_errors.append(f'{strategy}:caption:{type(exc).__name__}')
                    name=detect_table_name(prefix,bbox)
                    candidates.append({'rows':rows,'method':'pymupdf_'+strategy,
                                       'name':name,'signature':signature})
                if candidates:break
            except Exception as exc:
                table_errors.append(f'{strategy}:{type(exc).__name__}:{str(exc)[:120]}')
    doc.close()
    payload={'text':txt,'candidates':candidates,'table_errors':table_errors}
    Path(output_path).write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')


def _worker_cli():
    # Internal entry point. Never import PyMuPDF in the supervisor process.
    mode=sys.argv[2]
    if mode=='meta':
        _worker_meta(sys.argv[3],sys.argv[4])
    elif mode in ('page-full','page-text'):
        _worker_page(sys.argv[3],sys.argv[4],sys.argv[5],
                     'full' if mode=='page-full' else 'text')
    else:
        raise SystemExit(f'unknown worker mode: {mode}')


def _run_isolated_worker(mode, args, timeout=120):
    """Return (payload, diagnostic). Non-zero native exit is contained here."""
    with tempfile.TemporaryDirectory(prefix='rag_pdf_worker_') as td:
        out=Path(td)/'result.json'
        cmd=[sys.executable,str(Path(__file__).resolve()),'--_worker',mode,*map(str,args),str(out)]
        try:
            proc=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, f'timeout_after_{timeout}s'
        if proc.returncode != 0 or not out.exists():
            stderr=(proc.stderr or proc.stdout or '').strip().replace('\n',' ')[:240]
            return None, f'worker_exit={proc.returncode}; {stderr}'
        try:
            return json.loads(out.read_text(encoding='utf-8')), ''
        except Exception as exc:
            return None, f'invalid_worker_json:{type(exc).__name__}:{exc}'


def parse_report(pdf_path,company,source_url):
    # All native PDF operations run in child processes. A single bad page
    # cannot terminate the parent or erase chunks from previously completed companies.
    raw=pdf_path.read_bytes()
    fingerprint=hashlib.sha256(raw).hexdigest()
    meta,meta_error=_run_isolated_worker('meta',[pdf_path],timeout=120)
    if meta is None:
        raise RuntimeError(f'PDF元数据读取失败：{meta_error}')
    page_count=int(meta['page_count'])
    bookmarks=meta.get('bookmarks') or []
    allchunks=[];views=[];prev=''
    page_failures=[];table_fallbacks=[];table_errors_by_page=[];empty_text_pages=[]
    script=Path(__file__).resolve()
    for page_i in range(page_count):
        page_num=page_i+1
        payload,err=_run_isolated_worker('page-full',[pdf_path,page_i],timeout=120)
        fallback_record=None
        if payload is None:
            # Retry text extraction without find_tables. The supervisor then tries
            # a conservative text-layout reconstruction from the real page text.
            payload,text_err=_run_isolated_worker('page-text',[pdf_path,page_i],timeout=120)
            if payload is None:
                page_failures.append({'page':page_num,'reason':err,'text_retry':text_err})
                print(f'   [页面失败] PDF第{page_num}页：文本提取也失败',flush=True)
                continue
            fallback_record={'page':page_num,'reason':err,'text_retry':'success',
                             'recovered_by_text_layout':False,'recovered_tables':0,'recovered_rows':0}
            table_fallbacks.append(fallback_record)
            print(f'   [表格提取降级] PDF第{page_num}页；尝试用文本层恢复表格',flush=True)
        txt=payload.get('text','')
        if not txt.strip():empty_text_pages.append(page_num)
        candidates=payload.get('candidates') or []
        if payload.get('table_errors'):
            table_errors_by_page.append({'page':page_num,'errors':payload['table_errors']})
        toc_title=''
        for _,title,pp in bookmarks:
            if pp<=page_num:toc_title=clean(title)
            else:break
        section,sec_method=page_heading(txt,prev,toc_title)
        prev=section
        content=txt.strip(); start=0; j=0
        while start<len(content):
            end=min(start+800,len(content))
            if end<len(content):
                piece=content[start:end]
                stop=max(piece.rfind('\n'),piece.rfind('。'))
                if stop>=560:end=start+stop+1
            piece=content[start:end].strip()
            if piece:
                allchunks.append({'company':company,'report':'2025年年度报告','page':page_num,'pdf_page':page_num,
                    'section':section,'section_method':sec_method,'kind':'pdf_text',
                    'chunk_id':f'{company}_PDF{page_num:03d}_T{j:03d}',
                    'source_url':source_url,'pdf_sha256':fingerprint,
                    'text':f'公司：{company}；章节：{section}；PDF物理页：{page_num}\n{piece}'})
            if end>=len(content):break
            start=max(start+1,end-120);j+=1
        tr,vs=make_table_rows(company,'2025年年度报告',source_url,page_num,
                              section,sec_method,candidates,txt,fingerprint)
        if fallback_record is not None:
            recovered=[v for v in vs if v.get('method')=='pymupdf_text_layout']
            fallback_record['recovered_by_text_layout']=bool(recovered)
            fallback_record['recovered_tables']=len(recovered)
            fallback_record['recovered_rows']=sum(
                1 for r in tr if r.get('extraction_method')=='pymupdf_text_layout'
            )
        allchunks.extend(tr);views.extend(vs)
        if page_num % 10 == 0 or page_num == page_count:
            print(f'   [进度] {company} {page_num}/{page_count}页；正文块{sum(x["kind"]=="pdf_text" for x in allchunks)}；表格行块{sum(x["kind"]=="pdf_table_row" for x in allchunks)}',flush=True)
    return allchunks,views,page_count,page_failures,table_fallbacks,table_errors_by_page,empty_text_pages

def read_catalog():
    if not CATALOG.exists():return {}
    with CATALOG.open(encoding='utf-8-sig',newline='') as f:return {r['company']:r for r in csv.DictReader(f)}

def is_pdf(path):
    try:return path.stat().st_size>10000 and path.open('rb').read(5)==b'%PDF-'
    except (OSError,FileNotFoundError):return False

def obtain_pdf(company, catalog, allow_download):
    path=PDFDIR/(company+'_2025年年度报告.pdf')
    if is_pdf(path):return path,'local'
    if not allow_download:return None,'not_local'
    src=catalog.get(company,{}).get('pdf_url','')
    if not src.lower().split('?')[0].endswith('.pdf'):src=FALLBACK.get(company,'')
    if not src:return None,'manual_required'
    try:
        import requests
        resp=requests.get(src,timeout=75,headers={'User-Agent':'Mozilla/5.0'},stream=True)
        resp.raise_for_status()
        tmp=path.with_suffix('.part');PDFDIR.mkdir(parents=True,exist_ok=True)
        with tmp.open('wb') as f:
            for part in resp.iter_content(65536):
                if part:f.write(part)
        if not is_pdf(tmp):
            tmp.unlink(missing_ok=True)
            return None,'download_not_pdf'
        tmp.replace(path)
        return path,'downloaded'
    except Exception as exc:
        return None,'download_failed:'+str(exc)[:90]

def render_html(views, summaries):
    esc=html.escape
    chunks=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>2025财报表格行列重建核验</title>',
       '<style>body{font:15px/1.6 system-ui,"Microsoft YaHei";margin:30px auto;max-width:1200px;color:#243447}table{border-collapse:collapse;width:100%;margin:14px 0 35px}th,td{border:1px solid #cad5e1;padding:7px 10px;text-align:left;vertical-align:top}th{background:#eff5fa}h2{margin-top:30px;color:#164b72}small{color:#637588}a{color:#125ca2}div.info{background:#eff7f4;padding:15px;border-radius:7px}code{background:#f5f5f5}</style>',
       '<h1>2025年白酒财报：PDF表格重建产物</h1><div class="info">本页面由本地原始PDF实际提取生成；优先使用PDF文本层中的列间空白恢复单元格。每条自动重建行仍是候选结果，必须对照原始PDF人工核验后才能作为准确数据。</div>']
    for summary in summaries:
        company=summary['company']; subset=[v for v in views if v['company']==company]
        chunks.append(f'<h2>{esc(company)} — PDF共{summary.get("pages",summary.get("pages_in_pdf","?"))}页，重建表格{len(subset)}张</h2>')
        for v in subset[:100]:
            chunks.append(f'<h3>{esc(v["table_title"])} · PDF第{v["page"]}页</h3>')
            chunks.append(f'<small>章节：{esc(v["section"])} · 提取：{esc(v["method"])} · <a href="{esc(v["source_url"],quote=True)}">打开原始PDF</a></small>')
            chunks.append('<table><thead><tr>'+''.join(f'<th>{esc(h)}</th>' for h in v['headers'])+'</tr></thead><tbody>')
            for row in v['rows'][:55]:chunks.append('<tr>'+''.join(f'<td>{esc(x)}</td>' for x in row)+'</tr>')
            chunks.append('</tbody></table>')
    chunks.append('</html>')
    return '\n'.join(chunks)


def write_rows(path,items):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        for r in items:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    tmp.replace(path)


def _persist_outputs(output, rows, views, summaries, missing):
    output.mkdir(parents=True,exist_ok=True)
    write_rows(output/'2025重建全量知识块.jsonl',rows)
    write_rows(output/'2025重建表格行块.jsonl',[r for r in rows if r['kind']=='pdf_table_row'])
    (output/'表格重建核验页.html').write_text(render_html(views,summaries),encoding='utf-8')
    report={
        'schema_version':3,
        'generation_note':'逐页隔离子进程解析本地原始PDF；崩溃页单独记录，不补造数据。',
        'companies_expected':len({s['company'] for s in summaries}|{m['company'] for m in missing}),
        'companies_with_output':len(summaries),
        'companies_complete':sum(1 for s in summaries if s.get('status')=='complete'),
        'tables':len(views),
        'table_row_chunks':sum(x['kind']=='pdf_table_row' for x in rows),
        'needs_review_rows':sum(1 for x in rows if x.get('kind')=='pdf_table_row' and x.get('needs_review')),
        'unverified_rows':sum(1 for x in rows if x.get('kind')=='pdf_table_row' and x.get('column_alignment')=='unverified'),
        'summary_by_company':summaries,
        'missing':missing,
        'limitations':[
            '每页由独立子进程处理；底层崩溃不会终止其他页或公司。',
            '若表格提取子进程崩溃，会重试正文提取并记录该页表格缺失。',
            '若正文提取也失败，该页列入page_failures，不生成虚假知识块。',
            'column_alignment=candidate不等于人工核验通过；所有自动行均标记needs_review，必须对照HTML和原始PDF。',
            '文本层重建只在PDF文本层保留列间空白时使用；无法可靠分列时保留原文并标记待复核。',
            '扫描页无OCR时不会生成表格；未识别章节保持未识别，不推测补齐。',
            'PDF物理页码从1计数；不等于印刷页码。'
        ]
    }
    (output/'重建验收报告.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--download',action='store_true',help='Attempt official PDF downloads when PDFs are not present')
    ap.add_argument('--companies',nargs='*',default=COMPANIES)
    ap.add_argument('--merge',action='store_true',help='Merge only after manual review; requires --confirm-reviewed')
    ap.add_argument('--confirm-reviewed',action='store_true',help='Explicit confirmation that HTML and source PDFs were manually checked')
    args=ap.parse_args()
    if args.merge and not args.confirm_reviewed:
        ap.error('--merge 仅在人工核验后使用，必须同时提供 --confirm-reviewed')
    OUTPUT=OUTDIR
    OUTPUT.mkdir(parents=True,exist_ok=True)
    PDFDIR.mkdir(parents=True,exist_ok=True)
    catalog=read_catalog();rows=[];views=[];summaries=[];missing=[]
    for c in args.companies:
        if c not in COMPANIES:
            print('Skipping unknown company',c);continue
        path,status=obtain_pdf(c,catalog,args.download)
        if path is None:
            missing.append({'company':c,'status':status,'expected_file':str(PDFDIR/(c+'_2025年年度报告.pdf'))})
            print('[缺PDF]',c,status,flush=True)
            _persist_outputs(OUTPUT,rows,views,summaries,missing)
            continue
        print('[解析PDF]',c,path.name,flush=True)
        try:
            pieces,tables,page_count,page_failures,table_fallbacks,table_errors,empty_text_pages=parse_report(
                path,c,catalog.get(c,{}).get('pdf_url','') or FALLBACK.get(c,''))
        except Exception as exc:
            missing.append({'company':c,'status':'parse_failed','reason':f'{type(exc).__name__}: {exc}'})
            print('[公司失败]',c,repr(exc),flush=True)
            _persist_outputs(OUTPUT,rows,views,summaries,missing)
            continue
        row_count=sum(x['kind']=='pdf_table_row' for x in pieces)
        text_count=sum(x['kind']=='pdf_text' for x in pieces)
        section_unknown_pages=sorted({
            x['page'] for x in pieces
            if x.get('section_method')=='unrecognized' or str(x.get('section','')).startswith('未识别')
        })
        unverified_rows=sum(
            1 for x in pieces
            if x.get('kind')=='pdf_table_row' and x.get('column_alignment')=='unverified'
        )
        needs_review_rows=sum(
            1 for x in pieces
            if x.get('kind')=='pdf_table_row' and x.get('needs_review')
        )
        for v in tables:v['company']=c
        if pieces:
            rows.extend(pieces)
            views.extend(tables)
        status_complete=(len(page_failures)==0 and len(table_fallbacks)==0 and
                         len(pieces)>=60 and row_count>0 and len(table_errors)==0 and len(empty_text_pages)==0 and
                         len(section_unknown_pages)==0 and unverified_rows==0 and
                         len({x['page'] for x in pieces})<=page_count)
        summary={
            'company':c,'pages_in_pdf':page_count,
            'pages_with_chunks':len({x['page'] for x in pieces}),
            'text_chunks':text_count,'table_row_chunks':row_count,
            'table_count':len(tables),
            'section_unknown':len(section_unknown_pages),
            'section_unknown_pages':section_unknown_pages,
            'unverified_rows':unverified_rows,
            'needs_review_rows':needs_review_rows,
            'quality_status':'automatic_candidates_require_manual_review',
            'pdf_sha256':pieces[0]['pdf_sha256'] if pieces else hashlib.sha256(path.read_bytes()).hexdigest(),
            'source_status':status,'status':'complete' if status_complete else 'partial',
            'page_failures':page_failures,'table_fallbacks':table_fallbacks,
            'table_errors_by_page':table_errors,'empty_text_pages':empty_text_pages
        }
        summaries.append(summary)
        if not status_complete:
            missing.append({'company':c,'status':'partial_needs_review',
                            'page_failures':page_failures,'table_fallbacks':table_fallbacks,
                            'empty_text_pages':empty_text_pages,'table_row_chunks':row_count})
        print(f'   [完成] {c}：正文块{text_count}；表格行块{row_count}；表格{len(tables)}；正文失败页{len(page_failures)}；表格降级页{len(table_fallbacks)}',flush=True)
        # Persist after EACH company, so later failures cannot erase earlier outputs.
        _persist_outputs(OUTPUT,rows,views,summaries,missing)

    report=_persist_outputs(OUTPUT,rows,views,summaries,missing)
    if args.merge:
        mergeable={s['company'] for s in summaries if s.get('status')=='complete'}
        if not mergeable:
            print('[未合并]没有满足完整性条件的公司；原知识库保持不变。')
        elif not CHUNKFILE.exists():
            print('[未合并]缺少旧知识库：',CHUNKFILE)
        else:
            backup=CHUNKFILE.with_name('all_chunks_before_pdf_table_rebuild.jsonl')
            if not backup.exists():shutil.copy2(CHUNKFILE,backup)
            old=[]
            for line in CHUNKFILE.read_text(encoding='utf-8-sig').splitlines():
                if not line.strip():continue
                obj=json.loads(line)
                if obj.get('company') not in mergeable:old.append(obj)
            new_rows=[r for r in rows if r.get('company') in mergeable]
            write_rows(CHUNKFILE,old+new_rows)
            print('[已合并完整公司]',','.join(sorted(mergeable)),'；保留不完整公司的旧数据；备份：',backup)
    print('输出目录：',OUTPUT)
    print('说明：本版本输出到 data\\rebuilt_safe_v2，不覆盖 data\\rebuilt_safe 或旧 all_chunks。')
    print('公司有产物',len(summaries),'/',len(args.companies),
          '；完整公司',report['companies_complete'],
          '；表格行块',report['table_row_chunks'],flush=True)
    if missing:
        print('需复核公司/页面：',','.join(x['company'] for x in missing),flush=True)
    if not rows:
        raise SystemExit('没有生成可用知识块；已输出失败清单，未改动旧知识库。')

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--_worker':
        _worker_cli()
    else:
        raise SystemExit('该文件为内部PDF解析引擎；请运行 code/finish_feedback_v4.py 的 build/preview/verify 指令')

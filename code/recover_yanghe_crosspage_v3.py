"""Recover Yanghe 2025 PDF's two consecutive 3-column profit statements.

Reads the *actual local PDF* using its vector grid and text coordinates, without
calling page.find_tables().  Conservatively repairs PDF physical pages 67--70,
while keeping the previous v2 chunks intact in a NEW output directory.

This is not human verification and does not merge the old RAG index.
Requires: PyMuPDF and the existing data/rebuilt_safe_v2 JSONL outputs.
"""
from __future__ import annotations
import argparse
from collections import Counter
from html import escape
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile

COMPANY = '洋河股份'
REPORT = '2025年年度报告'
PDF_FILENAME = f'{COMPANY}_{REPORT}.pdf'
PDF_PAGES = (67, 68, 69, 70)
TITLE_CONSOLIDATED = '3、合并利润表'
TITLE_PARENT = '4、母公司利润表'
HEADERS = ['项目', '2025年度', '2024年度']
NUMBER = re.compile(r'^[\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?$')


def read_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open('r', encoding='utf-8-sig') as handle:
        for ln, line in enumerate(handle, 1):
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as ex:
                    raise ValueError(f'Invalid JSONL {path} line {ln}: {ex}') from ex
    return out


def write_jsonl(path: Path, objects: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as out:
        for obj in objects:
            out.write(json.dumps(obj, ensure_ascii=False) + '\n')
    tmp.replace(path)


def title_position(page, title: str) -> float | None:
    # A literal string from the actual PDF, not a guessed chapter name.
    matches = page.search_for(title)
    return min((float(rect.y0) for rect in matches), default=None)


def _join_grid_cell(words: list[tuple]) -> str:
    """Read ordered words inside ONE actual PDF vector-grid cell."""
    lines: list[list[tuple]] = []
    for w in sorted(words, key=lambda w: (round(w[1], 1), w[0])):
        if not lines or abs(w[1] - lines[-1][0][1]) > 4.0:
            lines.append([w])
        else:
            lines[-1].append(w)
    line_strings = []
    for row in lines:
        line_strings.append(''.join(str(w[4]) for w in sorted(row, key=lambda w: w[0])).strip())
    return ''.join(line_strings).strip()


def _grid_geometry(page):
    """Find an *existing* three-column grid from the PDF's vector rectangles.

    Do not assume a fixed number of pixels or reconstruct a table where the
    source has no detectable three-column vector boundaries.
    """
    vertical = Counter()
    filled_first_col = []
    for drawing in page.get_drawings():
        for item in drawing.get('items', []):
            if not item or item[0] != 're':
                continue
            rect = item[1]
            if 0.1 < rect.width < 1.5 and rect.height > 7:
                vertical[round((rect.x0 + rect.x1) / 2, 1)] += 1
            if 80 < rect.width < page.rect.width * 0.5 and 8 < rect.height < 65 \
                    and rect.x0 < page.rect.width * 0.28:
                filled_first_col.append(rect)
    xs = sorted(x for x, n in vertical.items() if n >= 8)
    # Cluster positions, preferring more frequent lines in each 1.8pt group.
    groups: list[list[float]] = []
    for x in xs:
        if not groups or x - groups[-1][-1] > 1.8:
            groups.append([x])
        else:
            groups[-1].append(x)
    edges = [max(g, key=lambda x: vertical[x]) for g in groups]
    if len(edges) != 4 or any(b - a < 70 for a, b in zip(edges, edges[1:])):
        return None
    if not (max(edges) - min(edges) > 0.55 * page.rect.width):
        return None
    # First-column grey rectangle matches full cell outline, not text inset.
    bands = set()
    for rect in filled_first_col:
        if abs(rect.x0 - edges[0]) < 2.0 and abs(rect.x1 - edges[1]) < 2.0:
            bands.add((round(rect.y0, 2), round(rect.y1, 2)))
    bands = sorted(bands)
    if len(bands) < 4:
        return None
    return edges, bands


def three_col_rows(page) -> list[dict]:
    geometry = _grid_geometry(page)
    if geometry is None:
        raise RuntimeError(f'PDF physical page {page.number + 1} has no safely detectable 3-column vector grid')
    edges, bands = geometry
    words = page.get_text('words', sort=True)
    output = []
    for y0, y1 in bands:
        cells = []
        for left, right in zip(edges, edges[1:]):
            selected = [w for w in words if left + 0.7 < (w[0] + w[2])/2 < right - 0.7
                        and y0 - 0.15 < (w[1] + w[3])/2 < y1 + 0.15]
            cells.append(_join_grid_cell(selected))
        if not cells[0]:
            continue
        # No concatenation of numbers across grid cells; blank values stay blank.
        if cells != HEADERS and any(v and not NUMBER.fullmatch(v.replace('−', '-')) for v in cells[1:]):
            raise RuntimeError(f'Page {page.number+1}: invalid numeric cell in grid row {cells!r}')
        output.append({'start_y': y0, 'end_y': y1, 'cells': cells})
    return output


def _split_profit_tables(doc):
    pages = {n: doc[n-1] for n in PDF_PAGES}
    first = title_position(pages[67], TITLE_CONSOLIDATED)
    second = title_position(pages[69], TITLE_PARENT)
    if first is None or second is None:
        raise ValueError('Cannot locate both original PDF table titles; refusing to infer table ownership')
    extracted = {n: three_col_rows(page) for n, page in pages.items()}
    # PDF page 67 has the tail of another statement before the consolidated profit table.
    # Page 69 contains the end of consolidated profit and the beginning of the parent profit table.
    consolidated = (
        [(67, r) for r in extracted[67] if r['start_y'] > first]
        + [(68, r) for r in extracted[68]]
        + [(69, r) for r in extracted[69] if r['end_y'] < second]
    )
    parent = (
        [(69, r) for r in extracted[69] if r['start_y'] > second]
        + [(70, r) for r in extracted[70]]
    )
    def validate_header(rows, label):
        if not rows or rows[0][1]['cells'] != HEADERS:
            raise RuntimeError(f'Actual PDF {label} column headers differ from expected; refuse to assume years. Got {rows[0][1]["cells"] if rows else "none"}')
    validate_header(consolidated, TITLE_CONSOLIDATED)
    validate_header(parent, TITLE_PARENT)
    return consolidated[1:], parent[1:]


def build_recovered_chunks(con, par, sha, source_url):
    chunks = []
    logical_tables = []
    for title, identifier, start_page, rows in [
        (TITLE_CONSOLIDATED, 'PROFIT_CONSOLIDATED', 67, con),
        (TITLE_PARENT, 'PROFIT_PARENT', 69, par),
    ]:
        tabid = f'{COMPANY}_PDF{start_page:03d}_{identifier}'
        for index, (page, raw_row) in enumerate(rows, 1):
            cells = raw_row['cells']
            if cells == HEADERS:
                # Keep only the first (real) header; inherited continuation headers are metadata.
                continue
            row_id = f'{tabid}_P{page:03d}_ROW{index:03d}'
            detail = (f'公司：{COMPANY}；报告：{REPORT}；章节：{title}；'
                      f'PDF物理页：{page}；表格：{title}；来源PDF首页：{start_page}。\n'
                      f'列名：{" | ".join(HEADERS)}\n数据行：{" | ".join(cells)}')
            chunks.append({
                'company': COMPANY, 'report': REPORT, 'page': page, 'pdf_page': page,
                'section': title, 'section_method': 'original_pdf_table_title_and_continuation',
                'table_title': title, 'table_id': tabid, 'source_table_start_page': start_page,
                'is_cross_page_continuation': page != start_page,
                'column_names': HEADERS[:], 'cells': cells,
                'row_index': index, 'row_label': cells[0],
                'kind': 'pdf_table_row', 'chunk_id': row_id, 'text': detail,
                'source_url': source_url, 'pdf_sha256': sha,
                'extraction_method': 'pdf_vector_grid_words',
                'column_alignment': 'candidate', 'numeric_cells_valid': True,
                'verification_status': 'automatic_candidate_not_human_verified',
                'needs_review': True,
                'blank_cells_preserved': any(not c for c in cells[1:]),
                'source_pdf': PDF_FILENAME,
            })
        logical_tables.append({'title': title, 'table_id': tabid, 'start_page': start_page,
                               'covered_pages': sorted({p for p,_ in rows}),
                               'data_rows': sum(1 for _,r in rows if r['cells'] != HEADERS)})
    return chunks, logical_tables


def check_expected_real_pdf(chunks):
    lookup = {(c['page'], c['table_title'], c['row_label']): c['cells'][1:]
              for c in chunks}
    checks = [
        (68, TITLE_CONSOLIDATED, '二、营业总成本', ['15,729,399,843.33','19,512,180,569.56']),
        (68, TITLE_CONSOLIDATED, '销售费用', ['5,205,631,990.16','5,516,238,544.79']),
        (68, TITLE_CONSOLIDATED, '利息支出', ['', '']),
        (69, TITLE_CONSOLIDATED, '1.归属于母公司股东的净利润', ['2,206,058,926.68','6,673,388,602.12']),
        (70, TITLE_PARENT, '管理费用', ['820,989,583.94','1,020,972,213.60']),
    ]
    for page, name, row_label, values in checks:
        found = lookup.get((page,name,row_label))
        if found != values:
            raise RuntimeError(f'PDF source check failed: page {page} {name}/{row_label}; '
                               f'expected {values} got {found}. No output written.')
    return [{'pdf_page':p,'table':title,'row':label,'cells':values} for p,title,label,values in checks]


def html_page(rows, logical_tables, unresolved, source_url):
    out = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
           '<title>洋河股份2025跨页利润表核验</title>',
           '<style>body{max-width:1200px;margin:30px auto;font:15px/1.65 system-ui,"Microsoft YaHei";padding:0 20px;color:#203b56}'
           'table{border-collapse:collapse;width:100%;margin:10px 0 25px}th,td{border:1px solid #bbcbd6;padding:8px;vertical-align:top}th{background:#eef4f8;text-align:left}'
           'tr:nth-child(even){background:#f8fafc}small{color:#53667d}h2{margin-top:35px}p.note{background:#f2f5f9;padding:12px}</style>',
           '<h1>洋河股份 2025 年报｜跨页利润表行列重建</h1>',
           '<p class="note">本页由同一份原始 PDF 的矢量表格边界与文字坐标提取。'
           '续页继承原表名和年份，但所有行仍需人工核验，不能视为整份年报已完成重建。'
           f'其他未恢复页：{escape("、".join(map(str,unresolved)))}。</p>']
    for table in logical_tables:
        subset = [r for r in rows if r['table_id']==table['table_id']]
        out.append(f'<h2>{escape(table["title"])}（PDF第{", ".join(map(str, table["covered_pages"]))}页）</h2>')
        if source_url:
            out.append(f'<p><a href="{escape(source_url,quote=True)}">查看原始报告PDF</a> · 候选行 {len(subset)} 条</p>')
        out.append('<table><thead><tr><th>来源 PDF 页</th><th>项目</th><th>2025年度</th><th>2024年度</th><th>状态</th></tr></thead><tbody>')
        for r in subset:
            vals = r['cells']
            out.append('<tr>' + ''.join(f'<td>{escape(str(x))}</td>' for x in
                [r['pdf_page'],*vals,'待人工复核']) + '</tr>')
        out.append('</tbody></table>')
    out.append('</html>')
    return '\n'.join(out)




def worker_extract(pdf: Path, output: Path):
    """Every PDF/native call runs in a separate process, preventing loss on crash."""
    import pymupdf
    with pymupdf.open(pdf) as doc:
        if len(doc) < 70:
            raise RuntimeError('Original PDF has fewer than 70 physical pages')
        consolidated, parent = _split_profit_tables(doc)
    output.write_text(json.dumps({'consolidated': consolidated, 'parent': parent},
                                 ensure_ascii=False), encoding='utf-8')


def isolated_extract(pdf: Path):
    with tempfile.TemporaryDirectory(prefix='rag_yanghe_v3_') as temp:
        out = Path(temp)/'grid_rows.json'
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                 '--_grid_worker', str(pdf), str(out)],
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=120)
        if result.returncode != 0 or not out.is_file():
            raise RuntimeError('PDF vector-word extraction failed in isolated worker '
                               f'(exit {result.returncode}); original v2 remains unchanged; '
                               f'error: {(result.stderr or result.stdout)[-400:]}')
        data = json.loads(out.read_text(encoding='utf-8'))
        return data['consolidated'], data['parent']

def main():
    parser = argparse.ArgumentParser(description='Repair Yanghe 2025 profit statement cross-page table rows in a NEW output folder.')
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.project_root.resolve()
    pdf = root/'data'/'pdfs'/PDF_FILENAME
    olddir = root/'data'/'rebuilt_safe_v2'
    outdir = root/'data'/'rebuilt_safe_v3'
    input_chunks = olddir/'2025重建全量知识块.jsonl'
    prior_report = olddir/'重建验收报告.json'
    if not pdf.is_file() or not input_chunks.is_file() or not prior_report.is_file():
        raise SystemExit('缺少本地PDF或v2成果。需要 data/pdfs/'+PDF_FILENAME+'、'+str(input_chunks)+'、'+str(prior_report))
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    report = json.loads(prior_report.read_text(encoding='utf-8-sig'))
    previous = report.get('summary_by_company') or []
    if len(previous)!=1 or previous[0].get('company') != COMPANY:
        raise SystemExit('v2验收报告不是洋河股份单公司成果；避免错误覆盖，请先核验输入。')
    if sha != previous[0].get('pdf_sha256'):
        raise SystemExit('原始PDF SHA256与v2记录不一致，拒绝把两个不同版本的数据混合。')
    rows = read_jsonl(input_chunks)
    if not rows or any(x.get('company')!=COMPANY for x in rows):
        raise SystemExit('当前v2全量知识块包含其他公司或为空；拒绝误合并。')
    source_url = next((x.get('source_url','') for x in rows if x.get('source_url')), '')
    consolidated, parent = isolated_extract(pdf)
    repaired, tables = build_recovered_chunks(consolidated, parent, sha, source_url)
    checks = check_expected_real_pdf(repaired)
    patched = [x for x in rows if not (x.get('kind')=='pdf_table_row' and x.get('page') in PDF_PAGES)]
    removed_count = len(rows) - len(patched)
    # A full-page continuation has a verifiable parent statement heading.
    # Avoid relabelling pages 67/69 wholesale: they each contain TWO logical statements.
    inherited_text_sections = {68: TITLE_CONSOLIDATED, 70: TITLE_PARENT}
    corrected_text_count = 0
    for item in patched:
        pg = item.get('page')
        if item.get('kind')!='pdf_text' or pg not in inherited_text_sections:
            continue
        title = inherited_text_sections[pg]
        item['original_auto_section'] = item.get('section', '')
        item['section'] = title
        item['section_method'] = 'inherited_original_pdf_statement_title'
        first_line, separator, rest = str(item.get('text','')).partition('\n')
        if separator and 'PDF物理页：' in first_line:
            item['text'] = f'公司：{COMPANY}；章节：{title}；PDF物理页：{pg}\n{rest}'
        corrected_text_count += 1
    patched.extend(repaired)
    # Never insert duplicate chunk IDs.
    ids = [x['chunk_id'] for x in patched]
    if len(ids)!=len(set(ids)):
        raise RuntimeError('Duplicate chunk IDs after repair; refusing to write')
    other_fallbacks = [r['page'] for r in previous[0].get('table_fallbacks', []) if r.get('page') not in (68,70)]
    out_report = {
        'schema_version': 4, 'company': COMPANY, 'report': REPORT,
        'source_pdf': PDF_FILENAME, 'pdf_sha256': sha,
        'derived_from': 'data/rebuilt_safe_v2/2025重建全量知识块.jsonl',
        'method': 'pdf_vector_grid_words; inherited headers only from observed original page 67 and 69',
        'repaired_pdf_pages': list(PDF_PAGES),
        'recovered_native_crash_pages': [68,70],
        'remaining_native_table_fallback_pages': sorted(other_fallbacks),
        'logical_tables': tables,
        'source_assertions_passed': checks,
        'old_table_chunks_replaced_on_pages_67_70': removed_count,
        'text_chunks_section_corrected_on_pages_68_70': corrected_text_count,
        'new_table_rows':len(repaired),
        'result_table_rows':sum(x.get('kind')=='pdf_table_row' for x in patched),
        'result_text_chunks':sum(x.get('kind')=='pdf_text' for x in patched),
        'needs_review_rows':sum(x.get('kind')=='pdf_table_row' and x.get('needs_review', True) for x in patched),
        'status':'partial_needs_manual_review',
        'limitations':[
            '仅用原始PDF真实矢量表格线和文字位置重建67至70页，不改动其他未识别页。',
            '所有自动行是候选结果，仍需对照原始PDF人工核验；空格保留空白，未编造数值。',
            '剩余降级页的复杂宽表需要独立处理，不能称为全报告修复。',
            '本工具不修改旧data/rebuilt_safe_v2、不自动合并默认all_chunks。'
        ]
    }
    outdir.mkdir(parents=True,exist_ok=True)
    write_jsonl(outdir/'2025重建全量知识块.jsonl',patched)
    write_jsonl(outdir/'2025重建表格行块.jsonl',[r for r in patched if r.get('kind')=='pdf_table_row'])
    (outdir/'表格重建核验页.html').write_text(html_page(repaired,tables,sorted(other_fallbacks),source_url),encoding='utf-8')
    (outdir/'重建验收报告.json').write_text(json.dumps(out_report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('真实PDF校验一致:', sha)
    for t in tables:
        print('已重建:',t['title'],'页码',t['covered_pages'],'行数',t['data_rows'])
    print('原候选表格行替换:',removed_count,'新表格行:',len(repaired))
    print('真实数字抽查通过:',len(checks),'项')
    print('原失败页恢复: 68,70；仍未恢复:',','.join(map(str,sorted(other_fallbacks))) or '无')
    print('输出目录:',outdir)
    print('注意: 部分结果仍需人工核验；没有改写旧文件，也没有合并默认检索入口。')


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--_grid_worker':
        worker_extract(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        main()

"""One-time/repeat-safe initialization: original chunks + official PDF reparsing for Moutai and Kouzijiao."""
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CODE=ROOT/'code'
sys.path.insert(0,str(CODE))
from bootstrap import download_if_needed
from repair_knowledge_base import main as repair_main
from rag_core import CHUNK_PATH, COMPANIES

def read_rows():
    rows=[]
    with CHUNK_PATH.open('r',encoding='utf-8-sig') as f:
        for line in f:
            if line.strip():
                try: rows.append(json.loads(line))
                except Exception: pass
    return rows

def canonical(row):
    value=str(row.get('company','') or '')+' '+str(row.get('report','') or '')
    for c in COMPANIES:
        if c in value: return c
    text=str(row.get('text','') or '')[:180]
    for c in COMPANIES:
        if c in text: return c
    return ''

def already_repaired(rows):
    companies={canonical(r) for r in rows}
    has_moutai=any(canonical(r)=='贵州茅台' and '_PDF' in str(r.get('chunk_id','')) for r in rows)
    has_kouzijiao=any(canonical(r)=='口子窖' and '_PDF' in str(r.get('chunk_id','')) for r in rows)
    return all(c in companies for c in COMPANIES) and has_moutai and has_kouzijiao

def main():
    print('[1/3] Checking original knowledge chunks...')
    download_if_needed()
    rows=read_rows()
    if already_repaired(rows):
        print('All 10 companies and reparsed Moutai/Kouzijiao chunks already exist. Skipping rebuild.')
    else:
        print('[2/3] Rebuilding Moutai and adding Kouzijiao from official 2025 annual-report PDFs...')
        repair_main()
    rows=read_rows()
    counts={c:sum(canonical(r)==c for r in rows) for c in COMPANIES}
    print('[3/3] Final company coverage:')
    for c,n in counts.items(): print(f'  {c}: {n:,} chunks')
    missing=[c for c,n in counts.items() if n==0]
    if missing:
        raise SystemExit('Initialization incomplete; missing companies: '+'、'.join(missing))
    print('Initialization complete: 10/10 companies detected.')

if __name__=='__main__': main()

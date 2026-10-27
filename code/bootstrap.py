"""从原公开项目获取真实知识块；下载失败会明确报错，不生成模拟数据。"""
from pathlib import Path
import requests
from rag_core import CHUNK_PATH

URLS = [
    'https://raw.githubusercontent.com/abwy896/baijiu-rag-financial-reports/main/data/chunks/all_chunks.jsonl',
    'https://raw.githubusercontent.com/abwy896/baijiu-rag-financial-reports/master/data/chunks/all_chunks.jsonl',
]

def download_if_needed():
    if CHUNK_PATH.exists() and CHUNK_PATH.stat().st_size > 50000:
        print(f'Found existing knowledge chunks: {CHUNK_PATH} ({CHUNK_PATH.stat().st_size:,} bytes)')
        return CHUNK_PATH
    CHUNK_PATH.parent.mkdir(parents=True, exist_ok=True)
    errors=[]
    headers={'User-Agent':'Mozilla/5.0'}
    for url in URLS:
        try:
            print('Downloading original knowledge chunks from public GitHub repository...')
            response=requests.get(url,headers=headers,timeout=120)
            response.raise_for_status()
            content=response.content
            if len(content)<50000 or not content.lstrip().startswith(b'{'):
                raise RuntimeError('Response is not a valid-looking JSONL knowledge file')
            # Validate first line before writing.
            import json
            json.loads(content.splitlines()[0].decode('utf-8-sig'))
            tmp=CHUNK_PATH.with_suffix('.jsonl.download')
            tmp.write_bytes(content); tmp.replace(CHUNK_PATH)
            print(f'Downloaded {len(content):,} bytes to {CHUNK_PATH}')
            return CHUNK_PATH
        except Exception as e:
            errors.append(f'{url}: {type(e).__name__}: {e}')
    raise RuntimeError('Could not download original knowledge chunks. Check internet access.\n'+'\n'.join(errors))

if __name__ == '__main__':
    download_if_needed()

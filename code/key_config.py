"""Secure local API-key prompt shared by app launcher and evaluator."""
import os
from getpass import getpass
from pathlib import Path
from dotenv import load_dotenv

def ensure_api_key(root: Path, allow_skip=True) -> bool:
    env_file=Path(root)/'.env'
    load_dotenv(env_file)
    if (os.getenv('DEEPSEEK_API_KEY') or '').strip():
        return True
    print('DeepSeek API key is not configured.')
    print('Paste your key and press Enter. The key will NOT appear on screen.')
    try:
        key=getpass('DeepSeek API Key'+(' (press Enter for retrieval-only mode)' if allow_skip else '')+': ').strip()
    except (EOFError, KeyboardInterrupt):
        key=''
    if not key:
        if allow_skip:
            print('No key entered; only retrieval evidence will be available.')
            return False
        raise SystemExit('No API key entered.')
    os.environ['DEEPSEEK_API_KEY']=key
    save=input('Save this key in the local .env file for future launches/tests? (Y/N): ').strip().lower()
    if save=='y':
        existing=[]
        if env_file.exists():
            existing=env_file.read_text(encoding='utf-8').splitlines()
        existing=[line for line in existing if not line.strip().startswith('DEEPSEEK_API_KEY=')]
        existing.append('DEEPSEEK_API_KEY='+key)
        env_file.write_text('\n'.join(existing)+'\n',encoding='utf-8')
        print('Saved locally. .env is excluded by .gitignore; do not upload it.')
    return True

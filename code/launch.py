"""Start Streamlit and securely request a DeepSeek API key if needed."""
import os, sys, subprocess
from pathlib import Path
from dotenv import load_dotenv
from key_config import ensure_api_key

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
ensure_api_key(ROOT, allow_skip=True)
os.chdir(ROOT)
print('Starting Streamlit. Keep this black window open while using the app.')
raise SystemExit(subprocess.call([sys.executable,'-m','streamlit','run',str(ROOT/'code'/'app.py')],cwd=str(ROOT),env=os.environ.copy()))

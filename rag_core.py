"""白酒财报 RAG：可审计的向量 + BM25 混合检索、逐公司取证与来源溯源。"""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

COMPANIES = ["贵州茅台", "五粮液", "山西汾酒", "泸州老窖", "洋河股份", "今世缘", "古井贡酒", "舍得酒业", "口子窖", "金徽酒"]
ROOT = Path(__file__).resolve().parents[1]
CHUNK_PATH = ROOT / "data" / "chunks" / "all_chunks.jsonl"
CACHE_PATH = ROOT / "data" / "chunks" / "dense_bge_cache.npz"


def tokenize(s: str):
    """jieba 优先；缺少依赖时回退中英文字符二元组，保证离线复现。"""
    s = str(s).lower()
    try:
        import jieba
        words = [x.strip() for x in jieba.lcut(s) if x.strip()]
        return words + re.findall(r"[a-z]+|\d+(?:\.\d+)?", s)
    except ImportError:
        han = re.findall(r"[\u4e00-\u9fff]+", s)
        return [ch[i:i+2] for ch in han for i in range(max(1, len(ch)-1))] + re.findall(r"[a-z]+|\d+(?:\.\d+)?", s)


def load_chunks(path=CHUNK_PATH):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"未找到知识库：{path}。请先运行 python code/bootstrap.py")
    out = []
    with path.open(encoding="utf-8-sig") as f:
        for lineno, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except Exception as e:
                raise ValueError(f"第{lineno}行JSON格式有误: {e}") from e
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            comp = str(row.get("company", "") or "").strip()
            if comp not in COMPANIES:
                for c in COMPANIES:
                    if c in comp or c in str(row.get("report", "")):
                        comp = c
                        break
            report = str(row.get("report", "") or "未标注报告").strip()
            section = str(row.get("section", "") or "").strip()
            if section in {"待识别", "未知", "unknown", "None"}:
                section = ""
            if not section:
                section = infer_section(text)
            # 章节不得推断成一个不存在的具体章节。不可确定的明确标识待核对。
            row = {**row, "company": comp or "未知公司", "report": report,
                   "section": section or "未识别（请从PDF重建）",
                   "page": row.get("pdf_page", row.get("page", "未标注")),
                   "text": text,
                   "chunk_id": str(row.get("chunk_id", f"chunk-{lineno:06d}")),
                   "source_url": str(row.get("source_url", "") or "")}
            out.append(row)
    if not out:
        raise ValueError("知识库文件为空，或无有效text字段")
    return out


def infer_section(text: str) -> str:
    """只根据块本身明确出现的章节/表名识别，不无依据地填章节。"""
    s = text[:450]
    for name in ("合并利润表", "母公司利润表", "合并现金流量表", "母公司现金流量表", "合并资产负债表", "母公司资产负债表", "分产品", "分行业", "分地区", "主营业务分行业", "主要会计数据", "主要财务指标"):
        if name in s:
            return name + "（文本内识别）"
    m = re.search(r"第[一二三四五六七八九十\d]+节[^\n]{0,28}", s)
    return (m.group(0).strip() + "（文本内识别）") if m else ""


def load_catalog(path=None):
    import csv
    path = Path(path or ROOT / "data" / "source_catalog.csv")
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {row["company"].strip(): row for row in csv.DictReader(f) if row.get("company")}


def bm25_search_setup(chunks):
    docs = [tokenize(x['text'][:2200]) for x in chunks]
    df = Counter()
    for doc in docs:
        df.update(set(doc))
    lengths = np.array([len(d) for d in docs], dtype=float)
    avgdl = max(1., float(np.mean(lengths)))
    counts = [Counter(x) for x in docs]
    return counts, df, lengths, avgdl


class HybridIndex:
    def __init__(self, chunks, mode='bge', cache_path=None):
        self.chunks = chunks
        self.mode = mode
        self.counts, self.df, self.lengths, self.avgdl = bm25_search_setup(chunks)
        self.n = len(chunks)
        self.companies = {c: np.array([i for i, x in enumerate(chunks) if x['company'] == c], dtype=int) for c in COMPANIES}
        self._vec_model = None
        self._tfidf = None
        self.cache_path = Path(cache_path or CACHE_PATH)
        if mode == 'bge':
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError("缺少 sentence-transformers。请安装 requirements.txt；或在侧栏切换为离线 TF-IDF 模式。") from e
            self._vec_model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
            # 向量缓存仅由同一批文字签名校验，避免误用旧索引
            key = hashlib.sha256(('\n'.join(x['company'] + x['text'] for x in chunks)).encode('utf-8')).hexdigest()
            loaded = False
            if self.cache_path.exists():
                try:
                    data = np.load(self.cache_path, allow_pickle=False)
                    if str(data['key'].item()) == key and len(data['arr']) == len(chunks):
                        self.matrix = data['arr']; loaded = True
                except (ValueError, KeyError, OSError):
                    pass
            if not loaded:
                texts = [x['company'] + ' ' + x['report'] + ' ' + x['section'] + ' ' + x['text'] for x in chunks]
                self.matrix = np.asarray(self._vec_model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=True), dtype=np.float32)
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(self.cache_path, key=np.array(key), arr=self.matrix)
        elif mode == 'tfidf':
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._tfidf = TfidfVectorizer(analyzer='char', ngram_range=(2, 3), max_features=65000, dtype=np.float32)
            self.matrix = self._tfidf.fit_transform(x['company'] + ' ' + x['report'] + ' ' + x['text'] for x in chunks)
        else:
            raise ValueError('mode必须是bge或者tfidf')

    def _bm25(self, query, ids):
        qts = tokenize(query)
        arr = np.zeros(len(ids), dtype=float)
        for qt in qts:
            df = self.df.get(qt, 0)
            if not df:
                continue
            idf = math.log(1. + (self.n - df + .5) / (df + .5))
            for pos, ix in enumerate(ids):
                f = self.counts[ix].get(qt, 0)
                if f:
                    den = f + 1.5 * (1 - .75 + .75 * self.lengths[ix] / self.avgdl)
                    arr[pos] += idf * f * 2.5 / den
        return arr

    def search(self, question, company=None, k=5):
        if company:
            ids = self.companies.get(company, np.array([], dtype=int))
        else:
            ids = np.arange(self.n)
        if not len(ids):
            return []
        if self.mode == 'bge':
            qvec = self._vec_model.encode([question], normalize_embeddings=True)[0]
            sim = self.matrix[ids] @ qvec
        else:
            qvec = self._tfidf.transform([question]); sim = (self.matrix[ids] @ qvec.T).toarray().ravel()
        bm = self._bm25(question, ids)
        # RRF不受两种分数的量纲、极端值影响
        scores = np.zeros(len(ids), dtype=float)
        for rank, pos in enumerate(np.argsort(-sim)):
            scores[pos] += 1.0 / (60 + rank + 1)
        for rank, pos in enumerate(np.argsort(-bm)):
            scores[pos] += 1.0 / (60 + rank + 1)
        order = np.argsort(-scores)[:min(k, len(ids))]
        return [{**self.chunks[int(ids[p])], "score": float(scores[p]),
                 "dense_score": float(sim[p]), "bm25_score": float(bm[p])} for p in order]


def resolve_companies(question, required=None):
    if required:
        return [c for c in required if c in COMPANIES]
    names = [c for c in COMPANIES if c in question]
    full = bool(re.search(r"(10家|十家|全部|所有|全景|各家|每家|行业.*(比较|对比|整体)|前十)", question))
    return COMPANIES[:] if full else names


def retrieve_question(index, question, required_companies=None, single_top_k=6, per_company=2):
    cs = resolve_companies(question, required_companies)
    if len(cs) > 1:
        # 逐公司独立取证，避免简单top-10集中在茅台/五粮液
        evidence = []
        missing = []
        for c in cs:
            xs = index.search(question + ' ' + c, company=c, k=per_company)
            if not xs: missing.append(c)
            evidence.extend(xs)
        return evidence, cs, missing
    if cs:
        evidence = index.search(question, company=cs[0], k=single_top_k)
    else:
        evidence = index.search(question, k=single_top_k)
    return evidence, cs, [c for c in cs if not any(x['company'] == c for x in evidence)]


def attach_urls(evidence, catalog):
    result = []
    for r in evidence:
        p = catalog.get(r['company'], {})
        result.append({**r, 'source_url': p.get('pdf_url') or r.get('source_url', ''), 'source_type': p.get('source_type', '原知识块链接（需核验）')})
    return result


def build_prompt(question, evidence, requested_companies, missing):
    sections = []
    for i, x in enumerate(evidence, 1):
        txt = x['text'][:1150]
        sections.append(f"[来源{i}] 公司:{x['company']}；报告:{x['report']}；PDF物理页码:{x['page']}；章节:{x['section']}；原文:\n{txt}")
    return f'''用户问题：{question}
需要覆盖的公司：{'、'.join(requested_companies) if requested_companies else '未限定'}
未检索到文本块的公司：{'、'.join(missing) if missing else '无'}
以下是系统实际检索到的原始证据：

{chr(10).join(sections)}

请只依据上述证据回答。每个含数字的结论都附[来源N]引用；不得用预训练知识填补空缺。
严格区分：2025本期/2024同期；万元/亿元；营业收入/营业总收入；合并/母公司；归母净利润/净利润。
引用片段没有足够信息时写“证据不足，暂不可核实”，不得由相似公司推断。
跨公司题必须按要求的公司逐家公司列出证据，若某家公司未查到，就逐行标注“未核实”；不要根据少量公司归纳为“全部公司”。
输出结尾增加“证据覆盖：已提供证据的公司X/Y；部分数据可能仍缺少关键表格或正确口径的人工核查”。'''


def generate_answer(question, evidence, companies, missing, key=None, model=None):
    key = key or os.getenv('DEEPSEEK_API_KEY', '').strip()
    model = model or os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')
    if not evidence:
        return '未检索到可用的财报原文，无法回答。', 'no_evidence'
    if not key:
        return '尚未配置 DEEPSEEK_API_KEY：已完成检索，但没有调用语言模型生成答案。请查看下面的真实召回证据。', 'no_api_key'
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'), timeout=65)
    res = client.chat.completions.create(
        model=model, temperature=0,
        messages=[{'role':'system','content':'你是财报取证助手，严格引用，绝不虚构未检索到的财务数据。'},
                  {'role':'user','content':build_prompt(question,evidence,companies,missing)}],
    )
    return res.choices[0].message.content, 'generated'


def describe_data(chunks):
    return {c: sum(x['company'] == c for x in chunks) for c in COMPANIES}

"""课程作业：白酒上市公司财报证据型RAG问答页面。"""
import json
import os
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from rag_core import (ROOT, CHUNK_PATH, COMPANIES, load_chunks, load_catalog, HybridIndex,
                      retrieve_question, attach_urls, generate_answer, describe_data)
from bootstrap import download_if_needed

load_dotenv(ROOT / '.env')
st.set_page_config(page_title='白酒财报｜可回查RAG', page_icon='📚', layout='wide')
st.title('📚 白酒行业上市公司财报 RAG · 可回查版')
st.caption('10家上市公司 · 2025年报 · 混合检索（向量 + BM25/RRF） · 逐公司取证 · 证据与答案分开评价')

if not CHUNK_PATH.exists():
    st.warning('尚未加载原仓库的知识块。点击下方按钮自动下载，不需要重做财报。')
    if st.button('从原GitHub仓库一键读取知识库', type='primary'):
        try:
            download_if_needed(); st.rerun()
        except SystemExit:
            st.error('下载失败。请按README中的手动下载方式放入 data/chunks/all_chunks.jsonl。')
    st.stop()

with st.sidebar:
    st.header('系统配置')
    embmode = st.radio('向量类型', ['BGE 中文语义向量（推荐）', '离线 TF-IDF 向量（兼容模式）'], index=0)
    mode = 'bge' if embmode.startswith('BGE') else 'tfidf'
    st.caption('TF-IDF也能复现实验，但不等同于语义Embedding。正式实验建议选BGE。')
    with st.expander('DeepSeek API状态', expanded=False):
        st.write('✅ 已检测到环境变量' if os.getenv('DEEPSEEK_API_KEY') else '⚠️ 无API key，仅展示真实检索证据')
        st.caption('只从本机.env读取密钥，不会上传仓库。')

@st.cache_data(show_spinner=False)
def cached_chunks(path, stamp):
    return load_chunks(path)

@st.cache_resource(show_spinner='正在构建BM25与向量索引；首次运行将下载BGE模型…')
def cached_index(path, stamp, mode):
    return HybridIndex(load_chunks(path), mode=mode)

chunks = cached_chunks(str(CHUNK_PATH), CHUNK_PATH.stat().st_mtime_ns)
st.success(f'已读取真实知识块 {len(chunks):,} 条；公司覆盖 {sum(v>0 for v in describe_data(chunks).values())}/10')
try:
    index = cached_index(str(CHUNK_PATH), CHUNK_PATH.stat().st_mtime_ns, mode)
except Exception as e:
    st.error('索引初始化失败：'+str(e))
    st.info('可切换左侧“离线TF-IDF向量”，或按README安装完整版依赖。')
    st.stop()

with st.expander('检查知识库是否真正包含10家公司的数据'):
    st.dataframe([{'公司': k, '入库块数': v} for k,v in describe_data(chunks).items()],hide_index=True,use_container_width=True)

catalog = load_catalog()
question = st.text_area('请输入财报问题', value='贵州茅台2025年营业收入和同比增速是多少？', height=80)
run = st.button('检索并回答', type='primary', use_container_width=True)
if run:
    with st.spinner('向量+BM25混合召回，并按公司拆分证据…'):
        evidence, req, missing = retrieve_question(index,question.strip())
        evidence = attach_urls(evidence,catalog)
    with st.spinner('生成受证据约束的答案…'):
        try:
            answer, status = generate_answer(question, evidence, req, missing)
        except Exception as e:
            answer, status = f'DeepSeek调用失败：{type(e).__name__}: {e}。检索原文已成功保存，可先查看来源。', 'api_error'
    st.session_state['last'] = {'question':question,'answer':answer,'status':status,'requested_companies':req,'missing_companies':missing,'evidence':evidence}

if 'last' in st.session_state:
    x=st.session_state['last']
    st.subheader('① 模型回答')
    if x['status'] != 'generated': st.warning('当前状态：'+x['status']+'；不能把这段状态信息当作已答题。')
    st.markdown(x['answer'])
    st.subheader('② 检索证据及原文出处（默认全部展开）')
    st.caption('PDF物理页码从1开始；如果章节显示“未识别”，表明原始知识块无该字段，需依据原PDF重新解析，不能直接把待识别当出处。')
    for n,ev in enumerate(x['evidence'],1):
        with st.expander(f'[来源{n}] {ev["company"]}｜{ev["report"]}｜PDF第{ev["page"]}页｜{ev["section"]}', expanded=True):
            st.caption(f'块ID：{ev["chunk_id"]}｜检索RRF分数：{ev["score"]:.5f}｜向量分数：{ev["dense_score"]:.4f}｜BM25分数：{ev["bm25_score"]:.3f}')
            st.text_area('检索原文（可复制回PDF校对）', ev['text'],height=170,key=f'src_{n}')
            if ev.get('source_url'):
                link_label = '打开年报PDF' if ev.get('source_type') == 'PDF直达' else '打开官方年报/公告来源页'
                st.link_button(link_label, ev['source_url'])
                if ev.get('source_type') != 'PDF直达':
                    st.caption('此链接为官方公告/年报入口页，并非PDF直达链接；请在入口页打开对应的2025年年度报告。')
            else:
                st.caption('⚠️ 暂无可回查来源链接；请核验data/source_catalog.csv。')
    st.subheader('③ 证据覆盖校验')
    if x['requested_companies']:
        st.write('应覆盖公司：' + '、'.join(x['requested_companies']))
        st.write('未找到知识块的公司：'+('、'.join(x['missing_companies']) if x['missing_companies'] else '无（但仍须逐公司人工核对所召回的财务字段）'))
    st.download_button('下载本题真实召回和回答JSON',data=json.dumps(x,ensure_ascii=False,indent=2),file_name='本题真实检索记录.json',mime='application/json')

st.divider()
st.caption('正式补交前：运行“批量测试10题.bat”，审核CSV中的召回/答案判定，再用结果脚本生成一页结论。此页面显示的召回不等于答案已经人工核验。')

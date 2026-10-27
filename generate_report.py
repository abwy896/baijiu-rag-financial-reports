"""从真实检索与人工复核CSV生成一页结论PDF；不能凭空计算正确率。"""
from pathlib import Path
import csv, json, re
from collections import Counter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.lib.enums import TA_LEFT
from rag_core import ROOT

pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
RES=ROOT/'data'/'results'; RES.mkdir(parents=True,exist_ok=True)

def p(s,sty):
    import xml.sax.saxutils as sx
    return Paragraph(sx.escape(str(s or '—')).replace('\n','<br/>'),sty)

def main():
    f=RES/'10题人工核验表.csv'
    if not f.exists():
        print('当前还没有真实运行日志。请先运行 python code/evaluate.py');return
    with f.open(encoding='utf-8-sig',newline='') as h:rows=list(csv.DictReader(h))
    recs=[]
    g=RES/'10题真实运行日志.jsonl'
    if g.exists():
        with g.open(encoding='utf-8') as h:recs=[json.loads(x) for x in h if x.strip()]
    rv=Counter(x['召回判定（完全/部分/失败）'].strip() for x in rows if x['召回判定（完全/部分/失败）'].strip())
    av=Counter(x['答案判定（正确/部分/错误/不可判）'].strip() for x in rows if x['答案判定（正确/部分/错误/不可判）'].strip())
    completed=len([x for x in rows if x['召回判定（完全/部分/失败）'].strip() and x['答案判定（正确/部分/错误/不可判）'].strip()])
    summary=f'共执行{len(recs)}/10题；已人工复核{completed}/10题。召回：完全{rv["完全"]}、部分{rv["部分"]}、失败{rv["失败"]}；回答：正确{av["正确"]}、部分{av["部分"]}、错误{av["错误"]}、不可判{av["不可判"]}。'
    status=Counter(x.get('generation_status','') for x in recs)
    if completed<10 or status.get('generated',0)<10:
        limitation='注意：当前尚未完成10道“模型生成+人工核对”的闭环，统计不是最终准确率；请先补齐再正式提交。'
    else:
        limitation='本统计由真实运行日志与人工回查PDF所得，非推测成绩。'
    fails=[x for x in rows if x['答案判定（正确/部分/错误/不可判）'].strip() in ('错误','部分') and x['失败原因及改进'].strip()]
    successes=[x for x in rows if x['答案判定（正确/部分/错误/不可判）'].strip()=='正确']
    examples=[('成功案例',f'{successes[0]["题号"]}：{successes[0]["题目"][:40]}' if successes else '尚待人工核对并填写成功题号'),
              ('失败案例',f'{fails[0]["题号"]}：{fails[0]["失败原因及改进"][:75]}' if fails else '尚待记录真实翻车题（召回缺失、表格碎片、财务口径混淆或跨公司遗漏）')]
    s=getSampleStyleSheet()
    title=ParagraphStyle('T',parent=s['Normal'],fontName='STSong-Light',fontSize=17,leading=24,textColor=colors.HexColor('#1b3c57'))
    label=ParagraphStyle('L',parent=s['Normal'],fontName='STSong-Light',fontSize=10.6,leading=17,textColor=colors.HexColor('#1b3c57'))
    normal=ParagraphStyle('N',parent=s['Normal'],fontName='STSong-Light',fontSize=9.4,leading=15,spaceAfter=4)
    small=ParagraphStyle('S',parent=s['Normal'],fontName='STSong-Light',fontSize=8.7,leading=13)
    path=RES/'一页结论_由实测生成.pdf'
    doc=SimpleDocTemplate(str(path),pagesize=(595.3,841.9),leftMargin=46,rightMargin=46,topMargin=41,bottomMargin=40)
    story=[p('方向A｜10家白酒上市公司财报 RAG 测试结论',title),Spacer(1,6),
         p('材料：10家白酒上市公司2025年年度报告｜问题：8道单公司、2道跨公司｜技术：中文向量检索+BM25/RRF+DeepSeek',normal),
         Spacer(1,9),p('一、真实测试概况',label),p(summary,normal),p(limitation,small),
         Spacer(1,10),p('二、典型表现与失败复盘',label)]
    for key,val in examples:
        story.extend([p(key+'：',normal),p(val,small)])
    story.extend([Spacer(1,10),p('三、为何有的题适合 RAG、有的题容易翻车',label),
          p('单家公司、明确年份及财务字段的事实检索，若原PDF表格和标签完整，通常较容易取得可回查证据。跨10家公司回答须逐家检索；单次Top-k可能遗漏公司，表格被切碎会丢失“合并/母公司”和单位。是否真正答对，以逐题PDF原文复核为准。',normal),
          Spacer(1,7),p('四、已经实施与仍需核验的改进',label),
          p('使用逐公司独立混合检索、RRF排序、PDF物理页码、章节标记及可见原文链接；保留原问题、真实召回、真实回答和人工评定字段。若旧数据没有章节或直达PDF链接，明确标为未核验，不伪造出处；可用PDF重建脚本补齐。',normal),
          Spacer(1,7),p('一句话结论',label),
          p('同一批持续更新的上市公司财报，要求精确数字与原文出处的局部事实问答更适合RAG；跨公司全景题需要逐公司取证、统一会计口径并人工复核，不能只依靠通用Top-k检索。',normal),
          Spacer(1,10),p('复核材料：data/results/10题真实运行日志.jsonl、10题人工核验表.csv、qa_pages/Q01—Q10.html；原PDF不随仓库公开上传。',small)])
    doc.build(story)
    print('已生成：',path)
    print('人工复核完成:',completed,'/10；',limitation)
if __name__=='__main__':main()

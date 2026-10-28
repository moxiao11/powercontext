"""Optional document build: pip install reportlab pypdf; python scripts/technical-pdf.py.

Set TIDE_PDF_FONT to a Chinese TTF if Windows SimHei is unavailable.
The web application does not require Python or these PDF dependencies.
"""
import os
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
FONT = Path(os.environ.get('TIDE_PDF_FONT', 'C:/Windows/Fonts/simhei.ttf'))
if not FONT.is_file():
    raise SystemExit('Set TIDE_PDF_FONT to a Chinese TTF font file')
pdfmetrics.registerFont(TTFont('TideCN', str(FONT)))
purple = colors.HexColor('#7561CB')
ink = colors.HexColor('#20273C')
muted = colors.HexColor('#626D84')
body = ParagraphStyle('body', fontName='TideCN', fontSize=9.0, leading=13.0,
                      textColor=ink, wordWrap='CJK', spaceAfter=7, alignment=TA_LEFT)
small = ParagraphStyle('small', parent=body, fontSize=7.5, leading=10.5, textColor=muted)
heading = ParagraphStyle('heading', parent=body, fontSize=10.3, leading=14,
                         textColor=purple, spaceBefore=4, spaceAfter=4)
title = ParagraphStyle('title', parent=body, fontSize=22, leading=27, spaceAfter=3)
table_body = ParagraphStyle('table', parent=body, fontSize=8.0, leading=10.5, spaceAfter=0)
story = []

def p(text, style=body):
    story.append(Paragraph(text, style))

def section(label, text):
    p(label, heading)
    p(text)

p('潮汐 TIDE', title)
p('seekdb × 阶跃星辰 | 浏览器本地知识库 | 一页技术说明 | 2026-10-28', small)
story.append(Spacer(1, 7))
section('01 模型与量化',
        '公开模型 Xenova/bge-small-zh-v1.5，源自 BAAI；固定版本 '
        '75c43b069aac4d136ba6bc1122f995fedcfd2781。使用上游 FP32、FP16、INT8 ONNX 图，'
        'INT8 为 QInt8 / per-channel / reduce_range；不训练模型，下载时校验 SHA-256。'
        'CLS pooling + L2 归一化，512 维、最多 256 tokens；查询添加 BGE 中文检索前缀。'
        'FP16 / INT8 权重压缩比为 1.997× / 3.950×；计入相同 tokenizer/config，'
        '完整包大小为 95.402 / 48.047 / 24.561 MB，压缩比为 1.986× / 3.884×。')
section('02 端侧运行与降级',
        'Transformers.js 3.8.1 在持久化 Web Worker 中计算文档与查询 embedding。'
        '自动模式显式选择 device:webgpu、dtype:fp16，并检查 adapter 与 shader-f16；'
        '不可用或初始化失败时切换 device:wasm、dtype:q8（单线程）。界面显示实际后端与降级原因。'
        '模型和 ORT 文件本机提供，关闭远程模型加载，Node 禁止 embedding 推理，无云端推理 API。')
section('03 seekdb、增量与状态',
        'seekdb-js 1.4.0 连接本地 seekdb 1.4.0，Docker 镜像锁定 digest。每库独立集合保存正文、'
        '向量、文档 ID、标题、来源与片段序号，使用 cosine HNSW 与 IK smart 全文索引。'
        'hybridSearch 调用数据库 DBMS_HYBRID_SEARCH，两路各召回 30，数据库 RRF(60) 返回 Top K，'
        '应用保留数据库次序。32 条批量 upsert 后同步刷新索引；刷新成功更新版本，未刷新时拒绝检索。'
        '集合注册与版本状态也存于 seekdb，全局串行队列避免 SDK 会话交叉。'
        '180 字符分块、重叠 24，稳定 SHA-256 去重；切库清空结果并忽略旧请求。')
section('04 实测与优化',
        'Windows / i7-14650HX / 16GB，默认 GPU 适配器未指定独显；固定内置 Chromium（UA Chrome/156.0.0.0）。'
        '16 文档、12 条人工分级查询，6 配置各重复 3 次，共 18 轮、216 个后续查询样本，失败 0。'
        '表中均为中位数；MB 为十进制 ONNX 权重大小，查询延迟不含模型加载及首次数据库请求。')
rows = [
    ['配置 / 推理批次', '权重 MB', '吞吐 块/s', 'seekdb ms', '端到端 ms', 'Recall@5 / nDCG@5'],
    ['FP32 / WASM / 1', '94.852', '15.78', '4.89', '44.08', '.8889 / .9589'],
    ['INT8 / WASM / 8', '24.011', '19.90', '5.19', '37.44', '.9306 / .9644'],
    ['FP32 / WebGPU / 1', '94.852', '90.42', '4.68', '22.58', '.8889 / .9589'],
    ['FP16 / WebGPU / 8', '47.497', '366.85', '5.56', '27.31', '.9306 / .9644'],
]
table = Table([[Paragraph(escape(cell), table_body) for cell in row] for row in rows],
              colWidths=[116, 51, 60, 61, 62, 177 - 7], hAlign='LEFT')
table.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EEEAF9')),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7F8FC')]),
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ('LINEBELOW', (0, 0), (-1, 0), 0.4, colors.HexColor('#DAD3EE')),
]))
story.append(table)
story.append(Spacer(1, 7))
p('FP16/WebGPU 文档吞吐组合提升 4.06×，查询端到端延迟从 22.58 增至 27.31 ms。'
  'INT8/WASM 批次消融：1 → 8 时吞吐 16.29 → 19.90（+22.2%）；逐条写入/刷新累计刷新 '
  '9722 ms，批量统一刷新为 517 ms。组合提升不能单独归因于量化。量化后本集 Recall +4.17 个百分点、'
  'nDCG +.0055，小样本不代表普遍改善。每组首轮清模型 Cache Storage，后两轮复用；HTTP 磁盘缓存不清除。')
section('05 验收与复现',
        '独立 Chrome 156.0.8078.73、Edge 156.0.4314.50，可见窗口与 headless 各 6/6 通过：'
        'WebGPU 优先、禁用 GPU 后页面/Worker 均无 adapter 并自动 WASM、FP16 文件加载失败后自动 WASM；'
        '均完成真实导入、刷新、检索、原文、去重、增量与集合隔离。未测试驱动崩溃或执行中设备丢失。'
        '启动：npm ci → npm run db:up → npm run models:download → npm run build → npm start；'
        '打开 127.0.0.1:8788，性能实验室运行评测，npm run test:browsers 执行补测。')
p('原始计时、首次/后续加载与质量标注：reports/browser-benchmark.json、reports/BENCHMARK.md；'
  '降级证据：reports/native-browser/。模型：'
  '<link href="https://huggingface.co/Xenova/bge-small-zh-v1.5">huggingface.co/Xenova/bge-small-zh-v1.5</link>；'
  'SDK：<link href="https://github.com/oceanbase/seekdb-js">github.com/oceanbase/seekdb-js</link>。'
  '依赖、详细启动步骤、模型获取与量化来源见 README.md；编辑版见 docs/TECHNICAL.md。', small)

out = ROOT / 'docs' / 'TECHNICAL.pdf'
document = SimpleDocTemplate(str(out), pagesize=A4, rightMargin=35, leftMargin=35,
                             topMargin=28, bottomMargin=27, title='潮汐 TIDE - 一页技术说明',
                             author='TIDE', pageCompression=1)
document.build(story)
reader = PdfReader(out)
if len(reader.pages) != 1:
    raise RuntimeError(f'Expected one page, got {len(reader.pages)}')
text = reader.pages[0].extract_text()
for phrase in ['512', '3.950', '366.85', '6/6', 'TECHNICAL.md']:
    assert phrase in text, phrase
print(f'Created and verified one page: {out}')

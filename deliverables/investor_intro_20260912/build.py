from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'AI_Douyin_项目融资介绍.pdf'
pdfmetrics.registerFont(TTFont('YH','C:/Windows/Fonts/msyh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('YHB','C:/Windows/Fonts/msyhbd.ttc',subfontIndex=0))
W,H=595.276,841.89
NAVY='#11283D'; GOLD='#AE8950'; INK='#25384A'; MUTED='#6B7783'; PALE='#F1F4F6'
c=canvas.Canvas(str(OUT),pagesize=(W,H))
c.setTitle('AI Douyin 项目融资介绍'); c.setAuthor('AI Douyin')
transcript=[]
def box(x,y,w,h,color):
 c.setFillColor(HexColor(color));c.rect(x,H-y-h,w,h,fill=1,stroke=0)
def text(s,x,y,size=11,color=INK,bold=False):
 c.setFillColor(HexColor(color));c.setFont('YHB' if bold else 'YH',size);c.drawString(x,H-y-size,s)
def para(s,x,y,w=491,size=11,color=INK,leading=19,bold=False):
 st=ParagraphStyle('body',fontName='YHB' if bold else 'YH',fontSize=size,leading=leading,textColor=HexColor(color),wordWrap='CJK')
 p=Paragraph(escape(s),st);_,h=p.wrap(w,600);p.drawOn(c,x,H-y-h)
 return y+h
def base(n,kicker,title,sub):
 box(0,0,W,7,NAVY);text('AI DOUYIN',52,30,10,NAVY,True);text('投资人项目介绍',420,30,9,MUTED)
 text(kicker,52,84,10,GOLD,True);text(title,52,110,27,NAVY,True)
 para(sub,52,157,size=11,color=MUTED,leading=18)
 text('AI Douyin  ·  2026年9月',52,796,8,MUTED);text(f'{n:02d} / 06',491,796,8,MUTED)
 transcript.extend(['',f'# {title}',sub])
def section(title,body,y):
 text(title,52,y,14,NAVY,True); end=para(body,52,y+28)
 transcript.extend([f'## {title}',body]);return end+27
def card(label,body,y,h=88):
 box(52,y,491,h,PALE);box(52,y,3,h,GOLD);text(label,69,y+14,12,NAVY,True);para(body,69,y+39,457,10.5,leading=17)
 transcript.extend([label,body])

base(1,'AI APPLICATION PLATFORM','AI Douyin 项目融资介绍','面向专业内容团队的多模态 AI 内容生产与运营平台')
text('让 AI 贯穿内容生产',52,239,32,NAVY,True)
text('让经验沉淀为业务资产',52,286,32,NAVY,True)
para('我们将多模态内容理解、语言模型创作与图像视频生成接入同一业务流程，围绕账号策略连接内容研究、创作、制作审核与运营反馈，推动 AI 能力转化为可持续的内容交付。',52,356,size=12,leading=22)
card('产品定位','以多模型分工支撑专业创作，以审核与版本管理控制交付过程，以账号反馈持续优化内容判断。',456,92)
card('当前进展','已具备内容研究、选题脚本与运营复盘基础；分阶段创作、逐镜视频生成及审核衔接基础可用，持续验证流程与交付稳定性。',563,94)
para('投资价值：将 AI 应用工程与领域经验，沉淀为内容团队持续使用的生产运营系统。',52,694,size=12,color=NAVY,leading=21,bold=True)
transcript.extend(['让 AI 贯穿内容生产，让经验沉淀为业务资产','我们将多模态内容理解、语言模型创作与图像视频生成接入同一业务流程，围绕账号策略连接内容研究、创作、制作审核与运营反馈。'])
c.showPage()

base(2,'CUSTOMER & VALUE','从持续运营的实际需求切入','优先服务有专业内容要求、持续更新需求和明确审核责任的团队。')
y=section('将 AI 效率转化为完整交付能力','内容团队的投入横跨调研、选题、写稿、制作、返修与复盘。产品将不同 AI 能力嵌入这些环节，并保持上下游内容一致，目标是降低一次合格交付的总投入，使有效的创作与运营方法能够复用。',222)
y=section('法律与专业服务  提升专业内容表达效率','项目已有法律领域账号策略。拟面向专业服务团队，以 AI 辅助话题研究、叙事设计和脚本创作，结合事实核验与专业审核，将复杂议题转化为更易理解的内容，支持律所等客户持续建立专业信任。',y)
y=section('小说与故事化内容  支持连续创作','项目已有小说领域策略。拟围绕授权内容，以 AI 支持故事提炼、长短稿协同、分镜设计和视频生成，验证连续创作与返修效率。保留剧情来源和授权范围，使创作产物可以追溯与复用。',y)
card('商业切入假设','先围绕单一垂直场景做出可复用的交付流程，再扩展到同类账号和团队；用付费试点验证需求强度。',y+1,97)
c.showPage()

base(3,'PRODUCT & READINESS','AI 贯穿研究到交付的全流程','围绕账号目标组织模型任务，保留每一阶段的依据、版本与审核结果。')
rows=[('01  内容理解与机会判断','结合关键帧理解、语音转写与内容指标，辅助分析主题、叙事方式及账号相关性，形成选题依据。','现有基础'),('02  智能创作与审批','语言模型分阶段生成故事、人物与道具状态、摄影设计；通过审核后绑定剧本，支持定点修订。','基础可用／流程验证'),('03  生成与审核','已支持锁定剧本、逐镜生成、已审尾帧衔接及抽帧与声画审核，持续验证质量与交付稳定性。','基础可用／流程验证'),('04  发布与运营反馈','支持已审视频的人工发布与作品指标、评论同步；关联账号和脚本版本，为后续内容判断提供反馈。','现有基础')]
y=222
for title,body,status in rows:
 box(52,y,491,100,PALE);text(title,68,y+13,13,NAVY,True);text(status,385,y+16,9,GOLD,True);para(body,68,y+43,455,10.5,leading=18)
 transcript.extend([title,status,body]);y+=113
para('交付机制：关键节点保留人工确认，画面与声音需实际审核。分阶段创作的网页自动编排仍在完善；完整流程的稳定性、交付成本与客户使用效果将通过持续验证确认。',52,689,size=10,color=MUTED,leading=18)
transcript.append('关键节点保留人工确认，画面与声音需实际审核。分阶段创作的网页自动编排仍在完善；完整流程的稳定性、交付成本与客户使用效果持续验证。')
c.showPage()

base(4,'AI CAPABILITIES & ADVANTAGE','多模型协同与可控生成','核心能力在于将模型输出组织为有依据、可审核、可衔接的业务产物。')
y=section('多模态理解  建立有依据的创作输入','结合视觉模型对关键帧的理解、语音识别对对白的转写，以及标题、标签和表现指标，提取主题、开场吸引点与表达方式。分析结果与账号策略关联，帮助创作建立在具体内容依据之上。',222)
y=section('分阶段推理  将创意转化为执行方案','语言模型按故事、动作对白、状态和摄影分工生成；程序校验结构、绑定已审内容，定点修订保留原有版本。图像与视频模型据此执行镜头，逐段通过审核后再衔接，降低上下游语义偏移风险。',y)
y=section('反馈驱动优化  积累可复用的领域经验','将内容来源、脚本版本、生成回执、失败原因与运营反馈关联，支持复盘选题和表达策略。反馈用于后续策略与执行调整，专业判断和声画质量由实际审核把关。',y)
card('应用层竞争优势的积累方向','持续沉淀领域策略、经审核的表达结构、镜头约束与失败修订经验。模型能力、流程规则与业务反馈的协同效果，将通过合格交付成本和客户持续使用验证。',y,110)
c.showPage()

base(5,'BUSINESS MODEL','从付费试点走向持续订阅','以下为拟验证的商业路径，定价和收入规模由试点结果确定。')
y=section('以团队订阅形成基础收入','拟围绕账号数量、团队协作、AI 创作工作流与资产管理提供订阅服务。以统一的内容依据、版本和审核记录服务持续创作，客户价值由节省的总工时、交付质量及内容资产复用衡量。',222)
y=section('以实施与按量服务覆盖差异化需求','早期可提供账号策略配置、流程搭建与培训服务；模型生成等变动成本拟单独计量或设置清晰额度。合同范围与计费边界应让客户能够预估预算。',y)
text('先验证四个经营指标',52,y,14,NAVY,True)
metrics=[('交付效率','从需求确认到审核通过的总工时'),('质量成本','首轮通过率、返修次数与返修投入'),('客户价值','付费转化、持续使用与续约意愿'),('单位经济','收入扣除模型、交付和支持成本后的贡献')]
yy=y+33
for a,b in metrics:
 box(52,yy,491,42,PALE);text(a,67,yy+11,10.5,NAVY,True);text(b,157,yy+12,10,MUTED);yy+=47
para('核算口径：生成成本应包含失败尝试，人工成本应包含审核与返修。以相近题材、时长和质量要求的人工流程作对照，避免将单次调用费用等同于成片成本。',52,yy+15,size=10,color=MUTED,leading=18)
transcript.extend(['先验证四个经营指标']+[a+'：'+b for a,b in metrics])
c.showPage()

base(6,'CAPITAL & MILESTONES','让融资对应可验收的进展','资金投入优先支持质量稳定、产品可交付和商业需求验证。')
phases=[('阶段一  建立质量与成本基线','完成代表性题材的端到端验证，记录合格交付时间、人工审核投入、生成消耗与失败原因，明确哪些内容可以稳定交付。'),('阶段二  完成垂直客户试点','围绕一个优先领域开展付费试点，把研发工具整理为客户可用流程，验证部署、培训、支持成本与持续付费意愿。'),('阶段三  推进可复制的交付','在试点质量和经营指标达到约定标准后，完善协作、计费与服务机制，将已验证流程推广到同类团队。')]
y=221
for title,body in phases:y=section(title,body,y)
card('资金用途与合作方向','拟投入多模型工作流工程、生成质量评估、内容资产管理与垂直客户试点。期待与具备内容产业经验、客户资源或 AI 产品商业化能力的投资伙伴合作。',y-2,106)
para('尽调交流可围绕产品流程演示、脚本与审核记录、生成回执、版本追溯及运营复盘机制展开。融资金额、估值与具体预算将在明确试点范围和资源计划后协商。',52,y+124,size=10.5,leading=18)
para('能力依据：项目当前能力说明、账号内容机会架构、剧本双稿流程、视频制作流程及制作看板代码。状态梳理截至2026年9月12日；商业路径与阶段安排为拟议方案。',52,740,size=8,color=MUTED,leading=13)
transcript.extend(['融资金额、估值与具体预算将在明确试点范围和资源计划后协商。','能力依据：docs/CURRENT_CAPABILITIES.md；docs/ACCOUNT_CONTENT_OPPORTUNITY_ARCHITECTURE.md；docs/SCRIPT_PAIR_WORKFLOW.md；docs/SCRIPT_VIDEO_RUN.md；src/web/video_production_dashboard.py。'])
c.save()
(ROOT/'项目介绍_可编辑文案.md').write_text('\n\n'.join(transcript),encoding='utf-8')
print(OUT)

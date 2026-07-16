# WeatherFlow 用户状态感知 Agent 调研：来源与方法

调研日期：2026-07-15（Asia/Shanghai）

## 决策问题

WeatherFlow 是否处在一个真实、活跃的产品与研究方向中；如果是，它应当与“全量记录型个人记忆”“健康穿戴教练”“情绪语音接口”“主动式 Agent”分别保持什么关系，并优先验证哪一条产品闭环。

## 比较口径

项目按四段链路比较：

1. 采集什么用户信号；
2. 是否形成显式、可纠正、带不确定性的用户状态；
3. 状态是否改变 Agent 的交互或执行；
4. 是否有权限、隐私与效果验证边界。

“相似”不等于“直接竞品”。只做记忆检索、只做传感采集、只做健康建议或只做实验评测的项目均标为相邻层。

## 官方项目、仓库与原始论文

- ActivityWatch — 本地、开源的应用/窗口、浏览器与 AFK 活动采集；它采集的窗口标题和 URL 超出 WeatherFlow v3 当前允许的元数据边界。来源：https://github.com/ActivityWatch/activitywatch
- screenpipe — 连续屏幕、可访问性树、OCR 和音频记忆，并用定时 Pipes 运行可行动的 Agent；当前仓库说明为 source-available，商业使用受许可约束。来源：https://github.com/screenpipe/screenpipe
- Omi — 桌面、手机和穿戴设备上的屏幕/对话捕获、转录、记忆、行动项与工具扩展。来源：https://github.com/BasedHardware/omi
- Microsoft Recall — Copilot+ PC 上的本地屏幕快照记忆；默认关闭、需显式 opt-in，可暂停、过滤和删除，使用 Windows Hello/TPM/VBS 保护。来源：https://support.microsoft.com/en-us/windows/privacy/privacy-and-control-over-your-recall-experience
- Limitless/Rewind — 录音吊坠与桌面个人记忆的商业案例；官方在 2025-12 宣布加入 Meta、停止新售 Pendant，并 sunset Rewind 与非 Pendant 录制功能。来源：https://www.limitless.ai/
- Oura Advisor — 健康传感算法与 LLM 结合，使用得分、贡献因素、活动、标签、画像与对话记忆提供个性化建议；官方强调非医疗诊断。来源：https://support.ouraring.com/hc/en-us/articles/39512345699219-Oura-Advisor
- WHOOP Coach — 使用 Recovery、Sleep、Strain、位置和天气等生理/上下文数据提供个性化训练与恢复建议。来源：https://support.whoop.com/s/article/How-to-Use-the-AI-Powered-WHOOP-Coach?language=en_US
- Hume EVI — 实时分析语音韵律、音色与表达，在轮次时机、语气和措辞上适配用户。来源：https://dev.hume.ai/docs/speech-to-speech-evi/overview
- StudentLife — 通过手机被动传感与自我报告研究压力、睡眠、活动、情绪、社交与心理状态；原始研究强调相关性和群体研究，而不是通用个人 Agent。来源：https://studentlife.cs.dartmouth.edu/
- AWARE Framework — 面向研究的移动上下文采集、推断、记录与分享框架。来源：https://github.com/awareframework/aware-client
- Beiwe — 哈佛 Onnela Lab 的智能手机数字表型研究平台，覆盖 GPS、活动、通信和语音样本。来源：https://github.com/onnela-lab/beiwe-backend
- ProactiveAgent — ICLR 2025 研究项目，使用 ActivityWatch 收集编码、写作和日常生活轨迹，自动推荐任务，并提供反馈、奖励模型和评测管线。来源：https://github.com/thunlp/ProactiveAgent
- ContextAgent — NeurIPS 2025 研究项目，从穿戴设备视频/音频提取多维上下文与 persona，预测是否需要主动服务并调用工具；包含 1,000 个样本、9 个场景、20 个工具的 ContextAgentBench。来源：https://github.com/openaiotlab/ContextAgent 和 https://arxiv.org/abs/2505.14668
- Pare / Pare-Bench — 2026 年主动式 Agent 评测环境，以状态化应用、主动用户模拟、事件流和 Observe-Execute 分离评测目标推断、介入时机和跨应用执行。论文报告最佳前沿模型平均成功率约 42%，同时单独测量 Proposal Rate、Acceptance Rate 与 Success。来源：https://arxiv.org/abs/2604.00842
- Sensible Agent — UIST 2025 的 AR 主动助手研究，依据实时多模态上下文同时调整“提供什么”和“如何呈现”，强调低打扰交互。来源：https://arxiv.org/abs/2509.09255

## WeatherFlow 本地依据

- `weatherflow-architecture-v3.md`：产品宪法、静默主动性、Human State 与 Agent State 分离、权限边界。
- `docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md`：六维状态、信号范围、RhythmPolicy、WeatherPresentation、验收与阶段规划。
- `core/src/weatherflow/rhythm/estimator.py`：当前 `rhythm-v1` 为确定性原型，包含基线、关键词匹配、固定活动公式、统一置信度和固定 steady 趋势。
- `core/src/weatherflow/rhythm/projections.py`：当前状态到天气与执行策略的阈值映射。
- `docs/flagship-trajectory.md`：过载发布故事的确定性、provider-free 轨迹验收。

## 证据边界

- 只使用公开资料；无法看到各商业产品的真实留存、日活、误报率、用户信任或收入数据。
- 仓库热度、官方自述和论文指标不能直接互相比较，也不能证明商业成功。
- Pare 使用模拟用户与 API 级环境；其结果适合说明主动 Agent 的难度与评测方式，不等同于 WeatherFlow 真实用户效果。
- 本报告的路线图是基于公开证据与当前仓库实现的产品建议，不是市场规模估算或医疗/法律意见。

## 图表说明

- `Pare-Bench 主动 Agent 平均成功率`：比较/排序柱状图；一行一个被评测模型，纵轴为论文 Table 1 的平均 Success Rate。数据集同时保留 Success@4、四次全成功率、Proposal Rate、Acceptance Rate、Read Actions 与模型类别，便于审计，但图中只编码模型和平均成功率，避免把不同含义的百分比混成一个结论。来源：https://arxiv.org/abs/2604.00842

## 报告结构与 QA 记录

- 受众：产品负责人/项目作者；报告类型：战略备忘录；交付模式：自包含 HTML。
- 结构映射：Title → Executive Summary → 项目分层与证据 → 差异化定位 → 当前实现差距 → 推荐路线与指标 → 下一步 → Further Questions → Caveats。
- 项目矩阵、路线图和指标使用 Markdown 表格，因为它们以精确文本查找和职责边界为主，不存在诚实的共同数值轴；唯一原生图表用于 Pare-Bench 的同口径模型成功率比较。
- 便携报告打包结果：validation passed，package passed，verification structural_only。当前环境没有已安装的 Chromium headless-shell，因此未执行增强阅读器的交互与窄视口浏览器检查；精确 payload 一致性、运行时根、阅读器根和语义回退结构已通过。

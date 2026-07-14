# Skills 清单与推荐启用集合

本文是 `wesley-skills` 的人工维护清单。所有 skill 目录名保持不变；中文说明只用于明确作用、职责边界和推荐启用方式。

当前数量：127 个 `SKILL.md`。

## 使用原则

- 不建议一次性启用全部 skills。数量过多会让 agent 路由变得含混，尤其是名称相近的增长、工程和安全类 skills。
- 日常按场景启用一个集合即可；临时任务再补充单个 skill。
- 技术实现类任务优先启用工程集合；商业判断类任务优先启用 OPC/增长集合；写作和文档类任务优先启用内容集合。
- 目录名是稳定 API，不随中文描述变化。

## 推荐启用集合

### daily-codex-core

适合日常 coding agent 工作。覆盖理解需求、查资料、拆任务、实现、测试、review、提交。

```text
context-engineering
planning-and-task-breakdown
spec-driven-development
source-driven-development
incremental-implementation
test-driven-development
debugging-and-error-recovery
code-review-and-quality
code-simplification
documentation-and-adrs
git-workflow-and-versioning
git-commit-pro
```

### build-and-ship

适合从产品需求到上线的完整交付。比 `daily-codex-core` 更偏产品、前端、发布和线上质量。

```text
before-you-build
create-prd
prd-writing
user-stories
mvp-scoping
frontend-ui-engineering
api-and-interface-design
architecture-design
observability-and-instrumentation
performance-optimization
security-and-hardening
playwright-testing
shipping-and-launch
release-notes
```

### opc-founder-core

适合一人公司、solo founder、独立产品操盘。覆盖战略节奏、客户、offer、自动化和每周复盘。

```text
startup-context
opc-operating-system
opc-weekly-review
opc-customer-pipeline
opc-offer-sprint
opc-automation-map
market-research
review-mining
product-market-fit
offer-creation
pricing-strategy
unit-economics
decision-frameworks
founder-productivity
```

### growth-sales

适合获客、销售、内容和转化优化。用于从 ICP 到线索、触达、页面、广告、成交的链路。

```text
cold-outreach
lead-scoring
sales-script
objection-handling
proposal-generation
landing-page
copywriting
content-strategy
seo-content
seo-technical
email-marketing
social-content
paid-ads
metaads
sentiment-monitoring
```

### fundraising-investor

适合融资准备、投资人研究、材料打磨和投资人沟通。

```text
fundraising
fundraising-email
investor-research
pitch-deck
board-update
accelerator-application
data-room
financial-modeling
unit-economics
market-research
competitive-analysis
```

### ops-legal-team

适合把公司运营、招聘、合规、支持和流程标准化。

```text
sop-builder
process-docs
support-docs
contract-review
privacy-policy
terms-of-service
soc2-prep
hiring-playbook
job-description
interview-kit
sourcing-outreach
employer-brand
team-building
delegation-framework
```

### content-docs-cn

适合中文资料处理、翻译、Markdown、图表、会议纪要和最终汇报。

```text
baoyu-translate
baoyu-url-to-markdown
baoyu-format-markdown
baoyu-diagram
markdown-writer
pdf-analyzer
excel-processor
summarize-meeting
zouzhe
```

### qa-security-accessibility

适合上线前质量门禁、安全检查、测试生成和无障碍审计。

```text
test-generator
pytest
playwright-testing
api-tester
browser-testing-with-devtools
security-audit
security-review
security-and-hardening
wcag-audit-patterns
screen-reader-testing
performance-optimization
observability-and-instrumentation
```

### claude-code-light

适合 Claude Code 或任何只想启用少量核心技能的环境。这个集合刻意避开同义重复 skill。

```text
context-engineering
planning-and-task-breakdown
source-driven-development
test-driven-development
debugging-and-error-recovery
code-review-and-quality
git-workflow-and-versioning
startup-context
opc-operating-system
opc-customer-pipeline
opc-offer-sprint
market-research
copywriting
landing-page
pricing-strategy
baoyu-translate
baoyu-url-to-markdown
markdown-writer
```

## 启用命令模板

把集合中的名字填入 `SKILLS` 后执行即可。建议同一时间只启用一个主集合，再按任务补充少量单个 skill。

```bash
REPO="/Users/wesz_station/Projects/wesley-skills"
SKILLS="context-engineering planning-and-task-breakdown source-driven-development"

mkdir -p "$HOME/.codex/skills"
for skill in $SKILLS; do
  ln -sfn "$REPO/skills/$skill" "$HOME/.codex/skills/$skill"
done
```

## 名称相近时的选择规则

| 相近项 | 推荐选择 |
| --- | --- |
| `landing-page` / `landing-pages` | 做具体页面、审查页面时用 `landing-page`；做一组转化页面策略时用 `landing-pages`。 |
| `code-review` / `code-review-and-quality` | 通用代码 review 用 `code-review-and-quality`；创业项目快速技术把关可用 `code-review`。 |
| `ci-cd-and-automation` / `cicd-setup` / `github-actions` | 泛 CI/CD 架构用 `ci-cd-and-automation`；快速搭建用 `cicd-setup`；写 GitHub Actions YAML 用 `github-actions`。 |
| `security-and-hardening` / `security-audit` / `security-review` | 代码加固用 `security-and-hardening`；扫描漏洞用 `security-audit`；威胁建模和安全评审用 `security-review`。 |
| `email-campaigns` / `email-marketing` | 创业增长活动用 `email-campaigns`；邮件序列、newsletter 和转化优化用 `email-marketing`。 |
| `social-content` / `social-media` | 创始人 LinkedIn/IP 内容用 `social-content`；多渠道社媒运营用 `social-media`。 |
| `market-research` / `competitive-analysis` / `competitor-monitoring` | 市场进入和需求判断用 `market-research`；竞品对比用 `competitive-analysis`；持续监控用 `competitor-monitoring`。 |

## 完整 Skills 清单

### 工程流程与代码质量

| Skill | 职责 | 边界 |
| --- | --- | --- |
| `api-and-interface-design` | 设计稳定的 API、模块接口、数据契约和版本策略。 | 不负责真实接口压测；接口验证用 `api-tester`。 |
| `architecture-design` | 设计或评估系统架构、服务边界、数据流和扩展性。 | 不替代具体实现；实现阶段配合工程集合。 |
| `ci-cd-and-automation` | 规划和改造 CI/CD 流程、构建、测试、部署自动化。 | 具体 GitHub Actions 语法优先用 `github-actions`。 |
| `cicd-setup` | 为创业项目快速搭建或修复 CI/CD 管线。 | 偏落地启动，不做长期平台架构治理。 |
| `code-review` | 对代码做实用型评审，适合创业项目快速把关。 | 大型变更或多维质量评审优先用 `code-review-and-quality`。 |
| `code-review-and-quality` | 做多维代码评审，覆盖正确性、可维护性、测试、安全和性能。 | 不直接修复问题；修复时配合调试和实现类 skills。 |
| `code-simplification` | 在不改变行为的前提下简化代码、降低复杂度。 | 不适合需求变更或大规模重构。 |
| `context-engineering` | 组织 agent 上下文、入口文件、约束和任务背景。 | 不解决具体代码问题；它负责让后续工作少走弯路。 |
| `debugging-and-error-recovery` | 系统化定位失败、异常、测试挂掉和构建错误。 | 不跳过复现；需要先收集证据。 |
| `deprecation-and-migration` | 制定废弃旧接口、迁移数据或替换系统的方案。 | 不适合一次性小改名；用于有兼容期和风险面的迁移。 |
| `documentation-and-adrs` | 写架构决策记录、技术文档和变更说明。 | 不负责营销文案；营销内容用增长类 skills。 |
| `doubt-driven-development` | 对关键技术决策做反方审查，暴露隐藏风险。 | 不用于日常小任务；适合高影响决策。 |
| `frontend-ui-engineering` | 构建或修改生产级前端界面、交互和响应式布局。 | 不替代产品需求定义；需求先用 PRD/PM 类 skills。 |
| `git-commit-pro` | 生成结构化 commit message，偏 Conventional Commits。 | 不决定要提交哪些文件；提交范围先由 git workflow 判断。 |
| `git-workflow-and-versioning` | 管理分支、提交、版本、发布前 git 工作流。 | 不自动做产品发布说明；发布文案用 `release-notes`。 |
| `github-actions` | 编写和维护 GitHub Actions workflow、job、step 和 trigger。 | 不做非 GitHub CI 平台的深度适配。 |
| `incremental-implementation` | 把功能拆成可验证的小步实现，降低一次性改动风险。 | 不替代总体设计；复杂任务先做规划。 |
| `mcp-server-builder` | 构建 MCP server，把外部工具或数据源接入 agent。 | 不负责普通 REST API 设计；普通接口用 `api-and-interface-design`。 |
| `observability-and-instrumentation` | 给系统加日志、指标、trace、告警和可诊断性。 | 不替代性能优化；它先让问题可见。 |
| `parallel-debugging` | 用多假设并行排查复杂问题。 | 适合疑难问题，不适合单一明确报错。 |
| `parallel-feature-development` | 协调多分支、多文件所有权和并行开发策略。 | 不适合单人单文件小改。 |
| `performance-optimization` | 分析和优化应用性能、响应时间、吞吐、资源占用。 | 需要基准和证据；不要凭感觉优化。 |
| `planning-and-task-breakdown` | 把明确目标拆成有顺序、可执行、可验证的任务。 | 不做长期文件化计划；需要持久计划时用 `planning-with-files`。 |
| `planning-with-files` | 用文件保存长期计划、任务状态和执行记录。 | 不适合一次性短任务。 |
| `security-and-hardening` | 在实现阶段加固认证、输入处理、权限和敏感数据保护。 | 不替代独立安全审计；审计用 `security-audit` 或 `security-review`。 |
| `shipping-and-launch` | 准备生产发布、上线检查、回滚计划和发布节奏。 | 不替代产品 launch 营销计划；营销发布用 `launch-strategy`。 |
| `source-driven-development` | 要求实现依据官方文档、源码或权威资料。 | 不适合纯创意写作；用于防止凭记忆写错。 |
| `spec-driven-development` | 在编码前写清规格、行为、约束和验收标准。 | 不适合已经非常明确的小修。 |
| `tech-stack-eval` | 评估技术栈、框架、服务和工具选型。 | 不直接实施迁移；迁移用 `deprecation-and-migration`。 |
| `test-driven-development` | 用测试驱动实现业务逻辑、修复 bug 和重构。 | 不适合纯 UI 文案或无可测行为的任务。 |

### 测试、工具与数据处理

| Skill | 职责 | 边界 |
| --- | --- | --- |
| `api-tester` | 测试 REST 和 GraphQL API，形成结构化断言和报告。 | 不负责设计接口；接口设计用 `api-and-interface-design`。 |
| `browser-testing-with-devtools` | 通过 Chrome DevTools 做浏览器级检查和调试。 | 偏手动/诊断；稳定 E2E 测试用 `playwright-testing`。 |
| `docker-helper` | 构建、调试和优化 Dockerfile、compose 和容器运行问题。 | 不负责云平台部署架构。 |
| `excel-processor` | 读取、清洗、分析和生成 Excel/CSV 文件。 | 不适合复杂 BI 仪表盘长期维护。 |
| `pdf-analyzer` | 从 PDF 提取文本、表格、元数据和结构化信息。 | 版面设计或 PDF 生成需另行处理。 |
| `playwright-testing` | 编写和维护 Playwright 端到端测试。 | 不替代单元测试；Python 单测用 `pytest`。 |
| `pytest` | 为 Python 代码编写和运行 pytest 单元/集成测试。 | 不适合浏览器流程测试。 |
| `screen-reader-testing` | 用 VoiceOver、NVDA 等思路测试屏幕阅读器体验。 | 不等同完整 WCAG 审计；规则审计用 `wcag-audit-patterns`。 |
| `security-audit` | 扫描代码漏洞、配置错误和敏感信息泄露。 | 偏发现问题；修复加固用 `security-and-hardening`。 |
| `security-review` | 做威胁建模、安全方案评审和风险判断。 | 偏评审与判断；自动化扫描用 `security-audit`。 |
| `sql-optimizer` | 分析 SQL 查询、索引和执行计划，优化数据库性能。 | 不负责数据建模全局设计。 |
| `test-generator` | 为既有代码生成单元、集成或端到端测试。 | 不保证测试策略合理；复杂逻辑优先 TDD。 |
| `wcag-audit-patterns` | 按 WCAG 2.2 做自动和人工无障碍审计。 | 不直接修 UI；修复时配合前端 skill。 |

### 产品管理与发布

| Skill | 职责 | 边界 |
| --- | --- | --- |
| `before-you-build` | 在开工前审查产品风险、需求假设和过度建设。 | 不写完整 PRD；PRD 用 `create-prd` 或 `prd-writing`。 |
| `create-prd` | 生成结构完整的产品需求文档。 | 偏标准模板；创业场景可配合 `mvp-scoping`。 |
| `feedback-synthesis` | 从反馈、访谈、工单中提炼主题、问题和行动项。 | 不负责主动招募用户。 |
| `mvp-scoping` | 决定首版产品要做、要砍、要延期的范围。 | 不替代工程排期。 |
| `onboarding-flow` | 设计、优化或审计注册后激活流程。 | 不负责广告获客。 |
| `outcome-roadmap` | 把输出导向 roadmap 改成结果导向 roadmap。 | 不适合纯任务清单管理。 |
| `prd-writing` | 为具体功能定义产品需求、边界和验收标准。 | 与 `create-prd` 相近，偏创业/产品实战表达。 |
| `prioritization-frameworks` | 使用 RICE、ICE、MoSCoW 等框架做优先级判断。 | 框架只辅助判断，不替代业务上下文。 |
| `release-notes` | 从 tickets、PRD、changelog 生成用户可读发布说明。 | 不负责技术部署。 |
| `roadmap-planning` | 把产品事项组织为阶段化、优先级明确的路线图。 | 不负责单个 sprint 的任务拆解。 |
| `user-research-synthesis` | 分析用户访谈、调研和问卷，输出洞察和机会点。 | 不做市场规模估算。 |
| `user-stories` | 写用户故事、验收条件和对话说明。 | 不替代完整 PRD。 |

### OPC 与创业经营

| Skill | 职责 | 边界 |
| --- | --- | --- |
| `accelerator-application` | 准备创业加速器、孵化器申请材料。 | 不替代融资路演材料。 |
| `automation-workflows` | 为 OPC/创业团队识别和设计自动化流程。 | 深度自动化优先用自研 `opc-automation-map`。 |
| `board-update` | 写月度或季度投资人/董事会更新。 | 不写首次融资冷邮件。 |
| `churn-analysis` | 分析流失风险、流失原因和挽回动作。 | 不负责新客获取。 |
| `competitive-analysis` | 做竞品定位、功能、价格、渠道和差异化分析。 | 持续追踪用 `competitor-monitoring`。 |
| `competitor-monitoring` | 建立竞品动态监控和摘要机制。 | 不做一次性深入战略分析。 |
| `daily-product-digest` | 汇总 Product Hunt、Hacker News、GitHub 等产品趋势。 | 不等同正式市场研究。 |
| `data-room` | 准备融资、并购或尽调资料室结构。 | 不负责生成所有底层财务数据。 |
| `decision-frameworks` | 帮创业者做清晰决策，比较方案和取舍。 | 不替代领域专家建议。 |
| `delegation-framework` | 设计创始人如何委派、外包和管理执行工作。 | 不解决招聘管道。 |
| `financial-modeling` | 搭建收入、成本、现金流和情景模型。 | 不提供财务或投资承诺。 |
| `founder-productivity` | 优化创始人时间、注意力、例会和执行系统。 | 不处理团队文化建设。 |
| `fundraising` | 规划融资策略、叙事、材料和流程。 | 冷邮件单封写作用 `fundraising-email`。 |
| `fundraising-email` | 写给投资人的冷启动或跟进邮件。 | 不负责完整 pitch deck。 |
| `investor-research` | 识别、筛选和排序潜在投资人。 | 不保证投资人当前偏好准确，必要时需联网核验。 |
| `launch-strategy` | 制定产品发布前、中、后的启动计划。 | 不负责 CI/CD 技术发布。 |
| `market-research` | 研究市场、客户、竞品、趋势和机会空间。 | 学术文献研究后续需独立 research skills。 |
| `opc-automation-map` | 为一人公司梳理可自动化事项并按 ROI 排序。 | 不直接实现所有自动化。 |
| `opc-customer-pipeline` | 管理客户发现、销售线索、跟进、异议和转化。 | 不替代 CRM 软件。 |
| `opc-offer-sprint` | 把客户证据、痛点、定位、价格转成可售卖 offer。 | 不负责长期品牌战略。 |
| `opc-operating-system` | 搭建一人公司的轻量经营系统、目标、指标和节奏。 | 不适合大型组织治理。 |
| `opc-weekly-review` | 把一周工作、数据和反馈转成下一周重点。 | 不做年度战略规划。 |
| `pitch-deck` | 设计融资或销售 pitch deck 的结构和叙事。 | 不负责视觉设计稿精修。 |
| `pricing-strategy` | 设计定价、套餐、试验和付费转化策略。 | 不替代财务模型。 |
| `product-market-fit` | 判断 PMF 信号、差距和下一步验证动作。 | 不保证市场结论，无数据时只能给假设。 |
| `startup-context` | 创建或更新创业项目上下文文档。 | 不直接做市场或产品判断。 |
| `team-building` | 设计早期团队结构、协作方式和文化机制。 | 招聘文案用 `job-description` 或 `sourcing-outreach`。 |
| `unit-economics` | 分析 CAC、LTV、毛利、回本周期等单元经济。 | 依赖数据质量，不适合凭空精算。 |

### 增长、销售与市场内容

| Skill | 职责 | 边界 |
| --- | --- | --- |
| `cold-outreach` | 写冷邮件、私信和初次触达流程。 | 不负责后续销售谈判。 |
| `community-discovery` | 找 Slack、Discord、Reddit、社区和潜在分发渠道。 | 不负责社区运营。 |
| `content-strategy` | 规划内容主题、栏目、频率和分发目标。 | 不直接写单篇文案；写作用 `copywriting`。 |
| `copywriting` | 写转化导向文案、标题、页面段落和广告文案。 | 不负责完整内容日历。 |
| `earned-media-outreach` | 争取媒体、播客、采访和外部曝光。 | 不做付费广告。 |
| `email-campaigns` | 设计创业增长邮件活动。 | 与 `email-marketing` 相近，偏 founder/OPC 语境。 |
| `email-marketing` | 设计邮件序列、newsletter 和转化优化。 | 不负责投放广告。 |
| `event-hosting` | 策划 meetup、workshop、技术活动或社区事件。 | 不负责活动票务系统开发。 |
| `founder-thought-leadership` | 建立创始人观点、个人品牌和思想内容。 | 不等同普通社媒运营。 |
| `landing-page` | 创建、审查或优化单个 landing page。 | 多页面增长策略用 `landing-pages`。 |
| `landing-pages` | 制定一组落地页或转化页面策略。 | 单页细节优先用 `landing-page`。 |
| `lead-scoring` | 定义 ICP、线索评分和优先级。 | 不直接生成外呼脚本。 |
| `metaads` | 通过 Meta Marketing API 配置、发布、分析广告活动。 | 依赖账号、token 和平台权限。 |
| `objection-handling` | 准备销售异议处理、FAQ 和回应话术。 | 不替代客户访谈。 |
| `offer-creation` | 设计可售卖的产品/服务 offer、承诺和交付边界。 | 与 `opc-offer-sprint` 相近，后者更适合短周期冲刺。 |
| `paid-ads` | 规划付费广告策略、预算、素材和测试。 | Meta 平台具体操作用 `metaads`。 |
| `partnership-outreach` | 写合作、BD、集成和渠道拓展邮件。 | 不负责法律合同条款。 |
| `proposal-generation` | 生成销售 proposal、SOW 或服务方案。 | 合同风险用 `contract-review`。 |
| `review-mining` | 从评论、论坛、应用商店等挖掘痛点和需求。 | 不等同正式用户访谈分析。 |
| `sales-script` | 设计 demo、发现电话、成交和跟进脚本。 | 不处理广告获客。 |
| `sentiment-monitoring` | 监控评价、提及和社区情绪。 | 不负责危机公关全案。 |
| `seo-content` | 做 SEO 内容策略、关键词和文章方向。 | 技术 SEO 用 `seo-technical`。 |
| `seo-technical` | 做技术 SEO、页面结构、索引和站点健康检查。 | 不写长文内容。 |
| `social-content` | 为 LinkedIn 和创始人 IP 写社交内容。 | 多平台运营机制用 `social-media`。 |
| `social-media` | 规划社媒渠道、发布节奏和运营策略。 | 单篇高质量观点文优先用 `social-content`。 |

### 运营、团队、法务与合规

| Skill | 职责 | 边界 |
| --- | --- | --- |
| `contract-review` | 审查合同风险、关键条款和谈判点。 | 不是法律意见；重要合同需律师确认。 |
| `employer-brand` | 设计候选人看到的雇主品牌和招聘叙事。 | 不直接筛选候选人。 |
| `hiring-playbook` | 搭建招聘流程、角色定义、评估标准和面试环节。 | 招聘触达用 `sourcing-outreach`。 |
| `interview-kit` | 设计面试题、评分表和面试流程。 | 不负责岗位市场定位。 |
| `job-description` | 写、审查或优化职位描述。 | 不负责薪酬建模。 |
| `privacy-policy` | 起草、审查或更新隐私政策。 | 不是法律意见。 |
| `process-docs` | 创建 SOP、playbook、runbook 和流程说明。 | 不处理代码文档。 |
| `soc2-prep` | 准备 SOC 2 路线图、控制项和证据清单。 | 不替代审计机构。 |
| `sop-builder` | 为重复运营流程写标准作业程序。 | 与 `process-docs` 相近，偏创业运营流程。 |
| `sourcing-outreach` | 写招聘候选人触达消息。 | 不负责职位定义。 |
| `support-docs` | 写帮助中心、FAQ、排障文档和支持话术。 | 不负责客服系统集成。 |
| `terms-of-service` | 起草、审查或更新服务条款。 | 不是法律意见。 |

### 内容、文档与中文处理

| Skill | 职责 | 边界 |
| --- | --- | --- |
| `baoyu-diagram` | 创建专业深色 SVG 图表，如架构图、流程图、关系图。 | 不适合需要真实产品截图的设计稿。 |
| `baoyu-format-markdown` | 格式化 Markdown、补 frontmatter、标题、摘要和结构。 | 不负责事实核查。 |
| `baoyu-translate` | 做中英文翻译、精翻和风格化翻译。 | 不做专业法律/医学认证翻译。 |
| `baoyu-url-to-markdown` | 抓取 URL 内容并转为 Markdown。 | 依赖网页可访问性和抓取权限。 |
| `markdown-writer` | 写结构化技术文档、说明书和 Markdown 内容。 | 不负责设计视觉排版。 |
| `summarize-meeting` | 把会议转写整理成日期、参与者、决策和行动项。 | 不负责会议录音转文字。 |
| `zouzhe` | 把多步骤任务收尾汇报写成奏折体。 | 只用于收尾汇报，不用于普通短答。 |

## 待补齐方向

当前清单对创业和工程很强，但 academic research 还没有正式导入。下一批建议补：

- 文献检索与综述：paper lookup、literature review、citation management。
- 论文阅读：阅读矩阵、claim/evidence/threats 拆解。
- idea inspiration：研究问题生成、gap map、假设生成。
- 写作与审稿：paper outline、related work、method section、claim audit、peer review。

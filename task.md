# 升学智能体系统任务记录

## 当前状态

项目已完成一个可运行的 MVP：具备 FastAPI 后端、LangGraph 多智能体工作流、RAG 检索、ChromaDB 本地向量库、SQLite 存储、网页采集、长期记忆、Agent Trace 和本地演示页面。

当前系统更准确地说是：**Agent / RAG / Memory / Trace 的工程骨架已经跑通，并已支持可选 LLM 调用、Playwright 动态浏览、Autonomous Browser Research、候选质量评分、研究级检索、评估系统、高级长期记忆、工程化可观察性和前端工作流展示**。

---

## 已完成

### 1. 项目基础工程

- [x] 创建 Python 项目结构
- [x] 配置 `requirements.txt`
- [x] 配置 `.env.example`
- [x] 创建 FastAPI 应用入口
- [x] 创建本地静态演示页面
- [x] 创建测试目录与冒烟测试
- [x] 使用 Conda 环境 `webagent` 安装完整依赖
- [x] 运行测试并通过：`6 passed`

关键文件：

- `app/main.py`
- `requirements.txt`
- `.env.example`
- `tests/test_smoke.py`

---

### 2. FastAPI 后端接口

- [x] `GET /api/health`：健康检查
- [x] `POST /api/chat`：升学咨询对话
- [x] `POST /api/ingest/url`：采集导师主页 URL
- [x] `GET /api/tutors/search`：导师检索
- [x] `GET /api/memory/{session_id}`：查看长期记忆

关键文件：

- `app/main.py`
- `app/services/chat.py`
- `app/services/ingestion.py`

---

### 3. 数据模型

- [x] 导师档案模型 `TutorProfile`
- [x] 论文模型 `Paper`
- [x] 证据模型 `Evidence`
- [x] 用户画像模型 `UserProfile`
- [x] 长期记忆模型 `MemoryState`
- [x] 多步任务计划模型 `AgentPlan`
- [x] 任务步骤模型 `PlanStep`
- [x] Agent 执行轨迹模型 `AgentTrace`
- [x] API 请求/响应模型

关键文件：

- `app/models/schemas.py`

---

### 4. SQLite 本地存储

- [x] 初始化 SQLite 数据库
- [x] 保存导师档案
- [x] 保存长期记忆
- [x] 保存会话消息
- [x] 从示例 JSON 导入导师数据

关键文件：

- `app/storage/database.py`
- `app/storage/repositories.py`
- `data/sample/faculty_seed.json`

---

### 5. RAG 与向量数据库

- [x] 接入 ChromaDB 本地向量库
- [x] 实现导师档案向量写入
- [x] 实现导师检索器
- [x] 默认使用本地 `hashing` embedding，避免 Hugging Face 模型下载阻塞
- [x] 保留 `sentence-transformers` 依赖，后续可切换到真实 embedding 模型
- [x] 检索失败时提供关键词 fallback

关键文件：

- `app/rag/embeddings.py`
- `app/rag/vector_store.py`
- `app/rag/retriever.py`

当前限制：

- 默认 hashing embedding 语义检索能力有限
- 还没有 Hybrid Retrieval
- 还没有 reranker
- 还没有 RAG Evaluation

---

### 6. 多智能体工作流

- [x] 使用 LangGraph 构建多节点工作流
- [x] Memory Agent：加载和更新记忆
- [x] Planner Agent：生成任务计划
- [x] RAG Retriever：召回导师
- [x] Research Agent：分析候选导师匹配基础
- [x] Advisor Agent：生成推荐建议
- [x] 工作流返回 answer、plan、tutors、memory、trace

关键文件：

- `app/graph/admission_graph.py`
- `app/agents/planner_agent.py`
- `app/agents/memory_agent.py`
- `app/agents/advisor_agent.py`

当前限制：

- Planner 仍是规则规划，不是真正 LLM 规划
- Agent 间通信较简单
- 复杂任务还不能真正自动多轮搜索与执行

---

### 7. Browser Agent 与网页采集

- [x] 使用 `requests` 抓取公开网页
- [x] 使用 BeautifulSoup 提取标题、正文、链接
- [x] 使用 trafilatura 提取网页正文
- [x] 规则化抽取导师姓名、职称、机构、院系、邮箱、地区、研究方向、论文线索
- [x] 支持 URL 采集后写入数据库和向量库

关键文件：

- `app/agents/browser_agent.py`
- `app/agents/research_agent.py`
- `app/crawlers/faculty.py`
- `app/crawlers/papers.py`

当前限制：

- 还不是真正 Browser Automation
- 不支持 Playwright 动态网页浏览
- 不支持点击、翻页、等待动态加载、DOM 操作
- 不处理登录、验证码或反爬绕过

---

### 8. 长期记忆与上下文压缩

- [x] 记录用户研究兴趣
- [x] 记录地区偏好
- [x] 记录目标阶段
- [x] 保存最近对话消息
- [x] 在消息达到阈值后生成压缩摘要

关键文件：

- `app/agents/memory_agent.py`
- `app/storage/repositories.py`

当前限制：

- 目前主要是 profile memory
- Episodic Memory 还不完整
- Semantic Memory 还不完整
- 上下文压缩仍是简单摘要，不是语义压缩算法

---

### 9. Agent Trace 与任务计划可视化

- [x] 每次对话返回结构化 `AgentTrace`
- [x] 记录各智能体节点执行过程
- [x] 前端展示 Agent Trace
- [x] 前端展示多步任务计划
- [x] 支持查看每个步骤的 agent、status、rationale、expected output

关键文件：

- `app/models/schemas.py`
- `app/graph/admission_graph.py`
- `app/static/index.html`

当前限制：

- Trace 只保存在当前响应中
- 还没有持久化 Agent Trace
- 还没有 LangSmith / OpenTelemetry 集成

---

## 未完成 / 接下来要深入的部分

### 第一阶段：接入真正大模型调用

目标：让系统从规则模板回答升级为真正的 LLM Agent。

- [x] 新增 `app/llm/provider.py`
- [x] 在 `.env.example` 中增加 LLM 配置
  - `LLM_PROVIDER`
  - `ANTHROPIC_API_KEY`
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `LLM_MODEL`
- [x] 实现统一 `LLMClient`
- [x] 支持 Anthropic Claude API
- [x] 支持 OpenAI-compatible API
- [x] 没有 API Key 时 fallback 到当前规则逻辑
- [x] Advisor Agent 接入 LLM 生成个性化推荐
- [x] Research Agent 接入 LLM 进行网页结构化抽取
- [x] Agent Trace 中显示 LLM 调用过程
- [x] 已配置 DeepSeek OpenAI-compatible 调用：`LLM_PROVIDER=openai-compatible`，`LLM_MODEL=deepseek-v4-flash`
- [x] 测试环境默认禁用真实 LLM，避免 pytest 消耗 API 额度
- [x] 为 Query Rewriter 和搜索结果过滤器增加直接单元测试
- [x] 将 FastAPI startup 迁移到 lifespan，消除 `on_event` 弃用警告

预期效果：

- 不同问题返回更个性化
- 推荐理由更自然
- 网页结构化准确率更高
- 前端可看到 `LLM Agent` 调用轨迹

---

### 第二阶段：增强 Planner 与多步执行能力

目标：从固定 RAG pipeline 升级为更接近 Autonomous Agent 的多步任务系统。

- [x] Planner 输出更严格的结构化任务计划
- [x] 每个计划步骤有输入、输出、依赖关系
- [x] 支持步骤状态持久化
- [x] 支持复杂任务自动拆解
- [x] 支持 Browser / Research / Retriever / Advisor 多轮协作
- [x] 支持任务失败原因记录与重试策略
- [x] 支持用户在中途补充约束后重新规划

示例目标任务：

```text
帮我找武汉地区做多模态方向、近三年发过顶会、并且有企业合作的导师。
```

期望执行链路：

```text
Planner → Browser Agent → Research Agent → Paper Analyzer → RAG Retriever → Advisor Agent
```

---

### 第三阶段：真正 Browser Agent

目标：从静态网页抓取升级为 Browser Automation。

- [x] 接入 Playwright
- [x] 支持自动打开网页
- [x] 支持等待动态加载
- [x] 支持点击链接
- [x] 支持滚动页面
- [x] 支持读取 DOM
- [x] 支持从页面链接中发现候选导师主页线索
- [x] 支持 Browser Agent API 返回浏览动作与 DOM 摘要
- [x] 实现 Autonomous Browser Research Agent
- [x] 支持根据关键词生成搜索入口
- [x] 支持搜索结果候选导师主页链接筛选和打分
- [x] 支持批量浏览候选主页
- [x] 支持将候选主页结构化为导师档案并写入 SQLite + ChromaDB
- [x] 支持导航式信息采集第一版：搜索结果页 → 学院/师资入口页 → 导师主页
- [x] 支持配置导航深度和最多导航页面数
- [x] 新增 `/api/browser/research` 自动研究接口
- [x] 前端支持自动搜索、候选链接、入库导师和研究 Trace 展示
- [x] 支持候选预检：搜索页、院校导航页、师资列表页、论文页不会被误当作导师个人主页直接入库
- [x] 支持导师档案质量评分：结合姓名可信度、主页语境、机构/院系、研究方向、邮箱、论文线索和页面质量判断是否可入库
- [x] 手动 URL 采集入口 `/api/ingest/url` 复用导师档案质量评分，低质量页面返回 422 且不会写入 SQLite / ChromaDB
- [x] 新增 `/api/ingest/url/preview`：单个导师主页 URL 只抓取、结构化和评分，不写入 SQLite / ChromaDB
- [x] 支持 Browser Research dry-run 预检模式：只浏览、结构化和评分候选导师，不写入 SQLite / ChromaDB
- [x] 支持候选质量报告：统计候选总数、可入库数、拒绝数、平均质量分、状态/类型/拒绝原因分布和最高分候选
- [x] 两套前端展示候选页面质量、档案质量分、是否可入库和拒绝原因，并提供“仅预检不入库”入口
- [x] Browser Research 真实 dry-run 已能从华科计算机教师名录发现真实教师个人主页，并在不入库模式下识别 3 个合格候选：曹忠升、陈汉华、班鹏新
- [x] 修复中文高校页面编码识别、教师名录纯姓名链接优先级、真实教师平台主页姓名/机构/研究方向抽取，避免师资栏目页抢占候选名额
- [x] 保持内置 Playwright Browser Agent，不额外引入 Browser Use / Stagehand，避免增加复杂依赖

当前限制：

- 搜索入口目前基于 Bing / Baidu 搜索结果页，不调用官方 Search API
- 候选链接筛选仍是启发式规则打分
- 批量浏览默认限制候选数量，避免对公开网站造成过高请求压力
- 不保证所有高校页面都能被静态或 Playwright 正确解析
- 当前真实 dry-run 只证明公开华科教师平台链路可发现并预检合格导师主页；是否写入真实库仍应先 dry-run 审核质量报告

当前不会做：

- [ ] 不绕过登录
- [ ] 不绕过验证码
- [ ] 不做反爬规避

---

### 第四阶段：研究级 RAG

目标：提升检索质量，使推荐不再依赖简单 hashing。

- [x] 支持 BGE-M3 / bge-large-zh embedding
- [x] 支持 OpenAI / Claude 兼容 embedding API
- [x] 支持 BM25 关键词检索
- [x] 实现 Hybrid Retrieval：BM25 + Dense Retrieval
- [x] 接入本地轻量 reranker 第一版
- [x] 接入模型 reranker：bge-reranker / jina-reranker
- [x] 支持 chunking 策略
- [x] 支持论文、主页、招生信息分字段检索证据
- [x] 支持引用证据高亮

---

### 第五阶段：评估系统

目标：从“能跑”升级为“可评估、可比较、可优化”。

- [x] 构建 evaluation dataset 第一版
- [x] 设计导师推荐测试问题集第一版
- [x] 增强 Benchmark Dataset 覆盖度，并新增 `/api/eval/rag/dataset` 数据集摘要接口
- [x] 评估 Recall
- [x] 评估 Precision
- [x] 评估 Relevance
- [x] 评估 Faithfulness
- [x] 对比不同 embedding 模型
- [x] 对比不同 chunk size
- [x] 对比有无 reranker / hybrid retrieval
- [x] 输出评估报告
- [x] 新增检索结果质量评估脚本，区分命中导师、有效但非预期导师和真实干扰项，并用审计规则判断检索结果是否混入噪声
- [x] 当前本地 RAG benchmark 6 个用例 top-1 全部命中预期导师，平均 recall 1.0，干扰项用例数 0；但该结论基于本地 3 条 seed/demo 导师数据

---

### 第六阶段：高级长期记忆

目标：从简单用户画像升级为长期可演化记忆系统。

- [x] Episodic Memory：记录用户联系过的导师、反馈、拒绝、偏好变化
- [x] Semantic Memory：抽象用户长期研究兴趣和申请策略
- [x] Procedural Memory：记录用户偏好的申请流程与材料准备方式
- [x] Memory Retrieval：回答时检索相关历史记忆
- [x] Memory Reflection：定期总结用户长期目标变化
- [x] Memory Conflict Resolution：处理用户偏好冲突

---

### 第七阶段：可观察性与工程化

目标：提升项目工程深度和可展示性。

- [x] 持久化 Agent Trace
- [x] 接入 LangSmith 或 OpenTelemetry
- [x] 增加请求 ID / session trace ID
- [x] 增加日志系统
- [x] 增加错误处理与失败恢复
- [x] 增加配置化开关
- [x] 增加 Dockerfile
- [x] 增加启动脚本

---

## 后续增强路线图

按优先级从工程稳定性、Agent 深度、检索质量和展示完整度逐步推进：

1. **配置化开关与安全边界**
   - [x] 增加 `ENABLE_BROWSER_RESEARCH`，允许关闭自动联网研究接口。
   - [x] 增加 `ENABLE_RAG_EVAL`，允许关闭评估接口，避免线上误触高开销任务。
   - [x] 增加 `AUTO_SEED_DATA`，控制启动时是否自动导入示例导师数据。
   - [x] 增加 Browser Research 上限配置：搜索页数、候选链接数、入库数量、导航页数。
   - [x] 对请求参数做统一裁剪，避免一次请求触发过多公开网页访问。
2. **错误处理与失败恢复**
   - [x] 统一 API 错误响应格式。
   - [x] Browser / Research / RAG 节点记录结构化失败原因。
   - [x] 对网页采集增加有限重试、超时分类和失败 trace。
3. **Planner 与任务状态持久化**
   - [x] 将 `AgentPlan` 和 `PlanStep` 持久化到 SQLite。
   - [x] 支持用户补充约束后的重新规划。
   - [x] 支持按 `trace_id` / `session_id` 回看计划执行状态。
4. **高级长期记忆**
   - [x] 实现 Episodic Memory：记录联系过、收藏、排除、反馈过的导师。
   - [x] 实现 Semantic Memory：抽象长期研究兴趣和申请策略。
   - [x] 实现 Procedural Memory：记录申请流程、材料准备、沟通和时间安排偏好。
   - [x] 实现 Memory Retrieval：回答时检索相关历史记忆。
5. **研究级 RAG 继续增强**
   - [x] 接入 BGE-M3 / bge-large-zh embedding。
   - [x] 接入 OpenAI-compatible embedding API。
   - [x] 接入 bge-reranker / jina-reranker。
   - [x] 实现 chunking 策略，后续继续评估不同 chunk size。
6. **评估系统完善**
   - [x] 增加 Faithfulness 评估。
   - [x] 保存历史评估结果。
   - [x] 对比不同 embedding、reranker 和 chunking 配置。
   - [x] React 前端支持加载评估数据集摘要、策略对比和配置对比。
7. **Browser Agent 深度增强**
   - [x] 支持导师列表页分页识别。
   - [x] 支持更深链路导航：高校主页 → 学院主页 → 师资列表 → 导师主页 → 论文页。
   - [x] 增加页面质量评分和候选主页置信度。
8. **部署与展示**
   - [x] 增加 Dockerfile 和启动脚本。
   - [x] 增强内置前端工作流 UI：展示 Plan / Trace / Evidence / Memory、Browser Research 深链路候选和导航参数。
   - [x] 增加独立 React / Vite 前端工程，可连接 FastAPI API 展示工作流 UI。
   - [x] 两套前端均支持预览高校种子入口、匹配原因和匹配词。
   - [x] 两套前端均支持单个导师主页 URL 预检和采集入库。
   - [x] 增加端到端演示检查脚本，覆盖 health、chat、seed-sites 和 RAG Evaluation。
   - [x] 增加导师数据质量审计和无效数据清理脚本。
- [x] 增加 `GET /api/tutors/audit` 数据质量审计接口和 React 审计面板。
   - [x] 可选接入 LangSmith 或 OpenTelemetry。

---

## 当前推荐下一步

下一阶段优先做 **真实数据闭环**，目标是证明系统不只会检索自写 demo 数据，也能从公开网页获得正确导师资料并被 RAG 准确召回。

### 立刻做：真实数据闭环

1. **分离 demo seed 与真实公开数据样本** `[已完成第一版]`
   - `data/sample/faculty_seed.json` 继续作为离线演示 seed，不再用它证明真实采集能力。
   - 新增 `data/sample/real_faculty_sample.json`，保存 3 条公开华科教师主页样本：曹忠升、陈汉华、班鹏新。
2. **建立真实导师 benchmark 第一版** `[已完成第一版]`
   - 新增 `data/sample/real_rag_eval.json`，覆盖华科教师平台 dry-run 已发现的真实候选。
   - 评估问题围绕真实页面能证明的方向，例如数据库、多媒体、大数据、计算机学院、武汉等。
3. **真实数据检索质量评估脚本** `[已完成第一版]`
   - `scripts/evaluate_retrieval_quality.py` 支持 `--dataset` 和 `--sample`，可用真实样本做隔离评估，不污染运行库。
   - 输出“命中真实导师 / 有效但非预期导师 / 干扰项”，并明确 demo benchmark 与真实 benchmark 的结果分别代表什么。
4. **继续使用 dry-run 作为真实采集前置门禁** `[已完成第一版]`
   - 写入真实库前必须先查看候选质量报告，确认候选是导师个人主页且包含姓名、机构、研究方向或其它证据。
   - 不把搜索页、栏目页、教师列表页、新闻页、百科页写入导师库。
5. **补充 profile-level relevance** `[已完成第一版]`
   - 本地 reranker 已增强院校别名、导师类型、职称、学科方向和精确短语权重，降低宽泛关键词覆盖导致的排序偏差。
   - `scripts/evaluate_retrieval_quality.py` 已输出 `top1_hit_rate`、`rank_of_first_hit` 和 `--min-top1-hit-rate` 门禁，能量化“召回正确但排序不准”。
   - 真实 HUST 样本隔离 benchmark 当前 3 个用例 top-1 全部命中预期导师，`avg_recall=1.0`、`top1_hit_rate=1.0`、`avg_rank_of_first_hit=1.0`、`interference_case_count=0`。

### 后续增强方向

6. Query Rewriter / 搜索域限制 / 搜索结果过滤器已完成第一版，后续升级 multi-query retrieval 与 search planning。
7. Browser Agent 已支持搜索页 → 学院/师资页 → 导师主页；后续继续增强分页、教师平台子页面、论文页和招生页抓取。
8. RAG 已支持 hybrid / reranker / evaluation；真实样本第一版已能量化 top-1 相关性，后续重点扩大真实 benchmark 覆盖率。
9. 前端、Trace、Memory、Docker、配置上限、审计和质量报告已完成第一版，后续围绕真实数据展示质量证据。

原因：

项目工程骨架已经完整，继续堆功能的收益低于补齐真实数据证据链。下一步的核心验收标准是：公开网页 dry-run 能找到合格导师主页，真实样本可审计，真实 benchmark 能检索到正确导师，并且报告中明确区分 demo 数据、真实有效数据和干扰项。

LLM 配置示例：

```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=你的 Key
```

或 OpenAI-compatible：

```env
LLM_PROVIDER=openai-compatible
LLM_MODEL=你的模型名
OPENAI_API_KEY=你的 Key
OPENAI_BASE_URL=https://api.openai.com/v1
```

---

## 常用命令

安装依赖：

```powershell
conda activate webagent
python -m pip install -r requirements.txt
```

运行项目：

```powershell
conda activate webagent
python -m uvicorn app.main:app --reload
```

运行测试：

```powershell
conda activate webagent
python -m pytest -q
```

Browser Research dry-run 质量检查：

```powershell
conda activate webagent
python scripts/browser_quality_check.py --base-url http://127.0.0.1:8000 --query "武汉 多模态 人工智能 导师 个人主页"
```

访问页面：

```text
http://127.0.0.1:8000
```

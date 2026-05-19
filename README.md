# 升学智能体系统（Research Agent）

基于 FastAPI、LangGraph、RAG、长期记忆、Browser Research 和本地向量数据库构建的升学辅助多智能体系统。系统可进行多轮升学咨询、导师检索与推荐、公开网页采集入库、深链路 Browser Research、记忆沉淀、RAG 评估和工作流可视化。

## 功能

- 多智能体工作流：Memory / Planner / Browser / RAG Retriever / Research / Advisor 节点协作。
- 结构化任务计划：支持计划持久化、步骤状态、重新规划和 Agent handoff 展示。
- RAG 导师推荐：支持 dense retrieval、BM25、hybrid retrieval、reranker、chunking 和高亮证据。
- Browser Research：支持 Query Rewriter、搜索结果过滤、Playwright 动态浏览、分页识别、深链路导航和候选置信度。
- 长期记忆：支持 Episodic / Semantic / Procedural Memory、记忆检索、反思、冲突解决和上下文压缩。
- 评估系统：支持 Recall、Precision、Relevance、Faithfulness、策略对比、配置对比、Benchmark Dataset 摘要和历史评估记录。
- 可观察性：支持请求 ID、结构化错误、Agent Trace 持久化和可选 OpenTelemetry。
- 前端展示：内置静态页面 + 独立 React / Vite 工作流前端。
- 部署工程：提供 Dockerfile、启动脚本和配置化开关。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

如需自定义配置：

```powershell
Copy-Item .env.example .env
```

Conda 环境示例：

```powershell
conda activate webagent
python -m pip install -r requirements.txt
```

## 运行后端与内置页面

```powershell
python -m uvicorn app.main:app --reload
```

或使用启动脚本：

```powershell
python scripts/run.py
```

浏览器打开内置页面：

```text
http://127.0.0.1:8000
```

## 运行独立 React / Vite 前端

先启动 FastAPI 后端，再运行：

```powershell
cd frontend
npm install
npm run dev
```

Vite 开发服务器会把 `/api` 请求代理到 `http://127.0.0.1:8000`。

## 测试与验证

后端测试：

```powershell
python -m pytest -q
```

前端验证：

```powershell
cd frontend
npm run lint
npm run build
```

## 主要 API

- `GET /api/health`：健康检查。
- `GET /api/system/capabilities`：系统能力概览。
- `POST /api/chat`：多轮升学咨询，返回 answer、plan、trace、agent_handoffs、memory 和检索证据。
- `POST /api/ingest/url`：采集公开导师主页并入库。
- `POST /api/browser/browse`：Playwright 动态浏览和 DOM 摘要。
- `POST /api/browser/research`：自动搜索、深链路导航、结构化导师入库。
- `GET /api/tutors/search?q=...`：导师检索。
- `GET /api/memory/{session_id}`：查看长期记忆。
- `GET /api/traces/{trace_id}` / `GET /api/traces/session/{session_id}`：查看 Agent Trace。
- `GET /api/plans/{plan_id}` / `GET /api/plans/session/{session_id}`：查看任务计划。
- `GET /api/eval/rag`：运行单策略 RAG 评估。
- `GET /api/eval/rag/compare`：对比 baseline / hybrid / reranker。
- `GET /api/eval/rag/report`：生成 Markdown 评估报告。
- `GET /api/eval/rag/configurations`：对比检索配置。
- `GET /api/eval/rag/dataset`：查看 Benchmark Dataset 覆盖度。
- `GET /api/eval/rag/runs`：查看历史评估记录。

## Docker

```powershell
docker build -t admission-research-agent .
docker run --rm -p 8000:8000 admission-research-agent
```

## 安全边界

网页采集只面向公开页面，不处理登录、验证码或反爬绕过；批量浏览受配置上限约束，避免对公开网站造成过高请求压力。推荐结果仅作信息辅助，需要以学校官网、导师主页和导师最新回复为准。

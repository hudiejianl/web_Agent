# 升学智能体系统（Research Agent）

基于 FastAPI、LangGraph、RAG 和本地向量数据库构建的升学辅助多智能体 MVP。系统支持导师资料结构化、个性化导师推荐、网页采集、长期记忆、上下文摘要和多轮任务规划。

## 功能

- LangGraph 多节点工作流：记忆加载、任务规划、导师检索、个性化建议、记忆更新
- RAG 导师推荐：使用 ChromaDB + 嵌入模型检索导师资料
- Browser Agent：抓取公开导师主页，提取正文、标题和链接
- Research Agent：将网页内容整理为导师档案、研究方向、论文和证据
- 长期记忆：保存用户研究兴趣、地区偏好、目标阶段和对话摘要
- 本地 Web 页面：提供咨询与 URL 采集入口

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

如需自定义配置：

```powershell
Copy-Item .env.example .env
```

## 运行

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

浏览器打开内置页面：

```text
http://127.0.0.1:8000
```

也可以运行独立 React / Vite 前端工程：

```powershell
cd frontend
npm install
npm run dev
```

前端开发服务器会代理 `/api` 到 `http://127.0.0.1:8000`，因此需要先启动 FastAPI 后端。

## 测试

```powershell
.\.venv\Scripts\python -m pytest
```

## API

- `GET /api/health`：健康检查
- `POST /api/chat`：多轮升学咨询
- `POST /api/ingest/url`：采集导师主页并入库
- `GET /api/tutors/search?q=...`：检索导师
- `GET /api/memory/{session_id}`：查看长期记忆

## 说明

MVP 内置示例导师数据，首次启动会自动入库和向量化。网页采集只面向公开页面，不处理登录、验证码或反爬绕过。推荐结果用于信息辅助，需要以学校官网和导师最新回复为准。

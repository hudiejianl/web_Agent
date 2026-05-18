# 升学智能体独立前端

这是项目的 React / Vite 前端工程，用于连接 FastAPI 后端并展示：

- 多轮升学咨询结果
- Agent Plan / Trace / Evidence / Memory
- Browser Research 深链路候选
- 导师入库结果

## 运行

先在项目根目录启动 FastAPI 后端：

```powershell
python -m uvicorn app.main:app --reload
```

再启动前端：

```powershell
cd frontend
npm install
npm run dev
```

Vite 开发服务器会把 `/api` 请求代理到 `http://127.0.0.1:8000`。

## 验证

```powershell
npm run lint
npm run build
```

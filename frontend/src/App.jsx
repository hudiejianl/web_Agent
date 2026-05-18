import { useMemo, useState } from 'react'
import './App.css'

const defaultMessage = '我想申请 AI 和 RAG 方向硕士，偏好江浙沪，帮我推荐导师。'
const defaultResearchQuery = '武汉 多模态 人工智能 导师 个人主页'

function App() {
  const [sessionId] = useState(() => localStorage.getItem('sessionId') || crypto.randomUUID())
  const [message, setMessage] = useState(defaultMessage)
  const [researchQuery, setResearchQuery] = useState(defaultResearchQuery)
  const [navigationDepth, setNavigationDepth] = useState(3)
  const [maxNavigationPages, setMaxNavigationPages] = useState(8)
  const [chatResult, setChatResult] = useState(null)
  const [researchResult, setResearchResult] = useState(null)
  const [activeTab, setActiveTab] = useState('plan')
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')

  localStorage.setItem('sessionId', sessionId)

  const workflow = useMemo(() => {
    const plan = chatResult?.plan
    const trace = chatResult?.trace || researchResult?.trace || []
    const steps = plan?.steps || []
    const completed = steps.filter((step) => step.status === 'completed').length
    const failed = trace.filter((item) => item.status === 'failed').length
    const progress = steps.length ? Math.round((completed / steps.length) * 100) : trace.length ? 100 : 0
    return { steps, completed, failed, traceCount: trace.length, progress }
  }, [chatResult, researchResult])

  async function requestJson(path, options) {
    setError('')
    const response = await fetch(path, options)
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.detail || JSON.stringify(data))
    }
    return data
  }

  async function sendChat() {
    setLoading('chat')
    try {
      const data = await requestJson('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message }),
      })
      setChatResult(data)
      setActiveTab('plan')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading('')
    }
  }

  async function runBrowserResearch() {
    setLoading('research')
    try {
      const data = await requestJson('/api/browser/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: researchQuery,
          max_search_pages: 1,
          max_candidates: 8,
          max_ingest: 3,
          navigation_depth: Number(navigationDepth),
          max_navigation_pages: Number(maxNavigationPages),
          use_playwright: true,
        }),
      })
      setResearchResult(data)
      setActiveTab('candidates')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading('')
    }
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Admission Research Agent</p>
          <h1>升学智能体工作流前端</h1>
          <p>独立 React / Vite UI，连接 FastAPI 后端，展示咨询、Plan、Trace、RAG Evidence、Memory 和 Browser Research 深链路候选。</p>
        </div>
        <div className="hero-card">
          <span>Session</span>
          <strong>{sessionId}</strong>
        </div>
      </header>

      {error && <div className="alert">{error}</div>}

      <main className="layout">
        <section className="panel primary">
          <h2>多轮升学咨询</h2>
          <textarea value={message} rows={5} onChange={(event) => setMessage(event.target.value)} />
          <button type="button" onClick={sendChat} disabled={loading === 'chat'}>
            {loading === 'chat' ? '智能体执行中...' : '发送咨询'}
          </button>
          <pre className="answer">{chatResult ? `${chatResult.answer}\n\nTrace ID: ${chatResult.trace_id}` : '等待咨询结果...'}</pre>
        </section>

        <section className="panel">
          <h2>Autonomous Browser Research</h2>
          <textarea value={researchQuery} rows={3} onChange={(event) => setResearchQuery(event.target.value)} />
          <div className="field-grid">
            <label>导航深度<input type="number" min="0" max="5" value={navigationDepth} onChange={(event) => setNavigationDepth(event.target.value)} /></label>
            <label>最多导航页<input type="number" min="1" max="20" value={maxNavigationPages} onChange={(event) => setMaxNavigationPages(event.target.value)} /></label>
          </div>
          <button type="button" className="secondary" onClick={runBrowserResearch} disabled={loading === 'research'}>
            {loading === 'research' ? '深度研究中...' : '自动搜索并入库'}
          </button>
          <pre>{researchResult ? JSON.stringify({ trace_id: researchResult.trace_id, rewritten_queries: researchResult.rewritten_queries, tutors: researchResult.tutors?.map((item) => item.name) }, null, 2) : '等待 Browser Research 结果...'}</pre>
        </section>
      </main>

      <section className="panel workflow">
        <h2>工作流总览</h2>
        <div className="stats">
          <Stat label="任务进度" value={`${workflow.progress}%`} />
          <Stat label="计划步骤" value={`${workflow.completed}/${workflow.steps.length}`} />
          <Stat label="Trace 节点" value={workflow.traceCount} />
          <Stat label="失败节点" value={workflow.failed} danger={workflow.failed > 0} />
        </div>
        <div className="progress"><span style={{ width: `${workflow.progress}%` }} /></div>
      </section>

      <section className="panel">
        <nav className="tabs">
          {[
            ['plan', 'Plan'],
            ['trace', 'Trace'],
            ['evidence', 'Evidence'],
            ['memory', 'Memory'],
            ['handoffs', 'Agent Handoffs'],
            ['candidates', 'Browser Candidates'],
            ['tutors', 'Tutors'],
          ].map(([id, label]) => (
            <button key={id} type="button" className={activeTab === id ? 'active' : ''} onClick={() => setActiveTab(id)}>{label}</button>
          ))}
        </nav>
        {activeTab === 'plan' && <PlanView steps={chatResult?.plan?.steps || []} />}
        {activeTab === 'trace' && <TraceView items={chatResult?.trace || researchResult?.trace || []} />}
        {activeTab === 'evidence' && <EvidenceView items={chatResult?.retrieval_evidence || []} />}
        {activeTab === 'memory' && <JsonView data={chatResult?.memory || {}} />}
        {activeTab === 'handoffs' && <HandoffView items={chatResult?.agent_handoffs || []} />}
        {activeTab === 'candidates' && <CandidateView items={researchResult?.candidates || []} />}
        {activeTab === 'tutors' && <TutorView items={[...(chatResult?.tutors || []), ...(researchResult?.tutors || [])]} />}
      </section>
    </div>
  )
}

function Stat({ label, value, danger }) {
  return <div className={danger ? 'stat danger' : 'stat'}><span>{label}</span><strong>{value}</strong></div>
}

function PlanView({ steps }) {
  if (!steps.length) return <Empty text="暂无任务计划" />
  return steps.map((step) => <article className="row" key={step.id}><Badge value={step.status} /><div><strong>{step.name}</strong><p>{step.agent} · {step.rationale}</p><small>预期输出：{step.expected_output || '未定义'}</small></div></article>)
}

function TraceView({ items }) {
  if (!items.length) return <Empty text="暂无执行轨迹" />
  return items.map((item, index) => <article className="row" key={`${item.action}-${index}`}><Badge value={item.status} /><div><strong>[{item.agent}] {item.action}</strong><p>{item.detail}</p><small>{new Date(item.timestamp).toLocaleString()}</small></div></article>)
}

function EvidenceView({ items }) {
  if (!items.length) return <Empty text="暂无检索证据" />
  return items.map((item, index) => <article className="row" key={`${item.tutor_id}-${index}`}><Badge value={item.field} /><div><strong>{item.tutor_name}</strong><p>{item.snippet}</p><small>匹配词：{item.matched_terms?.join('、') || '无'} · score {item.score}</small></div></article>)
}

function CandidateView({ items }) {
  if (!items.length) return <Empty text="暂无候选链路" />
  return items.map((item) => <article className="row" key={item.url}><Badge value={item.link_type || item.status} /><div><strong>{item.text || item.url}</strong><p>{item.url}</p><small>depth {item.depth} · confidence {item.confidence} · {item.reason}</small></div></article>)
}

function HandoffView({ items }) {
  if (!items.length) return <Empty text="暂无 Agent 交接记录" />
  return items.map((item, index) => <article className="row" key={`${item.source_agent}-${item.target_agent}-${index}`}><Badge value={item.payload_type} /><div><strong>{item.source_agent} → {item.target_agent}</strong><p>{item.summary}</p><small>{JSON.stringify(item.payload || {})}</small></div></article>)
}

function TutorView({ items }) {
  if (!items.length) return <Empty text="暂无导师结果" />
  return items.map((item, index) => <article className="card" key={`${item.name}-${index}`}><strong>{item.name}</strong><p>{item.institution} {item.department || ''}</p><small>方向：{item.research_areas?.join('、') || '未识别'}</small></article>)
}

function JsonView({ data }) {
  return <pre>{JSON.stringify(data, null, 2)}</pre>
}

function Badge({ value }) {
  return <span className={`badge ${value}`}>{value}</span>
}

function Empty({ text }) {
  return <p className="empty">{text}</p>
}

export default App

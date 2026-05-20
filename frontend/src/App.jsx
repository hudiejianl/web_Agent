import { useEffect, useMemo, useState } from 'react'
import './App.css'

const defaultMessage = '我想申请 AI 和 RAG 方向硕士，偏好江浙沪，帮我推荐导师。'
const defaultResearchQuery = '武汉 多模态 人工智能 导师 个人主页'
const defaultTutorUrl = 'https://cs.example.edu.cn/teacher/zhangsan'

function App() {
  const [sessionId] = useState(() => localStorage.getItem('sessionId') || crypto.randomUUID())
  const [message, setMessage] = useState(defaultMessage)
  const [researchQuery, setResearchQuery] = useState(defaultResearchQuery)
  const [tutorUrl, setTutorUrl] = useState(defaultTutorUrl)
  const [navigationDepth, setNavigationDepth] = useState(3)
  const [maxNavigationPages, setMaxNavigationPages] = useState(8)
  const [chatResult, setChatResult] = useState(null)
  const [urlPreviewResult, setUrlPreviewResult] = useState(null)
  const [urlIngestResult, setUrlIngestResult] = useState(null)
  const [researchResult, setResearchResult] = useState(null)
  const [seedSites, setSeedSites] = useState(null)
  const [ragDataset, setRagDataset] = useState(null)
  const [ragComparison, setRagComparison] = useState(null)
  const [ragConfigurations, setRagConfigurations] = useState(null)
  const [tutorAudit, setTutorAudit] = useState(null)
  const [capabilities, setCapabilities] = useState(null)
  const [activeTab, setActiveTab] = useState('plan')
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')

  localStorage.setItem('sessionId', sessionId)

  useEffect(() => {
    requestJson('/api/system/capabilities')
      .then(setCapabilities)
      .catch((err) => setError(err.message))
  }, [])

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

  async function loadSeedSites() {
    setLoading('seed-sites')
    try {
      const query = encodeURIComponent(researchQuery)
      const data = await requestJson(`/api/browser/seed-sites?q=${query}&limit=6`)
      setSeedSites(data.sites || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading('')
    }
  }

  async function previewTutorUrl() {
    setLoading('url-preview')
    try {
      const data = await requestJson('/api/ingest/url/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: tutorUrl }),
      })
      setUrlPreviewResult(data)
      setActiveTab('tutors')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading('')
    }
  }

  async function ingestTutorUrl() {
    setLoading('url-ingest')
    try {
      const data = await requestJson('/api/ingest/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: tutorUrl }),
      })
      setUrlIngestResult(data)
      setActiveTab('tutors')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading('')
    }
  }

  async function loadTutorAudit() {
    setLoading('tutor-audit')
    try {
      setTutorAudit(await requestJson('/api/tutors/audit'))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading('')
    }
  }

  async function loadRagEvaluation() {
    setLoading('rag-eval')
    try {
      const [dataset, comparison, configurations] = await Promise.all([
        requestJson('/api/eval/rag/dataset'),
        requestJson('/api/eval/rag/compare?limit=5'),
        requestJson('/api/eval/rag/configurations?limit=5'),
      ])
      setRagDataset(dataset)
      setRagComparison(comparison)
      setRagConfigurations(configurations)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading('')
    }
  }

  async function runBrowserResearch(dryRun = false) {
    setLoading(dryRun ? 'research-preview' : 'research')
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
          dry_run: dryRun,
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
          <h2>导师主页 URL 采集</h2>
          <p className="panel-note">先预检质量再入库，避免无效页面污染导师库。</p>
          <input value={tutorUrl} onChange={(event) => setTutorUrl(event.target.value)} placeholder="https://..." />
          <div className="action-row url-actions">
            <button type="button" className="ghost" onClick={previewTutorUrl} disabled={loading === 'url-preview'}>
              {loading === 'url-preview' ? '预检中...' : '仅预检不入库'}
            </button>
            <button type="button" className="secondary" onClick={ingestTutorUrl} disabled={loading === 'url-ingest'}>
              {loading === 'url-ingest' ? '入库中...' : '采集并入库'}
            </button>
          </div>
          <UrlPreviewCard data={urlPreviewResult} />
          <pre>{urlIngestResult ? JSON.stringify({ indexed: urlIngestResult.indexed, tutor: urlIngestResult.tutor?.name }, null, 2) : '暂无 URL 入库结果'}</pre>
        </section>

        <section className="panel">
          <h2>Autonomous Browser Research</h2>
          <textarea value={researchQuery} rows={3} onChange={(event) => setResearchQuery(event.target.value)} />
          <div className="field-grid">
            <label>导航深度<input type="number" min="0" max="5" value={navigationDepth} onChange={(event) => setNavigationDepth(event.target.value)} /></label>
            <label>最多导航页<input type="number" min="1" max="20" value={maxNavigationPages} onChange={(event) => setMaxNavigationPages(event.target.value)} /></label>
          </div>
          <div className="action-row">
            <button type="button" className="secondary" onClick={() => runBrowserResearch(false)} disabled={loading === 'research'}>
              {loading === 'research' ? '深度研究中...' : '自动搜索并入库'}
            </button>
            <button type="button" className="ghost" onClick={() => runBrowserResearch(true)} disabled={loading === 'research-preview'}>
              {loading === 'research-preview' ? '预检中...' : '仅预检不入库'}
            </button>
            <button type="button" className="ghost" onClick={loadSeedSites} disabled={loading === 'seed-sites'}>
              {loading === 'seed-sites' ? '匹配中...' : '预览高校入口'}
            </button>
          </div>
          <SeedSitePreview sites={seedSites} />
          <QualityReport data={researchResult?.quality_report} dryRun={researchResult?.dry_run} />
          <pre>{researchResult ? JSON.stringify({ mode: researchResult.dry_run ? '仅预检，不写库' : '搜索并入库', trace_id: researchResult.trace_id, rewritten_queries: researchResult.rewritten_queries, quality_report: researchResult.quality_report, tutors: researchResult.tutors?.map((item) => item.name) }, null, 2) : '等待 Browser Research 结果...'}</pre>
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

      <CapabilityPanel data={capabilities} />

      <RagEvaluationPanel
        dataset={ragDataset}
        comparison={ragComparison}
        configurations={ragConfigurations}
        loading={loading === 'rag-eval'}
        onLoad={loadRagEvaluation}
      />

      <TutorAuditPanel data={tutorAudit} loading={loading === 'tutor-audit'} onLoad={loadTutorAudit} />

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
        {activeTab === 'tutors' && <TutorView items={[...(chatResult?.tutors || []), ...(urlPreviewResult?.tutor ? [urlPreviewResult.tutor] : []), ...(urlIngestResult?.tutor ? [urlIngestResult.tutor] : []), ...(researchResult?.tutors || [])]} />}
      </section>
    </div>
  )
}

function Stat({ label, value, danger }) {
  return <div className={danger ? 'stat danger' : 'stat'}><span>{label}</span><strong>{value}</strong></div>
}

function CapabilityPanel({ data }) {
  if (!data) {
    return <section className="panel"><h2>系统能力概览</h2><p className="empty">正在加载系统能力...</p></section>
  }
  return (
    <section className="panel">
      <h2>系统能力概览</h2>
      <div className="capability-grid">
        {data.capabilities.map((item) => (
          <article className="card" key={item.name}>
            <strong>{item.name}</strong>
            <p>{item.features.join('、')}</p>
          </article>
        ))}
      </div>
      <h3>推荐下一步</h3>
      <ul className="next-steps">
        {data.next_recommended_steps.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  )
}

function TutorAuditPanel({ data, loading, onLoad }) {
  const issues = data?.issues || []
  return (
    <section className="panel audit-panel">
      <div className="panel-heading">
        <div>
          <h2>导师数据质量审计</h2>
          <p>检查当前 SQLite 导师库是否存在搜索页、噪声姓名、缺少主页或缺少研究方向等无效数据。</p>
        </div>
        <button type="button" onClick={onLoad} disabled={loading}>{loading ? '审计中...' : '运行审计'}</button>
      </div>
      {data ? (
        <>
          <div className="stats rag-stats">
            <Stat label="总数" value={data.total} />
            <Stat label="有效" value={data.valid} />
            <Stat label="无效" value={data.invalid} danger={data.invalid > 0} />
            <Stat label="通过" value={data.quality_passed ? '是' : '否'} danger={!data.quality_passed} />
          </div>
          <small>地区分布：{formatCounts(data.locations)} · 机构分布：{formatCounts(data.institutions)}</small>
          <small>重复姓名：{data.duplicate_names?.join('、') || '无'} · 缺少方向：{data.missing_research_areas?.join('、') || '无'} · 缺少主页：{data.missing_homepage?.join('、') || '无'}</small>
          {issues.length ? (
            <div className="audit-issues">
              {issues.slice(0, 8).map((item) => <article className="card" key={`${item.name}-${item.homepage}`}><strong>{item.name}</strong><p className="url-text">{item.homepage || '无主页'}</p><small>{item.reasons.join('、')}</small></article>)}
            </div>
          ) : <p className="empty audit-empty">未发现无效导师数据</p>}
        </>
      ) : <p className="empty audit-empty">暂无审计结果</p>}
    </section>
  )
}

function RagEvaluationPanel({ dataset, comparison, configurations, loading, onLoad }) {
  const strategies = comparison?.strategies || []
  const configResults = configurations?.configurations || []
  return (
    <section className="panel rag-panel">
      <div className="panel-heading">
        <div>
          <h2>RAG Evaluation</h2>
          <p>对比 baseline、hybrid、reranker 以及不同 chunk 配置的 Recall、Precision、Relevance 和 Faithfulness。</p>
        </div>
        <button type="button" onClick={onLoad} disabled={loading}>{loading ? '评估中...' : '加载评估'}</button>
      </div>
      {dataset ? (
        <div className="stats rag-stats">
          <Stat label="评测用例" value={dataset.case_count} />
          <Stat label="期望导师" value={dataset.expected_tutor_count} />
          <Stat label="覆盖地区" value={dataset.covered_locations.length} />
          <Stat label="研究主题" value={dataset.covered_research_terms.length} />
        </div>
      ) : <Empty text="暂无评估数据集摘要" />}
      <EvaluationTable title="策略对比" items={strategies} />
      <EvaluationTable title="配置对比" items={configResults} showConfig />
    </section>
  )
}

function EvaluationTable({ title, items, showConfig = false }) {
  if (!items.length) return <div className="eval-section"><h3>{title}</h3><Empty text="暂无评估结果" /></div>
  return (
    <div className="eval-section">
      <h3>{title}</h3>
      <div className="eval-table">
        <div className="eval-row header"><span>配置</span><span>Recall</span><span>Precision</span><span>Relevance</span><span>Faithfulness</span></div>
        {items.map((item, index) => (
          <div className="eval-row" key={`${title}-${item.strategy}-${index}`}>
            <span>{showConfig ? formatConfig(item) : item.strategy}</span>
            <span>{formatMetric(item.recall)}</span>
            <span>{formatMetric(item.precision)}</span>
            <span>{formatMetric(item.relevance)}</span>
            <span>{formatMetric(item.faithfulness)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function formatConfig(item) {
  const config = item.config || {}
  return `${config.retrieval_strategy || item.strategy} · chunk ${config.chunk_size || '-'} / ${config.chunk_overlap || 0}`
}

function formatMetric(value) {
  return Number(value ?? 0).toFixed(4)
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

function SeedSitePreview({ sites }) {
  if (sites === null) return <p className="empty seed-empty">暂无高校入口预览</p>
  if (!sites.length) return <p className="empty seed-empty">未匹配到高校入口</p>
  return (
    <div className="seed-sites">
      <h3>匹配高校入口</h3>
      {sites.map((site) => (
        <article className="card" key={site.url}>
          <strong>{site.name}</strong>
          <p>{site.location} · {site.institution}</p>
          <small>score {site.score} · {site.tags?.join('、') || '无标签'}</small>
          <p>{site.reason || '默认高校入口'} · 匹配词：{site.matched_terms?.join('、') || '无'}</p>
          <p className="url-text">{site.url}</p>
        </article>
      ))}
    </div>
  )
}

function UrlPreviewCard({ data }) {
  if (!data) return <p className="empty seed-empty">暂无 URL 预检结果</p>
  return (
    <div className="quality-report url-preview-card">
      <h3>URL 预检结果 · {data.ingest_eligible ? '可入库' : '不建议入库'}</h3>
      <div className="stats rag-stats">
        <Stat label="档案质量" value={Number(data.profile_quality_score || 0).toFixed(2)} />
        <Stat label="页面质量" value={Number(data.page_quality || 0).toFixed(2)} />
        <Stat label="可入库" value={data.ingest_eligible ? '是' : '否'} danger={!data.ingest_eligible} />
        <Stat label="已写库" value={data.indexed ? '是' : '否'} />
      </div>
      <small>导师：{data.tutor?.name || '未识别'} · {data.tutor?.institution || '未知机构'} · {data.tutor?.research_areas?.join('、') || '未识别方向'}</small>
      <small className={data.ingest_eligible ? 'quality-pass' : 'quality-reject'}>质量说明：{data.quality_reasons?.join('、') || '无'}</small>
    </div>
  )
}

function QualityReport({ data, dryRun }) {
  if (!data) return <p className="empty seed-empty">暂无候选质量报告</p>
  return (
    <div className="quality-report">
      <h3>候选质量报告 · {dryRun ? '仅预检' : '入库模式'}</h3>
      <div className="stats rag-stats">
        <Stat label="候选总数" value={data.total_candidates} />
        <Stat label="可入库" value={data.eligible_candidates} />
        <Stat label="已拒绝" value={data.rejected_candidates} danger={data.rejected_candidates > 0} />
        <Stat label="平均质量" value={Number(data.average_profile_quality_score || 0).toFixed(2)} />
      </div>
      <small>状态分布：{formatCounts(data.status_counts)} · 类型分布：{formatCounts(data.link_type_counts)}</small>
      <small>主要拒绝原因：{formatCounts(data.rejection_reasons)}</small>
    </div>
  )
}

function formatCounts(value) {
  return Object.entries(value || {}).map(([key, count]) => `${key}:${count}`).join('、') || '无'
}

function CandidateView({ items }) {
  if (!items.length) return <Empty text="暂无候选链路" />
  return items.map((item) => {
    const reasons = item.quality_reasons?.length ? item.quality_reasons.join('、') : item.error || '暂无质量说明'
    return (
      <article className="row candidate-row" key={item.url}>
        <Badge value={item.status || item.link_type} />
        <div>
          <strong>{item.text || item.url}</strong>
          <p className="url-text">{item.url}</p>
          <small>类型 {item.link_type} · depth {item.depth} · confidence {item.confidence} · 链接分 {item.score}</small>
          <small>页面质量 {item.page_quality} · 档案质量 {item.profile_quality_score} · 可入库 {item.ingest_eligible ? '是' : '否'}</small>
          <small>来源原因：{item.reason || '无'}</small>
          <small className={item.ingest_eligible ? 'quality-pass' : 'quality-reject'}>质量说明：{reasons}</small>
        </div>
      </article>
    )
  })
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

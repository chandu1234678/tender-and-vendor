import { useEffect, useMemo, useRef, useState } from 'react'
import {
  API_BASE,
  downloadAllReports,
  downloadOutputFile,
  getFiles,
  getOllamaStatus,
  getOutputFiles,
  getResults,
  getRuns,
  getStatus,
  getSummary,
  resetPipeline,
  runPipeline,
  uploadFiles,
} from './api'

/* ─── helpers ───────────────────────────────────────────────────────────── */
function fmtElapsed(ms) {
  if (ms < 1000) return `${ms}ms`
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

function StatusBadge({ status }) {
  const map = {
    idle:      { label: 'Idle',      cls: 'badge-idle' },
    queued:    { label: 'Queued',    cls: 'badge-queued' },
    running:   { label: 'Running',   cls: 'badge-running' },
    completed: { label: 'Completed', cls: 'badge-done' },
    failed:    { label: 'Failed',    cls: 'badge-fail' },
    unknown:   { label: 'Unknown',   cls: 'badge-idle' },
  }
  const { label, cls } = map[status] ?? map.unknown
  return <span className={`status-badge ${cls}`}>{label}</span>
}

function ProgressBar({ value, status }) {
  const pct = Math.min(100, Math.max(0, Number(value) || 0))
  const cls =
    status === 'completed' ? 'bar-fill bar-done' :
    status === 'failed'    ? 'bar-fill bar-fail' :
    status === 'running'   ? 'bar-fill bar-running' :
                             'bar-fill bar-idle'
  return (
    <div className="progress-track" role="progressbar"
      aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className={cls} style={{ width: `${pct}%` }} />
      <span className="progress-label">{pct.toFixed(1)}%</span>
    </div>
  )
}

/* ─── main component ────────────────────────────────────────────────────── */
export default function App() {
  const [masterFile, setMasterFile] = useState(null)
  const [vendorFiles, setVendorFiles] = useState([])
  const [files, setFiles] = useState([])
  const [outputFiles, setOutputFiles] = useState([])
  const [summary, setSummary] = useState(null)
  const [results, setResults] = useState([])
  const [runHistory, setRunHistory] = useState([])
  const [ollamaStatus, setOllamaStatus] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [runId, setRunId] = useState('')
  const [runStatus, setRunStatus] = useState('idle')
  const [runProgress, setRunProgress] = useState(0)
  const [runMessage, setRunMessage] = useState('')
  const [elapsed, setElapsed] = useState(0)

  const startTimeRef = useRef(null)
  const elapsedTimerRef = useRef(null)
  const selectedCount = useMemo(() => vendorFiles.filter(Boolean).length, [vendorFiles])
  const isActive = ['queued', 'running'].includes(runStatus)

  /* elapsed wall-clock timer — runs whenever pipeline is active */
  useEffect(() => {
    if (isActive) {
      if (!startTimeRef.current) startTimeRef.current = Date.now()
      elapsedTimerRef.current = window.setInterval(
        () => setElapsed(Date.now() - startTimeRef.current), 500)
    } else {
      window.clearInterval(elapsedTimerRef.current)
      // keep final elapsed visible after completion/failure
    }
    return () => window.clearInterval(elapsedTimerRef.current)
  }, [isActive])

  /* poll pipeline status every 1.5 s whenever we have a runId */
  useEffect(() => {
    if (!runId) return undefined
    const poll = window.setInterval(async () => {
      try {
        const p = await getStatus(runId)
        const newStatus = p.status || 'unknown'
        setRunStatus(newStatus)
        setRunProgress(Number(p.progress || 0))
        setRunMessage(p.message || p.error || '')
        if (newStatus === 'completed') {
          await refreshDashboard()
          window.clearInterval(poll)
        }
        if (newStatus === 'failed') {
          refreshRunHistory()
          window.clearInterval(poll)
        }
      } catch (e) { setError(e.message) }
    }, 1500)
    return () => window.clearInterval(poll)
  }, [runId])

  useEffect(() => { refreshDashboard() }, [])

  async function refreshDashboard() {
    try {
      const [fp, sp, rp, op, os] = await Promise.all([
        getFiles(), getSummary(), getResults({ limit: 10 }), getOutputFiles(), getOllamaStatus(),
      ])
      setFiles(fp.incoming || [])
      setSummary(sp)
      setResults(rp.results || [])
      setOutputFiles(op.files || [])
      setOllamaStatus(os)
      refreshRunHistory()
    } catch (_) {}
  }

  async function refreshRunHistory() {
    try {
      const p = await getRuns({ limit: 8 })
      setRunHistory(Array.isArray(p) ? p : [])
    } catch (_) {}
  }

  /* file helpers */
  function addVendorRow() { setVendorFiles(c => [...c, null]) }
  function updateVendorFile(i, f) { setVendorFiles(c => c.map((e, p) => p === i ? f : e)) }
  function removeVendorRow(i) { setVendorFiles(c => c.filter((_, p) => p !== i)) }

  /* actions */
  async function handleUpload() {
    setError(''); setMessage('')
    if (!masterFile) return setError('Choose one .xlsx master workbook first.')
    if (!selectedCount) return setError('Add at least one vendor PDF.')
    setBusy(true)
    try {
      const p = await uploadFiles([masterFile, ...vendorFiles.filter(Boolean)])
      setMessage(`Uploaded ${p.saved.length} file(s).`)
      await refreshDashboard()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function handleRunPipeline() {
    setError(''); setMessage(''); setBusy(true)
    try {
      const p = await runPipeline()
      setRunId(p.run_id)
      setRunStatus(p.status || 'queued')
      setRunProgress(0); setRunMessage('Queued')
      startTimeRef.current = Date.now(); setElapsed(0)
      setMessage('Pipeline started.')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function handleResetPipeline() {
    setError(''); setMessage(''); setBusy(true)
    try {
      const p = await resetPipeline()
      setMessage(`Pipeline reset. Cleared ${p.cleared} stuck run(s).`)
      setRunStatus('idle'); setRunId(''); setRunProgress(0); setRunMessage('')
      startTimeRef.current = null; setElapsed(0)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  function _dl(blob, filename) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename
    document.body.appendChild(a); a.click(); a.remove()
    URL.revokeObjectURL(url)
  }

  async function handleDownloadFile(fileName) {
    setError(''); setMessage(''); setBusy(true)
    try { _dl(await downloadOutputFile(fileName), fileName); setMessage(`Downloaded ${fileName}`) }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function handleDownloadAll() {
    setError(''); setMessage(''); setBusy(true)
    try { _dl(await downloadAllReports(), 'compliance_reports.zip'); setMessage('All reports downloaded as ZIP.') }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  /* derive human phase label from raw backend message */
  function phaseLabel() {
    const m = (runMessage || '').toLowerCase()
    if (!m) return ''
    if (m.includes('loaded') && m.includes('specs'))    return `Phase 0 — ${runMessage}`
    if (m.includes('parsing pdf'))                       return `Phase 1 — ${runMessage}`
    if (m.includes('parsed'))                            return `Phase 1 — ${runMessage}`
    if (m.includes('evaluating pair'))                   return `Phase 2 — ${runMessage}`
    if (m.includes('evaluated'))                         return `Phase 2 — ${runMessage}`
    if (m.includes('skipped') && m.includes('cached'))  return `Phase 2 — ${runMessage}`
    if (m.includes('building') || m.includes('report')) return `Phase 3 — ${runMessage}`
    if (m.includes('completed'))                         return `✓ ${runMessage}`
    if (m.includes('failed'))                            return `✗ ${runMessage}`
    if (m.includes('queue'))                             return 'Queued — waiting to start'
    return runMessage
  }

  /* ── render ── */
  return (
    <div className="app-shell">
      <main className="workspace">

        {/* topbar */}
        <header className="topbar">
          <div>
            <p className="eyebrow">Tender &amp; Vendor Compliance</p>
            <h1>Compliance Pipeline Console</h1>
          </div>
          <div className="topbar-right">
            {ollamaStatus && (
              <div className={`ollama-chip ${ollamaStatus.healthy ? 'ollama-ok' : 'ollama-down'}`}
                title={ollamaStatus.healthy ? `Models: ${ollamaStatus.models.join(', ')}` : 'LLM server not reachable — using heuristic fallback'}>
                <span className="ollama-dot" />
                {ollamaStatus.healthy
                  ? `LLM · ${ollamaStatus.selected_model || ollamaStatus.models[0] || 'ready'}`
                  : 'LLM offline'}
              </div>
            )}
            <div className="api-chip">{API_BASE}</div>
          </div>
        </header>

        {/* ── pipeline progress card ── */}
        <section className="pipeline-card" aria-label="Pipeline status">
          <div className="pipeline-card__header">
            <div className="pipeline-card__title">
              <span className="pipeline-card__label">Pipeline</span>
              <StatusBadge status={runStatus} />
            </div>
            <div className="pipeline-card__meta">
              {elapsed > 0 && (
                <span className="pipeline-card__elapsed">⏱ {fmtElapsed(elapsed)}</span>
              )}
              <button className="plain-button" type="button"
                onClick={refreshDashboard} disabled={busy}>Refresh</button>
            </div>
          </div>

          <ProgressBar value={runProgress} status={runStatus} />

          {phaseLabel() && (
            <p className="pipeline-card__phase">{phaseLabel()}</p>
          )}

          {/* step indicators */}
          <div className="pipeline-steps">
            {[
              { key: 'upload',   label: 'Upload',   done: files.length > 0 },
              { key: 'parse',    label: 'Parse',    done: runProgress > 5 },
              { key: 'evaluate', label: 'Evaluate', done: runProgress > 50 },
              { key: 'report',   label: 'Report',   done: runStatus === 'completed' },
            ].map((step, i) => (
              <div key={step.key}
                className={`pipeline-step ${step.done ? 'step-done' : isActive ? 'step-active' : 'step-pending'}`}>
                <div className="step-dot">{step.done ? '✓' : i + 1}</div>
                <span className="step-label">{step.label}</span>
              </div>
            ))}
          </div>

          {runId && (
            <p className="pipeline-card__runid">Run ID: <code>{runId}</code></p>
          )}
        </section>

        {/* ── upload + incoming ── */}
        <section className="grid-two">
          <div className="panel">
            <h2>Upload</h2>
            <label className="field-label" htmlFor="master-file">Master workbook (.xlsx)</label>
            <input id="master-file" className="file-input" type="file" accept=".xlsx"
              onChange={(e) => setMasterFile(e.target.files?.[0] || null)} />
            <div className="file-name">
              {masterFile ? masterFile.name : 'No master workbook selected'}
            </div>

            <div className="row-between compact-row">
              <label className="field-label">Vendor PDFs</label>
              <button className="plain-button" type="button" onClick={addVendorRow}>+ Add File</button>
            </div>

            <div className="vendor-list">
              {vendorFiles.length ? vendorFiles.map((file, index) => (
                <div className="vendor-row" key={`vendor-${index}`}>
                  <input className="file-input" type="file" accept=".pdf"
                    onChange={(e) => updateVendorFile(index, e.target.files?.[0] || null)} />
                  <div className="file-name">
                    {file ? file.name : `Vendor ${index + 1}: no file selected`}
                  </div>
                  <button className="plain-button danger" type="button"
                    onClick={() => removeVendorRow(index)}>Remove</button>
                </div>
              )) : <div className="empty-line">No vendor files added yet.</div>}
            </div>

            <div className="actions">
              <button className="solid-button" type="button"
                onClick={handleUpload} disabled={busy}>Upload Files</button>
              <button className="solid-button inverse" type="button"
                onClick={handleRunPipeline} disabled={busy || isActive}>Run Pipeline</button>
              <button className="plain-button danger" type="button"
                onClick={handleResetPipeline} disabled={busy}
                title="Clear any stuck pipeline run">Reset Pipeline</button>
            </div>
          </div>

          <div className="panel">
            <h2>Incoming Files</h2>
            <div className="file-table">
              {files.length ? files.map((file) => (
                <div className="file-row" key={file.file_name}>
                  <strong>{file.file_name}</strong>
                  <span>{file.role}</span>
                  <span>{Math.round(file.size_bytes / 1024)} KB</span>
                </div>
              )) : <div className="empty-line">No incoming files loaded.</div>}
            </div>
          </div>
        </section>

        {/* ── summary + results ── */}
        <section className="grid-two">
          <div className="panel">
            <h2>Summary</h2>
            {summary ? (
              <div className="summary-grid">
                <div><span className="muted">Total</span><strong>{summary.total_results}</strong></div>
                {Object.entries(summary.status_counts || {}).map(([s, c]) => (
                  <div key={s}><span className="muted">{s}</span><strong>{c}</strong></div>
                ))}
              </div>
            ) : <div className="empty-line">No summary loaded.</div>}
          </div>

          <div className="panel">
            <h2>Latest Results</h2>
            <div className="result-list">
              {results.length ? results.map((row) => (
                <div className="result-row" key={`${row.spec_id}-${row.vendor_id}`}>
                  <strong>{row.spec_id}</strong>
                  <span>{row.vendor_id}</span>
                  <span className={`verdict verdict-${(row.status || '').toLowerCase().replace(/\s/g, '-')}`}>
                    {row.status}
                  </span>
                </div>
              )) : <div className="empty-line">No result rows loaded.</div>}
            </div>
          </div>
        </section>

        {/* ── run history ── */}
        {runHistory.length > 0 && (
          <section className="panel section-block">
            <h2>Run History</h2>
            <div className="run-history">
              <div className="run-history__head">
                <span>Run ID</span><span>Status</span>
                <span>Progress</span><span>Message</span><span>Updated</span>
              </div>
              {runHistory.map((r) => (
                <div className="run-history__row" key={r.run_id}>
                  <code className="run-id-short" title={r.run_id}>{r.run_id.slice(0, 8)}…</code>
                  <StatusBadge status={r.status} />
                  <div className="run-mini-bar">
                    <div className="run-mini-fill"
                      style={{ width: `${Math.min(100, r.progress || 0)}%` }} />
                    <span>{(r.progress || 0).toFixed(0)}%</span>
                  </div>
                  <span className="run-msg" title={r.message}>
                    {(r.message || '').slice(0, 42)}{(r.message || '').length > 42 ? '…' : ''}
                  </span>
                  <span className="run-time">
                    {(r.updated_at || '').slice(0, 16).replace('T', ' ')}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── downloads ── */}
        <section className="panel section-block">
          <div className="row-between">
            <h2>Downloads</h2>
            <button className="solid-button" type="button"
              onClick={handleDownloadAll} disabled={busy || !outputFiles.length}>
              ⬇ Download All (ZIP)
            </button>
          </div>
          {outputFiles.length ? (
            <div className="file-table">
              {outputFiles.map((f) => {
                const isVendor = f.file_name.startsWith('vendor_') &&
                  f.file_name !== 'vendor_comparison_matrix.xlsx'
                const vendorId = isVendor
                  ? f.file_name.replace(/^vendor_/, '').replace(/\.xlsx$/, '') : null
                return (
                  <div className="file-row" key={f.file_name}>
                    <strong>{f.file_name}</strong>
                    <span>{Math.round(f.size_bytes / 1024)} KB</span>
                    <span className="muted">{f.modified_at.slice(0, 16).replace('T', ' ')}</span>
                    <div className="row-actions">
                      <button className="plain-button" type="button" disabled={busy}
                        onClick={() => handleDownloadFile(f.file_name)}>
                        ⬇ Download
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="empty-line">No output files yet. Run the pipeline first.</div>
          )}
        </section>

        {/* ── messages ── */}
        {(message || error) && (
          <section className="section-block status-block">
            {message && <div className="message success">{message}</div>}
            {error   && <div className="message error">{error}</div>}
          </section>
        )}

      </main>
    </div>
  )
}

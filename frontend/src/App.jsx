import { useEffect, useMemo, useState } from 'react'
import {
  API_BASE,
  downloadReport,
  getCurrentUser,
  getFiles,
  getResults,
  getStatus,
  getSummary,
  login,
  runPipeline,
  uploadFiles,
} from './api'

const TOKEN_KEY = 'vendor-token'

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) || '')
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [user, setUser] = useState(null)
  const [masterFile, setMasterFile] = useState(null)
  const [vendorFiles, setVendorFiles] = useState([])
  const [files, setFiles] = useState([])
  const [summary, setSummary] = useState(null)
  const [results, setResults] = useState([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [runId, setRunId] = useState('')
  const [runStatus, setRunStatus] = useState('idle')
  const [runProgress, setRunProgress] = useState(0)
  const [runMessage, setRunMessage] = useState('')

  const selectedCount = useMemo(() => vendorFiles.filter(Boolean).length, [vendorFiles])
  const isAuthed = Boolean(token && user)

  useEffect(() => {
    if (!token) {
      setUser(null)
      return
    }
    let cancelled = false
    getCurrentUser(token)
      .then((payload) => {
        if (!cancelled) setUser(payload)
      })
      .catch(() => {
        if (!cancelled) {
          sessionStorage.removeItem(TOKEN_KEY)
          setToken('')
          setUser(null)
        }
      })
    return () => {
      cancelled = true
    }
  }, [token])

  useEffect(() => {
    if (!token || !runId || ['completed', 'failed'].includes(runStatus)) return undefined
    const poll = window.setInterval(async () => {
      try {
        const payload = await getStatus(token, runId)
        setRunStatus(payload.status || 'unknown')
        setRunProgress(Number(payload.progress || 0))
        setRunMessage(payload.message || payload.error || '')
        if (payload.status === 'completed') {
          await refreshDashboard(token)
        }
      } catch (err) {
        setError(err.message)
      }
    }, 2500)
    return () => window.clearInterval(poll)
  }, [token, runId, runStatus])

  async function refreshDashboard(activeToken = token) {
    if (!activeToken) return
    const [filePayload, summaryPayload, resultPayload] = await Promise.all([
      getFiles(activeToken),
      getSummary(activeToken),
      getResults(activeToken, { limit: 10 }),
    ])
    setFiles(filePayload.incoming || [])
    setSummary(summaryPayload)
    setResults(resultPayload.results || [])
  }

  async function handleLogin(event) {
    event.preventDefault()
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const payload = await login(username, password)
      sessionStorage.setItem(TOKEN_KEY, payload.access_token)
      setToken(payload.access_token)
      setMessage('Signed in.')
      await refreshDashboard(payload.access_token)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function handleLogout() {
    sessionStorage.removeItem(TOKEN_KEY)
    setToken('')
    setUser(null)
    setMessage('')
    setError('')
  }

  function addVendorRow() {
    setVendorFiles((current) => [...current, null])
  }

  function updateVendorFile(index, file) {
    setVendorFiles((current) => current.map((entry, position) => (position === index ? file : entry)))
  }

  function removeVendorRow(index) {
    setVendorFiles((current) => current.filter((_, position) => position !== index))
  }

  async function handleUpload() {
    setError('')
    setMessage('')
    if (!masterFile) {
      setError('Choose one .xlsx master workbook first.')
      return
    }
    if (!selectedCount) {
      setError('Add at least one vendor PDF.')
      return
    }
    setBusy(true)
    try {
      const payload = await uploadFiles(token, [masterFile, ...vendorFiles.filter(Boolean)])
      setMessage(`Uploaded ${payload.saved.length} file(s).`)
      await refreshDashboard()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleRunPipeline() {
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const payload = await runPipeline(token)
      setRunId(payload.run_id)
      setRunStatus(payload.status || 'queued')
      setRunProgress(0)
      setRunMessage('Queued')
      setMessage('Pipeline started.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleDownloadReport() {
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const blob = await downloadReport(token)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'vendor_comparison_matrix.xlsx'
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setMessage('Report download started.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app-shell">
      <main className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Tender & Vendor Compliance</p>
            <h1>Compliance Pipeline Console</h1>
          </div>
          <div className="api-chip">{API_BASE}</div>
        </header>

        {!isAuthed ? (
          <form className="auth-panel" onSubmit={handleLogin}>
            <label className="field-label" htmlFor="username">Username</label>
            <input id="username" value={username} onChange={(event) => setUsername(event.target.value)} />
            <label className="field-label" htmlFor="password">Password</label>
            <input id="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
            <button className="solid-button" type="submit" disabled={busy}>Sign In</button>
          </form>
        ) : (
          <>
            <section className="status-strip">
              <div><span className="muted">User</span><strong>{user.username}</strong></div>
              <div><span className="muted">Run</span><strong>{runStatus}</strong></div>
              <div><span className="muted">Progress</span><strong>{runProgress}%</strong></div>
              <button className="plain-button" type="button" onClick={() => refreshDashboard()} disabled={busy}>Refresh</button>
              <button className="plain-button" type="button" onClick={handleLogout}>Sign Out</button>
            </section>

            <section className="grid-two">
              <div className="panel">
                <h2>Upload</h2>
                <label className="field-label" htmlFor="master-file">Master workbook</label>
                <input
                  id="master-file"
                  className="file-input"
                  type="file"
                  accept=".xlsx"
                  onChange={(event) => setMasterFile(event.target.files?.[0] || null)}
                />
                <div className="file-name">{masterFile ? masterFile.name : 'No master workbook selected'}</div>

                <div className="row-between compact-row">
                  <label className="field-label">Vendor PDFs</label>
                  <button className="plain-button" type="button" onClick={addVendorRow}>Add File</button>
                </div>

                <div className="vendor-list">
                  {vendorFiles.length ? vendorFiles.map((file, index) => (
                    <div className="vendor-row" key={`vendor-${index}`}>
                      <input
                        className="file-input"
                        type="file"
                        accept=".pdf"
                        onChange={(event) => updateVendorFile(index, event.target.files?.[0] || null)}
                      />
                      <div className="file-name">{file ? file.name : `Vendor ${index + 1}: no file selected`}</div>
                      <button className="plain-button danger" type="button" onClick={() => removeVendorRow(index)}>Remove</button>
                    </div>
                  )) : (
                    <div className="empty-line">No vendor files added yet.</div>
                  )}
                </div>

                <div className="actions">
                  <button className="solid-button" type="button" onClick={handleUpload} disabled={busy}>Upload Files</button>
                  <button className="solid-button inverse" type="button" onClick={handleRunPipeline} disabled={busy}>Run Pipeline</button>
                  <button className="plain-button" type="button" onClick={handleDownloadReport} disabled={busy}>Download Report</button>
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

            <section className="grid-two">
              <div className="panel">
                <h2>Summary</h2>
                {summary ? (
                  <div className="summary-grid">
                    <div><span className="muted">Total</span><strong>{summary.total_results}</strong></div>
                    {Object.entries(summary.status_counts || {}).map(([status, count]) => (
                      <div key={status}><span className="muted">{status}</span><strong>{count}</strong></div>
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
                      <span>{row.status}</span>
                    </div>
                  )) : <div className="empty-line">No result rows loaded.</div>}
                </div>
              </div>
            </section>

            <section className="section-block status-block">
              <div><span className="muted">Run ID</span><strong>{runId || '-'}</strong></div>
              {runMessage ? <div><span className="muted">Run message</span><strong>{runMessage}</strong></div> : null}
              {message ? <div className="message success">{message}</div> : null}
              {error ? <div className="message error">{error}</div> : null}
            </section>
          </>
        )}
      </main>
    </div>
  )
}

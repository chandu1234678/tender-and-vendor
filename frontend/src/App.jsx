import { useMemo, useState } from 'react'
import { runPipeline, uploadFiles } from './api'

export default function App() {
  const [masterFile, setMasterFile] = useState(null)
  const [vendorFiles, setVendorFiles] = useState([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [runId, setRunId] = useState('')
  const [runStatus, setRunStatus] = useState('idle')

  const selectedCount = useMemo(() => vendorFiles.filter(Boolean).length, [vendorFiles])

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
      setError('Choose a master workbook first.')
      return
    }
    if (!selectedCount) {
      setError('Add at least one vendor PDF.')
      return
    }
    setBusy(true)
    try {
      const files = [masterFile, ...vendorFiles.filter(Boolean)]
      await uploadFiles(localStorage.getItem('vendor-token') || '', files)
      setMessage(`Uploaded ${files.length} file(s).`)
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
      const payload = await runPipeline(localStorage.getItem('vendor-token') || '')
      setRunId(payload.run_id)
      setRunStatus(payload.status || 'queued')
      setMessage('Pipeline started.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app-shell minimal-shell">
      <main className="minimal-card">
        <div className="header-block">
          <p className="eyebrow">Tender & Vendor Compliance</p>
          <h1>Upload master file and vendor PDFs</h1>
          <p className="intro">
            Minimal black-and-white review flow. Upload the master workbook once, add one or more vendor PDFs, then start the pipeline.
          </p>
        </div>

        <section className="section-block">
          <label className="field-label" htmlFor="master-file">Master workbook</label>
          <input
            id="master-file"
            className="file-input"
            type="file"
            accept=".xlsx,.xlsm,.xls"
            onChange={(event) => setMasterFile(event.target.files?.[0] || null)}
          />
          <div className="file-name">{masterFile ? masterFile.name : 'No master workbook selected'}</div>
        </section>

        <section className="section-block">
          <div className="row-between">
            <label className="field-label">Vendor PDFs</label>
            <button className="plain-button" type="button" onClick={addVendorRow}>
              + Add vendor file
            </button>
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
                <button className="plain-button danger" type="button" onClick={() => removeVendorRow(index)}>
                  Remove
                </button>
              </div>
            )) : (
              <div className="empty-line">No vendor files added yet.</div>
            )}
          </div>
        </section>

        <section className="section-block actions">
          <button className="solid-button" type="button" onClick={handleUpload} disabled={busy}>
            Upload Files
          </button>
          <button className="solid-button inverse" type="button" onClick={handleRunPipeline} disabled={busy}>
            Run Pipeline
          </button>
        </section>

        <section className="section-block status-block">
          <div><span className="muted">Run status</span> <strong>{runStatus}</strong></div>
          <div><span className="muted">Run ID</span> <strong>{runId || '—'}</strong></div>
          {message ? <div className="message success">{message}</div> : null}
          {error ? <div className="message error">{error}</div> : null}
        </section>
      </main>
    </div>
  )
}


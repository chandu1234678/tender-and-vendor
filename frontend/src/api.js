const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8088'

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {})
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed (${response.status})`)
  }
  return response
}

export async function uploadFiles(files) {
  const formData = new FormData()
  for (const file of files) {
    formData.append('files', file)
  }
  const response = await request('/upload', { method: 'POST', body: formData })
  return response.json()
}

export async function getFiles() {
  const response = await request('/files')
  return response.json()
}

export async function resetPipeline() {
  const response = await request('/reset-pipeline', { method: 'POST' })
  return response.json()
}

export async function runPipeline() {
  const response = await request('/run-pipeline', { method: 'POST' })
  return response.json()
}

export async function getRuns({ limit = 25, offset = 0 } = {}) {
  const params = new URLSearchParams({ limit, offset })
  const response = await request(`/runs?${params.toString()}`)
  return response.json()
}

export async function getStatus(runId) {
  const response = await request(`/status/${encodeURIComponent(runId)}`)
  return response.json()
}

export async function getResults(filters = {}) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, value)
    }
  }
  const path = params.toString() ? `/results?${params.toString()}` : '/results'
  const response = await request(path)
  return response.json()
}

export async function getSummary() {
  const response = await request('/summary')
  return response.json()
}

export async function getAuditLog({ limit = 100, offset = 0 } = {}) {
  const params = new URLSearchParams({ limit, offset })
  const response = await request(`/audit-log?${params.toString()}`)
  return response.json()
}

export async function getTrainingQueue({ processed, limit = 100, offset = 0 } = {}) {
  const params = new URLSearchParams({ limit, offset })
  if (processed !== undefined && processed !== null) {
    params.set('processed', processed ? '1' : '0')
  }
  const response = await request(`/training-queue?${params.toString()}`)
  return response.json()
}

export async function getParsedDocument(docId) {
  const response = await request(`/parsed-document/${encodeURIComponent(docId)}`)
  return response.json()
}

export async function getPdfObjectUrl(fileName) {
  const response = await request(`/pdf/${encodeURIComponent(fileName)}`)
  const blob = await response.blob()
  return URL.createObjectURL(blob)
}

export async function applyOverride(payload) {
  const response = await request('/override', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return response.json()
}

export async function downloadReport() {
  const response = await request('/report')
  return response.blob()
}

export async function downloadAllReports() {
  const response = await request('/report/all')
  return response.blob()
}

export async function downloadVendorReport(vendorId) {
  const response = await request(`/report/vendor/${encodeURIComponent(vendorId)}`)
  return response.blob()
}

export async function downloadOutputFile(fileName) {
  const response = await request(`/output/${encodeURIComponent(fileName)}`)
  return response.blob()
}

export async function getOllamaStatus() {
  const response = await request('/ollama-status')
  return response.json()
}

export async function getOutputFiles() {
  const response = await request('/output-files')
  return response.json()
}

export { API_BASE }

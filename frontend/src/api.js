const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

async function request(path, options = {}, token = '') {
  const headers = new Headers(options.headers || {})
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
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

export async function login(username, password) {
  const body = new URLSearchParams()
  body.set('username', username)
  body.set('password', password)
  const response = await fetch(`${API_BASE}/token`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || 'Login failed')
  }
  return response.json()
}

export async function uploadFiles(token, files) {
  const formData = new FormData()
  for (const file of files) {
    formData.append('files', file)
  }
  const response = await request('/upload', { method: 'POST', body: formData }, token)
  return response.json()
}

export async function runPipeline(token) {
  const response = await request('/run-pipeline', { method: 'POST' }, token)
  return response.json()
}

export async function getStatus(token, runId) {
  const response = await request(`/status/${encodeURIComponent(runId)}`, {}, token)
  return response.json()
}

export async function getResults(token) {
  const response = await request('/results', {}, token)
  return response.json()
}

export async function getParsedDocument(token, docId) {
  const response = await request(`/parsed-document/${encodeURIComponent(docId)}`, {}, token)
  return response.json()
}

export async function getPdfObjectUrl(token, fileName) {
  const response = await request(`/pdf/${encodeURIComponent(fileName)}`, {}, token)
  const blob = await response.blob()
  return URL.createObjectURL(blob)
}

export async function applyOverride(token, payload) {
  const response = await request('/override', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  }, token)
  return response.json()
}

export async function downloadReport(token) {
  const response = await request('/report', {}, token)
  return response.blob()
}

export { API_BASE }

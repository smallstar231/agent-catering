// AI 管理后台 API 封装：直连 Python Agent 服务(:8000)
// 与 ai-chat 页相同的模式（fetch 到 http://localhost:8000），供 AI配置页各子页复用。
const AI_BASE = 'http://localhost:8000'

// AI 管理接口鉴权 token（后端 opt-in：.env 配 AI_ADMIN_TOKEN 后强制校验 X-AI-Admin-Token 头）
// 前端从构建环境 VUE_APP_AI_ADMIN_TOKEN 读取（本地可在 .env.development.local 配置，不入库）。
const AI_ADMIN_TOKEN: string = (process.env.VUE_APP_AI_ADMIN_TOKEN || '').trim()

async function req(path: string, options: RequestInit = {}) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (AI_ADMIN_TOKEN) headers['X-AI-Admin-Token'] = AI_ADMIN_TOKEN
  const res = await fetch(`${AI_BASE}${path}`, {
    headers,
    ...options
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => '')
    throw new Error(`${path} ${res.status}: ${txt.slice(0, 120)}`)
  }
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

export const getAiConfig = () => req('/ai/config')
export const getModelOptions = () => req('/ai/model-options')
export const putAiConfig = (items: Array<{ file: string; path: string; value: any }>) =>
  req('/ai/config', { method: 'PUT', body: JSON.stringify({ items }) })

export const getAiKb = () => req('/ai/kb')
export const getAiFaq = () => req('/ai/faq')

// 上传知识文件入库（FormData：scene + kind + file）
export const uploadKbFile = (scene: string, kind: string, file: File) => {
  const fd = new FormData()
  fd.append('scene', scene)
  fd.append('kind', kind)
  fd.append('file', file, file.name)
  const headers: Record<string, string> = {}
  if (AI_ADMIN_TOKEN) headers['X-AI-Admin-Token'] = AI_ADMIN_TOKEN
  return fetch(`${AI_BASE}/ai/kb/upload`, { method: 'POST', body: fd, headers }).then(async (res) => {
    if (!res.ok) {
      const txt = await res.text().catch(() => '')
      throw new Error(`${res.status}: ${txt.slice(0, 120)}`)
    }
    return res.json()
  })
}

export const getAiSessions = (user_id?: string) =>
  req(`/ai/sessions${user_id ? `?user_id=${user_id}` : ''}`)
export const deleteAiSession = (session_id: string, user_id?: string) =>
  req(`/ai/sessions/${session_id}${user_id ? `?user_id=${user_id}` : ''}`, { method: 'DELETE' })

export const getAiEvalSample = () => req('/ai/eval/sample')
export const postAiEval = (body: { limit?: number; category?: string; dataset_path?: string }) =>
  req('/ai/eval', { method: 'POST', body: JSON.stringify(body) })

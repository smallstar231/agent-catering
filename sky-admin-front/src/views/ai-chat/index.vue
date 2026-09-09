<template>
  <div class="dashboard-container">
    <div class="chat-layout">
      <!-- === 侧边栏（可展开/收缩） === -->
      <div class="sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div class="sidebar-header">
          <template v-if="!sidebarCollapsed">
            <div class="sidebar-title" style="padding-right: 32px;">💬 AI 智能客服</div>
            <button class="new-chat-btn" @click="newChat">🔄 新对话</button>
          </template>
          <button class="toggle-btn" :class="{ 'toggle-corner': !sidebarCollapsed }" @click="sidebarCollapsed = !sidebarCollapsed">
            {{ sidebarCollapsed ? '☰' : '✕' }}
          </button>
        </div>
        <div class="sidebar-body" v-if="!sidebarCollapsed">
          <!-- 当前会话信息 -->
          <div class="current-session-info">
            <span class="round-badge">已对话 {{ roundCount }} 轮</span>
          </div>
          <!-- 历史会话（可展收） -->
          <div class="history-section">
            <div class="history-header" @click="historyExpanded = !historyExpanded">
              <span>{{ historyExpanded ? '▾' : '▸' }} 历史会话</span>
              <span class="history-count">{{ sessions.length }}</span>
            </div>
            <div v-show="historyExpanded" class="history-list">
              <div
                v-for="s in sessions"
                :key="s.id"
                class="session-item"
                :class="{ active: s.id === currentSessionId }"
                @click="switchToSession(s)"
              >
                <div class="session-title">{{ s.title }}</div>
                <div class="session-meta">{{ s.round_count }} 轮 · {{ formatTime(s.updated_at) }}</div>
              </div>
              <div v-if="!sessions.length" class="no-sessions">暂无历史会话</div>
            </div>
          </div>
        </div>
      </div>

      <!-- === 聊天区 === -->
      <div class="chat-main">
        <!-- 消息列表 -->
        <div class="message-list" ref="messageList">
          <div v-for="(msg, i) in messages" :key="i" class="message-item"
               :class="{ 'message-user': msg.role === 'user', 'message-ai': msg.role === 'assistant' }">
            <div class="message-avatar">{{ msg.role === 'user' ? '🧑' : '🤖' }}</div>
            <div class="message-content">
              <div class="message-role">{{ msg.role === 'user' ? '我' : 'AI 客服' }}</div>
              <div class="message-bubble" :class="{ 'bubble-user': msg.role === 'user' }">
                <!-- 工具调用轨迹（仅最新一条 assistant、且当轮确实调了工具时显示） -->
                <div v-if="msg.role === 'assistant' && i === messages.length - 1 && currentToolCalls.length" class="tool-track">
                  <span v-for="(t, ti) in currentToolCalls" :key="'t' + ti" class="tool-chip">⚙ {{ t }}</span>
                </div>
                <span v-if="msg.role === 'assistant' && i === messages.length - 1 && !msg.content && isStreaming" class="loading-dots">
                  <span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>
                </span>
                <template v-else>
                  <template v-for="(seg, si) in contentSegments(msg.content)">
                    <img
                      v-if="seg.type === 'img'"
                      :key="'i' + si"
                      class="chat-img"
                      :src="seg.v"
                      @click="openImg(seg.v)"
                    />
                    <a
                      v-else-if="seg.type === 'file'"
                      :key="'f' + si"
                      class="chat-file"
                      :href="seg.v"
                      target="_blank"
                      rel="noopener noreferrer"
                    >📄 {{ seg.name }}</a>
                    <span v-else :key="'t' + si">{{ seg.v }}</span>
                  </template>
                </template>
                <!-- 引用来源 chips（最新一条 assistant、且带来源时显示） -->
                <div v-if="msg.role === 'assistant' && i === messages.length - 1 && currentSources.length" class="source-track">
                  <span class="source-label">📎 参考</span>
                  <span v-for="(s, si) in currentSources" :key="'s' + si" class="source-chip">{{ s }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区：拖拽图片/txt/pdf 到此处，或在输入框内 Ctrl+V 粘贴（均支持多附件） -->
        <div
          class="composer"
          @dragenter.prevent="onDragEnter"
          @dragover.prevent
          @dragleave.prevent="onDragLeave"
          @drop="onDrop"
          @paste="onPaste"
        >
          <transition name="el-fade-in">
            <div v-if="dragActive" class="drop-overlay">
              <span>📎 松开鼠标，上传 图片 / txt / pdf</span>
            </div>
          </transition>
          <!-- 待发送附件预览条：显示在输入框上方，可逐个删除 -->
          <div v-show="pendingAtts.length" class="attach-strip">
            <div v-for="(a, ai) in pendingAtts" :key="ai" class="attach-item" :title="a.name || a.url">
              <img v-if="a.kind === 'img'" :src="a.url" class="attach-img" alt="附件" />
              <span v-else class="attach-file">📄 {{ a.name || '文件' }}</span>
              <span class="attach-del" @click="removePending(ai)">✕</span>
            </div>
          </div>
          <div class="input-area">
            <el-input
              v-model="inputText"
              type="textarea"
              :rows="2"
              placeholder="输入问题；拖入文件或 Ctrl+V 粘贴图片即可发送"
              :disabled="isStreaming"
              @keyup.enter.native="sendMessage"
            />
            <el-button
              type="primary"
              :loading="isStreaming"
              :disabled="(!inputText.trim() && !pendingAtts.length) || isStreaming || attUploading"
              @click="sendMessage"
            >
              {{ isStreaming ? '思考中...' : (attUploading ? '上传中...' : '发送') }}
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { Component, Vue } from 'vue-property-decorator'

const API_BASE = 'http://localhost:8000'
// 当前登录用户标识（会话隔离用）。演示阶段用固定值；接入真实登录态后改为从 store/token 取用户ID
const CURRENT_USER_ID = 'sky-admin'
// 图片 + txt/pdf 附件统一直传 Python Agent(:8000) 本地存储（/upload/file → /files 托管）
const FILE_UPLOAD_URL = API_BASE + '/upload/file'
const IMG_REG = /\[图片:([^\]]+)\]/g
// 文件标记：<链接>|<原文件名>；两者均可能含空格，文件名不允许有 ']'，用 [^\]] 分别捕获
const FILE_REG = /\[文件:([^\]]+)\|([^\]]+)\]/g

interface SessionMeta {
  id: string
  title: string
  created_at: string
  updated_at: string
  round_count: number
}

interface ChatMessage {
  role: string
  content: string
}

// 待发送附件：img=图片，file=txt/pdf；url 均为本服务 /files 相对路径
interface PendingAtt {
  kind: 'img' | 'file'
  url: string
  name?: string
}

@Component({
  name: 'AIChat'
})
export default class extends Vue {
  private inputText = ''
  private isStreaming = false
  // 待发送附件列表（拖拽/粘贴累计；发送后清空）
  private pendingAtts: PendingAtt[] = []
  private attUploading = false   // 是否有附件正在上传（发送按钮禁用）
  private dragActive = false     // 拖拽悬停高亮
  private dragDepth = 0          // 拖入/拖出计数（防子元素 dragleave 抖动）
  private sidebarCollapsed = false
  private historyExpanded = true
  private messages: ChatMessage[] = []
  private sessions: SessionMeta[] = []
  private currentSessionId: string | null = null
  private roundCount = 0
  // 当前轮"工具调用轨迹"与"引用来源"（仅本次流式展示，不持久化进历史消息）
  private currentToolCalls: string[] = []
  private currentSources: string[] = []

  // ======== 生命周期 ========
  mounted() {
    this.fetchSessions()
    // 全局兜底：拖拽被 ESC 取消/移出窗口时重置悬停态（防止 overlay 卡住）
    window.addEventListener('dragend', this.resetDrag)
    window.addEventListener('drop', this.resetDrag)
  }
  beforeDestroy() {
    window.removeEventListener('dragend', this.resetDrag)
    window.removeEventListener('drop', this.resetDrag)
  }

  // ======== 会话管理 ========

  private get authHeaders(): Record<string, string> {
    return { 'X-User-Id': CURRENT_USER_ID }
  }

  private async fetchSessions() {
    try {
      const res = await fetch(`${API_BASE}/sessions`, { headers: this.authHeaders })
      const data = await res.json()
      this.sessions = data.sessions || []
    } catch {
      // 静默失败
    }
  }

  private async switchToSession(s: SessionMeta) {
    // 先保存当前会话（确保保存完成后再切换）
    await this.saveCurrentSession()
    // 清空当前
    this.messages = []
    this.roundCount = 0
    this.currentSessionId = null
    this.currentToolCalls = []
    this.currentSources = []
    // 加载新会话
    try {
      const res = await fetch(`${API_BASE}/sessions/${s.id}`, { headers: this.authHeaders })
      const data = await res.json()
      if (data.messages) {
        this.messages = data.messages
        this.currentSessionId = s.id
        this.roundCount = s.round_count
      }
    } catch {
      // 静默失败
    }
    this.$nextTick(() => this.scrollToBottom())
  }

  private async newChat() {
    // 先保存当前会话（await 确保保存完成后再清空）
    await this.saveCurrentSession()
    this.messages = []
    this.roundCount = 0
    this.currentSessionId = null
    this.currentToolCalls = []
    this.currentSources = []
  }

  private async saveCurrentSession() {
    if (this.messages.length === 0) return
    try {
      const res = await fetch(`${API_BASE}/sessions/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...this.authHeaders },
        body: JSON.stringify({
          messages: this.messages,
          round_count: this.roundCount,
          session_id: this.currentSessionId,
          user_id: CURRENT_USER_ID,
        })
      })
      const data = await res.json()
      if (data.session_id && !this.currentSessionId) {
        this.currentSessionId = data.session_id
      }
      // 刷新列表
      this.fetchSessions()
    } catch {
      // 静默失败
    }
  }

  // ======== 发送消息 ========

  private async sendMessage() {
    const text = this.inputText.trim()
    // query = 文字 + 各附件标记（图片→[图片:绝对URL]，文件→[文件:绝对URL|名]）；文字/附件至少其一
    // 附件 url 在 push 时已是绝对地址（absUrl），这里直接用
    const parts: string[] = this.pendingAtts.map((a) => {
      if (a.kind === 'img') return `[图片:${a.url}]`
      return `[文件:${a.url}|${a.name || '文件'}]`
    })
    let content = text
    if (parts.length) {
      content = (text ? text + '\n' : '') + parts.join('\n')
    }
    if (!content || this.isStreaming || this.attUploading) return
    const query = content

    // 添加用户消息
    this.messages.push({ role: 'user', content })
    this.inputText = ''
    this.pendingAtts = []
    this.isStreaming = true

    // 添加空白占位消息（显示 "..." 加载点）
    const msgIdx = this.messages.length
    this.messages.push({ role: 'assistant', content: '' })
    // 清空上一轮的展示字段
    this.currentToolCalls = []
    this.currentSources = []

    this.$nextTick(() => this.scrollToBottom())

    try {
      const history = this.messages.slice(0, -2).map(m => ({
        role: m.role,
        content: m.content
      }))

      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...this.authHeaders },
        body: JSON.stringify({ query, history })
      })

      if (!response.ok) {
        throw new Error(`请求失败 (${response.status})`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) continue

          const data = trimmed.startsWith('data: ')
            ? trimmed.substring(6)
            : trimmed.substring(5)

          if (data === '[DONE]') continue

          try {
            const parsed = JSON.parse(data)
            if (parsed.token) {
              this.$set(this.messages, msgIdx, {
                role: 'assistant',
                content: this.messages[msgIdx].content + parsed.token
              })
              this.$nextTick(() => this.scrollToBottom())
            } else if (parsed.tool) {
              // 工具调用事件 → 追加到"工具轨迹"展示（不写入历史消息）
              const t = parsed.tool
              const label = (t.name || '工具').replace('_', ' ')
              this.currentToolCalls.push(label)
              this.$nextTick(() => this.scrollToBottom())
            }
            // 注意：reasoning 事件当前版本不渲染（保持气泡干净），忽略即可
          } catch {
            // 跳过非 JSON 行
          }
        }
      }
    } catch (err) {
      const errMsg = (err && err.message) || '网络错误'
      this.$set(this.messages, msgIdx, {
        role: 'assistant',
        content: (this.messages[msgIdx].content || '') + '\n\n[请求失败：' + errMsg + ']'
      })
    } finally {
      this.isStreaming = false
      this.roundCount += 1
      // 从最终回答文本提取"来源: [N] xx · [M] yy"引用行 → 独立来源 chips，
      // 并从正文中剔除该行（避免正文+chips 双份重复展示）
      const full = (this.messages[msgIdx] && this.messages[msgIdx].content) || ''
      const citeMatch = full.match(/来源:\s*(.+)$/m)
      if (citeMatch) {
        const parts = citeMatch[1].split('·')
        this.currentSources = parts
          .map((s: string) => s.replace(/\[\d+\]\s*/, '').trim())
          .filter((s: string) => !!s)
        // 去掉正文末尾的来源行（连同前导空行）
        const cleaned = full.replace(/\n*\s*来源:\s*.+$/m, '').trimEnd()
        if (cleaned !== full) {
          this.$set(this.messages, msgIdx, { role: 'assistant', content: cleaned })
        }
      }
      this.$nextTick(() => this.scrollToBottom())
      // ★ 自动保存（注意：currentToolCalls/currentSources 不入库，仅展示）
      await this.saveCurrentSession()
    }
  }

  // ======== 图片/文件上传与消息分段渲染 ========

  // 解析消息 content：把 "[图片:url]"、"[文件:url|文件名]" 拆成
  // [{type:'text'|'img'|'file', v, name?}] 段，供模板分段渲染。
  // 注意：文件名可能含空格/点等字符，故文件名捕获组用 [^\] 排除 ']'，而不用 \S。
  private contentSegments(content: string): Array<{ type: string; v: string; name?: string }> {
    const segs: Array<{ type: string; v: string; name?: string }> = []
    const combined = new RegExp(`(${IMG_REG.source})|(${FILE_REG.source})`, 'g')
    let last = 0
    let m: RegExpExecArray | null
    while ((m = combined.exec(content || '')) !== null) {
      if (m.index > last) segs.push({ type: 'text', v: content.slice(last, m.index) })
      const whole = m[0]
      if (whole.startsWith('[图片:')) {
        segs.push({ type: 'img', v: m[2] })
      } else {
        // [文件:<url>|<name>]：URL 为 m[4]，文件名 m[5]；兼容 URL 侧含 '|' 的边界按第一个 '|' 拆
        const inner = whole.slice(4, -1)   // 去 "[文件:" 与 "]"
        const sep = inner.indexOf('|')
        const url = sep >= 0 ? inner.slice(0, sep) : inner
        const name = sep >= 0 ? inner.slice(sep + 1) : '文件'
        segs.push({ type: 'file', v: url, name })
      }
      last = m.index + whole.length
    }
    if (last < (content || '').length) segs.push({ type: 'text', v: content.slice(last) })
    if (!segs.length && content) segs.push({ type: 'text', v: content })
    return segs
  }

  // ======== 拖拽 / Ctrl+V 粘贴上传 ========
  // 图片 → Spring OSS；txt/pdf → Python Agent；两者都支持一次多个
  // 常量上限：与后端一致（图片≤10MB，txt/pdf≤10MB）
  private MAX_ATT_SIZE = 10 * 1024 * 1024

  // 上传完成的回调队列是否在忙（mutex：并发 drop/paste 时只让一批跑，避免 attUploading 互相覆盖）
  private uploadBusy = false

  private resetDrag() {
    this.dragDepth = 0
    this.dragActive = false
  }

  private isImg(f: File): boolean {
    return (f.type || '').startsWith('image/')
  }
  private isDoc(f: File): boolean {
    const n = (f.name || '').toLowerCase()
    return f.type === 'text/plain' || f.type === 'application/pdf'
      || n.endsWith('.txt') || n.endsWith('.pdf')
  }

  // 拖拽进入：仅当拖的是文件才点亮高亮（用 depth 计数避免子元素抖动）
  private onDragEnter(e: DragEvent) {
    if (this.isStreaming) return
    const types = (e.dataTransfer && e.dataTransfer.types) || []
    if (Array.prototype.indexOf.call(types, 'Files') >= 0) {
      this.dragDepth += 1
      this.dragActive = true
    }
  }
  private onDragLeave() {
    this.dragDepth = Math.max(0, this.dragDepth - 1)
    if (this.dragDepth === 0) this.dragActive = false
  }
  private onDrop(e: DragEvent) {
    this.resetDrag()
    if (this.isStreaming) return
    const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []) as File[]
    if (files.length) {
      e.preventDefault()   // 仅真正 drop 文件时拦截默认（拖文字进输入框不受影响）
      this.uploadFiles(files)
    }
  }

  // Ctrl+V：截图/复制的图片，或从资源管理器复制的 txt/pdf 文件
  private onPaste(e: ClipboardEvent) {
    if (this.isStreaming) return
    const cd = e.clipboardData
    if (!cd) return
    const files: File[] = []
    // 只从 clipbaordData.items（getAsFile）取文件；cd.files 与 items 是同一批，
    // 若同时遍历会因 File 引用不同而重复 → 粘贴一张冒出两张
    const items = cd.items ? Array.from(cd.items) : []
    items.forEach((it) => {
      if (it.kind === 'file') {
        const f = it.getAsFile()
        if (f) files.push(f)
      }
    })
    // 兜底：个别浏览器 items 为空但 files 有 → 此时才用 cd.files
    if (!files.length && cd.files) {
      Array.from(cd.files).forEach((f) => files.push(f))
    }
    const usable = files.filter((f) => this.isImg(f) || this.isDoc(f))
    if (usable.length) {
      e.preventDefault()
      this.uploadFiles(usable)
    }
    // 无图片/文件（纯文本粘贴）→ 不拦截，交给 textarea 默认行为
  }

  private async uploadFiles(files: File[]) {
    // 防抖/mutex：正在传时又 drop/paste → 直接忽略新的一批（避免并发覆盖 attUploading）
    if (this.uploadBusy) return
    this.uploadBusy = true
    this.attUploading = true
    try {
      for (const f of files) {
        if (f.size > this.MAX_ATT_SIZE) {
          this.$message.warning(`「${f.name}」超过 10MB，已跳过`)
          continue
        }
        if (this.isImg(f)) {
          await this.uploadImage(f)
        } else if (this.isDoc(f)) {
          await this.uploadDoc(f)
        } else {
          this.$message.warning(`忽略 ${f.name}：仅支持 图片 / txt / pdf`)
        }
      }
    } finally {
      this.attUploading = false
      this.uploadBusy = false
    }
  }

  // 文件名清洗：去掉会破坏 [文件:url|名] 标记解析、或用于 HTML title/插值的字符
  private cleanName(name: string): string {
    return (name || '').replace(/[\]|\r\n<>"]/g, '_').slice(0, 120)
  }

  // 后端返回的相对 /files/... → 补成绝对 URL。
  // 预览条缩略图、消息气泡、发给 Agent 的标记都要用绝对地址（页面在 :8888，/files 只在 :8000）
  private absUrl(u: string): string {
    return u && u.startsWith('http') ? u : API_BASE + u
  }

  // 图片 → Python Agent /upload/file（与 txt/pdf 同链路，本地存储 /files 托管）
  // 返回 {url:'/files/..', name}；发送时拼 [图片:绝对URL]，Agent 见标记转本地 base64 读图
  private async uploadImage(file: File) {
    const fd = new FormData()
    fd.append('file', file, file.name)
    try {
      const res = await fetch(FILE_UPLOAD_URL, { method: 'POST', body: fd })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json().catch(() => null)
      if (!data || !data.url) throw new Error('未返回图片地址')
      this.pendingAtts.push({ kind: 'img', url: this.absUrl(data.url), name: this.cleanName(data.name || file.name) })
    } catch (e) {
      const msg = (e && (e as Error).message) || '网络错误'
      this.$message.error(`图片「${file.name}」上传失败：${msg}（≤10MB）`)
    }
  }

  // txt/pdf → Python Agent /upload/file，返回 {url:'/files/..', name}
  private async uploadDoc(file: File) {
    const fd = new FormData()
    fd.append('file', file, file.name)
    try {
      const res = await fetch(FILE_UPLOAD_URL, { method: 'POST', body: fd })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json().catch(() => null)
      if (!data || !data.url) throw new Error('未返回文件地址')
      this.pendingAtts.push({ kind: 'file', url: this.absUrl(data.url), name: this.cleanName(data.name || file.name) })
    } catch (e) {
      const msg = (e && (e as Error).message) || '网络错误'
      this.$message.error(`文件「${file.name}」上传失败：${msg}（仅 txt/pdf，≤10MB）`)
    }
  }

  // 删除某条待发送附件
  private removePending(i: number) {
    this.pendingAtts.splice(i, 1)
  }

  private openImg(url: string) {
    window.open(url, '_blank')
  }

  private scrollToBottom() {
    const el = this.$refs.messageList as HTMLElement
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }

  private formatTime(t: string): string {
    if (!t) return ''
    // 取 "2025-06-10 19:33" 格式
    const parts = t.split(' ')
    if (parts.length >= 2) {
      return parts[0].slice(5) + ' ' + parts[1].slice(0, 5)
    }
    return t
  }
}
</script>

<style lang="scss" scoped>
.chat-layout {
  display: flex;
  height: calc(100vh - 100px);
  gap: 0;
  background: #f0f2f5;
}

/* ===== 侧边栏 ===== */
.sidebar {
  width: 260px;
  min-width: 260px;
  background: #fff;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e8e8e8;
  transition: all 0.25s ease;
  overflow: hidden;
}
.sidebar.collapsed {
  width: 48px;
  min-width: 48px;
}

.sidebar-header {
  padding: 12px;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  flex-direction: column;
  gap: 8px;
  position: relative;
}
.sidebar.collapsed .sidebar-header {
  align-items: center;
  padding: 12px 8px;
}

.sidebar-title {
  font-size: 15px;
  font-weight: 600;
  color: #333;
}

.new-chat-btn {
  width: 100%;
  padding: 10px 0;
  margin: 8px 0 4px;
  background: #409eff;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}
.new-chat-btn:hover {
  background: #66b1ff;
}

.toggle-btn {
  background: none;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
  padding: 4px 10px;
  color: #666;
  transition: all 0.2s;
}
.toggle-btn:hover {
  background: #f0f0f0;
  color: #333;
}
.toggle-corner {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 10;
  border-color: #333 !important;
}
.sidebar-header {
  position: relative;
}

.sidebar-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 8px 0;
  overflow: hidden;
}

.current-session-info {
  padding: 8px 16px 12px;
  border-bottom: 1px solid #f0f0f0;
  margin-bottom: 4px;
}
.round-badge {
  font-size: 12px;
  color: #409eff;
  background: #ecf5ff;
  padding: 4px 10px;
  border-radius: 12px;
  display: inline-block;
}

/* ===== 历史会话展收 ===== */
.history-section {
  border-top: 1px solid #f0f0f0;
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  font-size: 13px;
  color: #666;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.history-header:hover {
  background: #f5f7fa;
}

.history-count {
  font-size: 11px;
  color: #999;
  background: #f0f0f0;
  padding: 1px 8px;
  border-radius: 10px;
}

.history-list {
  overflow-y: auto;
  max-height: calc(100vh - 280px);
}

.session-item {
  padding: 12px 16px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all 0.15s;
}
.session-item:hover {
  background: #f5f7fa;
}
.session-item.active {
  background: #ecf5ff;
  border-left-color: #409eff;
}

.session-title {
  font-size: 13px;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 4px;
}

.session-meta {
  font-size: 11px;
  color: #999;
}

.no-sessions {
  text-align: center;
  color: #ccc;
  padding: 40px 16px;
  font-size: 13px;
}

/* ===== 聊天区 ===== */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
}

/* ===== 消息气泡：用户右侧，AI 左侧 ===== */
.message-item {
  display: flex;
  margin-bottom: 20px;
  gap: 10px;
}
.message-user {
  flex-direction: row-reverse;
}
.message-ai {
  flex-direction: row;
}

.message-avatar {
  font-size: 28px;
  flex-shrink: 0;
  margin-top: 4px;
}

.message-content {
  max-width: 70%;
}
.message-user .message-content {
  text-align: right;
}

.message-role {
  font-size: 12px;
  color: #999;
  margin-bottom: 4px;
}

.message-bubble {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
  white-space: pre-wrap;
  background: #fff;
  color: #333;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.bubble-user {
  background: #409eff;
  color: #fff;
  box-shadow: 0 1px 3px rgba(64, 158, 255, 0.25);
}

/* ===== 工具轨迹 + 引用来源 ===== */
.tool-track {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.tool-chip {
  font-size: 12px;
  color: #8c6d1f;
  background: #fff7e6;
  border: 1px solid #ffe58f;
  border-radius: 12px;
  padding: 2px 10px;
  display: inline-block;
}
.source-track {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed #eee;
}
.source-label {
  font-size: 12px;
  color: #999;
}
.source-chip {
  font-size: 11px;
  color: #666;
  background: #f4f4f5;
  border-radius: 10px;
  padding: 2px 8px;
  display: inline-block;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== 加载点动画 ===== */
.loading-dots .dot {
  animation: blink 1.4s infinite;
  font-size: 24px;
  font-weight: bold;
  line-height: 0;
}
.loading-dots .dot:nth-child(2) {
  animation-delay: 0.2s;
}
.loading-dots .dot:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes blink {
  0%, 80%, 100% { opacity: 0; }
  40% { opacity: 1; }
}

/* ===== 输入区（composer：预览条 + 输入框，整体为拖放目标） ===== */
.composer {
  position: relative;
  background: #fff;
  border-top: 1px solid #e8e8e8;
}
.input-area {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 12px 24px 16px;
}
.input-area .el-input {
  flex: 1;
}
.input-area .el-button {
  height: 56px;
  min-width: 100px;
}

/* 待发送附件预览条：位于输入框上方，可横向排布、可删除 */
.attach-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 10px 24px 2px;
}
.attach-item {
  position: relative;
  display: inline-flex;
  align-items: center;
  cursor: default;
}
.attach-img {
  width: 52px;
  height: 52px;
  object-fit: cover;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  display: block;
}
.attach-file {
  display: inline-block;
  max-width: 180px;
  background: #f4f4f5;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attach-del {
  position: absolute;
  top: -7px;
  right: -7px;
  background: #f56c6c;
  color: #fff;
  width: 16px;
  height: 16px;
  line-height: 16px;
  text-align: center;
  border-radius: 50%;
  font-size: 11px;
  cursor: pointer;
  z-index: 2;
}
.attach-del:hover {
  background: #f78989;
}

/* 拖拽悬停时的整区高亮遮罩 */
.drop-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(64, 158, 255, 0.1);
  border: 2px dashed #409eff;
  color: #409eff;
  font-size: 14px;
  font-weight: 600;
  pointer-events: none;
}

/* ===== 聊天消息里的图片 ===== */
.chat-img {
  max-width: 220px;
  max-height: 220px;
  border-radius: 6px;
  display: block;
  margin: 4px 0;
  cursor: zoom-in;
}

/* ===== 聊天消息里的文件链接 ===== */
.chat-file {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  background: #f4f4f5;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 4px 10px;
  margin: 4px 0;
  font-size: 13px;
  color: #409eff;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.chat-file:hover {
  background: #ecf5ff;
  border-color: #b3d8ff;
}
</style>

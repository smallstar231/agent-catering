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
                <span v-if="msg.role === 'assistant' && i === messages.length - 1 && !msg.content" class="loading-dots">
                  <span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>
                </span>
                <span v-else>{{ msg.content }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="input-area">
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="2"
            placeholder="请输入问题..."
            :disabled="isStreaming"
            @keyup.enter.native="sendMessage"
          />
          <el-button
            type="primary"
            :loading="isStreaming"
            :disabled="!inputText.trim() || isStreaming"
            @click="sendMessage"
          >
            {{ isStreaming ? '思考中...' : '发送' }}
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { Component, Vue } from 'vue-property-decorator'

const API_BASE = 'http://localhost:8000'

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

@Component({
  name: 'AIChat'
})
export default class extends Vue {
  private inputText = ''
  private isStreaming = false
  private sidebarCollapsed = false
  private historyExpanded = true
  private messages: ChatMessage[] = []
  private sessions: SessionMeta[] = []
  private currentSessionId: string | null = null
  private roundCount = 0

  // ======== 生命周期 ========
  mounted() {
    this.fetchSessions()
  }

  // ======== 会话管理 ========

  private async fetchSessions() {
    try {
      const res = await fetch(`${API_BASE}/sessions`)
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
    // 加载新会话
    try {
      const res = await fetch(`${API_BASE}/sessions/${s.id}`)
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
  }

  private async saveCurrentSession() {
    if (this.messages.length === 0) return
    try {
      const res = await fetch(`${API_BASE}/sessions/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: this.messages,
          round_count: this.roundCount,
          session_id: this.currentSessionId,
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
    const query = this.inputText.trim()
    if (!query || this.isStreaming) return

    // 添加用户消息
    this.messages.push({ role: 'user', content: query })
    this.inputText = ''
    this.isStreaming = true

    // 添加空白占位消息（显示 "..." 加载点）
    const msgIdx = this.messages.length
    this.messages.push({ role: 'assistant', content: '' })

    this.$nextTick(() => this.scrollToBottom())

    try {
      const history = this.messages.slice(0, -2).map(m => ({
        role: m.role,
        content: m.content
      }))

      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
            }
          } catch {
            // 跳过非 JSON 行
          }
        }
      }
    } catch (err: any) {
      const errMsg = (err && err.message) || '网络错误'
      this.$set(this.messages, msgIdx, {
        role: 'assistant',
        content: (this.messages[msgIdx].content || '') + '\n\n[请求失败：' + errMsg + ']'
      })
    } finally {
      this.isStreaming = false
      this.roundCount += 1
      this.$nextTick(() => this.scrollToBottom())
      // ★ 自动保存
      await this.saveCurrentSession()
    }
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

/* ===== 输入区 ===== */
.input-area {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 16px 24px;
  background: #fff;
  border-top: 1px solid #e8e8e8;
}
.input-area .el-input {
  flex: 1;
}
.input-area .el-button {
  height: 56px;
  min-width: 100px;
}
</style>

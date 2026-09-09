<template>
  <div class="dashboard-container">
    <div class="container">
      <el-tabs v-model="activeTab">
        <!-- ============ Tab 1: AI 能力开关 ============ -->
        <el-tab-pane label="AI能力" name="ability">
          <el-alert
            title="以下配置写回 config/*.yml。Agent 在启动时加载配置，修改后需重启 Agent 服务才生效。"
            type="info" :closable="false" show-icon style="margin-bottom: 16px" />
          <div v-if="configLoading" class="tip">加载中...</div>
          <el-form v-else label-width="160px" label-position="left" class="ai-form">
            <el-form-item label="🌐 联网搜索">
              <span :class="cfg.web_search && cfg.web_search.enabled ? 'cfg-on' : 'cfg-off'">
                {{ cfg.web_search && cfg.web_search.enabled ? '已启用' : '未启用' }}
              </span>
              <span class="cfg-hint">{{ cfg.web_search && cfg.web_search.note }}</span>
            </el-form-item>

            <el-form-item label="🎯 Rerank 精排">
              <el-switch :value="!!(cfg.rerank && cfg.rerank.enabled)" @change="onRerankToggle" />
              <span class="cfg-hint">模型: {{ cfg.rerank && cfg.rerank.model }}（top {{ cfg.rerank && cfg.rerank.top_n }}）</span>
            </el-form-item>

            <el-form-item label="🔌 MCP 工具">
              <el-switch :value="!!(cfg.mcp && cfg.mcp.enabled)" @change="onMcpToggle" />
              <span class="cfg-hint">transport: {{ cfg.mcp && cfg.mcp.transport }}</span>
            </el-form-item>

            <el-form-item label="🖼 视觉读图模型">
              <el-select :value="cfg.vision_model" @change="onVisionChange" style="width: 200px">
                <el-option label="qwen-vl-plus" value="qwen-vl-plus" />
                <el-option label="qwen-vl-max" value="qwen-vl-max" />
              </el-select>
            </el-form-item>

            <el-form-item label="💬 会话压缩预算">
              <el-input-number
                :value="cfg.conv && cfg.conv.budget"
                :min="1000" :max="30000" :step="500" @change="onBudgetChange" />
              <span class="cfg-hint">字符，超预算自动压缩历史</span>
            </el-form-item>

            <el-form-item label="📚 FAQ 精确问答">
              <span class="cfg-on">{{ cfg.faq ? cfg.faq.count : 0 }} 条</span>
              <span class="cfg-hint">{{ cfg.faq && cfg.faq.path }}</span>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- ============ Tab 2: 模型 / 知识库 / FAQ 查看 ============ -->
        <el-tab-pane label="模型·知识库·FAQ" name="kb">
          <!-- 模型配置区 -->
          <div class="sec-title">模型配置（改后需重启 Agent 生效）</div>
          <div class="model-config">
            <div v-for="k in modelKeys" :key="k" class="model-row">
              <label class="model-label">{{ modelLabels[k] || k }}</label>
              <el-select
                v-model="modelDraft[k]"
                filterable
                allow-create
                default-first-option
                placeholder="选择或输入模型名"
                style="width: 260px"
              >
                <el-option
                  v-for="m in (modelOptions.options && modelOptions.options[k]) || []"
                  :key="m" :label="m" :value="m"
                />
              </el-select>
            </div>
            <div style="margin: 8px 0 4px 160px">
              <el-button type="primary" :loading="modelSaving" @click="saveModels">保存模型配置</el-button>
              <span class="cfg-hint">保存写回 config/rag.yml，重启 Agent 后生效</span>
            </div>
          </div>
          <el-divider />
          <div v-if="kbLoading" class="tip">加载中...</div>
          <template v-else>
            <div class="sec-title">向量知识库</div>
            <el-table :data="kbRows" stripe class="tableBox" style="width: 100%; margin-bottom: 20px">
              <el-table-column prop="scene" label="场景" width="180" />
              <el-table-column prop="collection" label="文本集合" />
              <el-table-column prop="chunks" label="文本切片数" width="110" />
              <el-table-column prop="collection_mm" label="图文集合" />
              <el-table-column prop="mm_images" label="图文数" width="100" />
            </el-table>

            <div class="sec-title">知识库源文件（data/）</div>
            <div style="margin-bottom: 20px">
              <el-tag v-for="(f, i) in sourceFiles" :key="i" style="margin: 0 8px 8px 0">{{ f }}</el-tag>
            </div>

            <div class="sec-title">上传入库</div>
            <div style="margin-bottom: 16px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap">
              <el-radio-group v-model="kbUploadScene">
                <el-radio-button label="sky">苍穹外卖(sky)</el-radio-button>
                <el-radio-button label="robot">机器人(robot)</el-radio-button>
              </el-radio-group>
              <el-upload
                action="#"
                :auto-upload="false"
                :show-file-list="true"
                :limit="1"
                :on-change="onKbFileChange"
                :on-remove="() => { kbFile = null }"
                accept=".txt,.pdf,.png,.jpg,.jpeg,.gif,.webp,.bmp"
              >
                <el-button size="small" icon="el-icon-upload2">选择文件（txt/pdf/图片）</el-button>
              </el-upload>
              <el-button type="primary" size="small" :loading="kbUploading" :disabled="!kbFile" @click="doKbUpload">
                上传并入库
              </el-button>
              <span class="cfg-hint">保存到 data/kb/&lt;场景&gt;/，自动进文本库或图文库（含图PDF抽图）</span>
            </div>

            <div class="sec-title">FAQ 问答（{{ faqItems.length }} 条）</div>
            <el-collapse>
              <el-collapse-item v-for="(f, i) in faqItems" :key="i" :title="f.q">
                <div style="white-space: pre-wrap">{{ f.a }}</div>
              </el-collapse-item>
            </el-collapse>
          </template>
        </el-tab-pane>

        <!-- ============ Tab 3: 离线评估控制台 ============ -->
        <el-tab-pane label="离线评估" name="eval">
          <el-alert
            title="将样例问题批量跑 Agent 并打分（exact_match + LLM judge）。每次运行会真实调用模型，较慢。"
            type="warning" :closable="false" style="margin-bottom: 16px" />
          <div style="margin-bottom: 16px">
            <el-button type="primary" :loading="evalRunning" @click="runEval">运行评估（样例 limit=2）</el-button>
            <el-button @click="loadEvalSample">预览样例</el-button>
          </div>

          <template v-if="evalSample.length">
            <div class="sec-title">样例数据</div>
            <el-table :data="evalSample" border size="mini" class="tableBox" style="width: 100%; margin-bottom: 20px">
              <el-table-column prop="category" label="分类" width="100" />
              <el-table-column prop="query" label="问题" />
            </el-table>
          </template>

          <template v-if="evalResult.summary">
            <div class="sec-title">评估结果</div>
            <div style="margin-bottom: 16px">
              <el-tag type="success" style="margin-right: 12px">样本 {{ evalResult.summary.total }}</el-tag>
              <el-tag style="margin-right: 12px">exact_match 均值 {{ evalResult.summary.avg_exact_match }}</el-tag>
              <el-tag type="warning">LLM-judge PASS 率 {{ evalResult.summary.judge_pass_rate }}</el-tag>
            </div>
            <el-table v-if="evalResult.results && evalResult.results.length" :data="evalResult.results" border size="mini" class="tableBox" style="width: 100%">
              <el-table-column prop="query" label="问题" width="220" show-overflow-tooltip />
              <el-table-column prop="exact_match" label="em" width="80" />
              <el-table-column prop="judge" label="judge" width="90" />
              <el-table-column prop="answer" label="回答" show-overflow-tooltip />
            </el-table>
          </template>
        </el-tab-pane>

        <!-- ============ Tab 4: 会话历史管理 ============ -->
        <el-tab-pane label="会话历史" name="sessions">
          <div class="tableBar">
            <el-radio-group v-model="sessionUser" @change="loadSessions" style="margin-right: 12px">
              <el-radio-button label="sky-admin">sky-admin（客服）</el-radio-button>
              <el-radio-button label="default">default</el-radio-button>
            </el-radio-group>
            <el-button class="normal-btn continue" @click="loadSessions">刷新</el-button>
          </div>
          <el-table v-if="sessionRows.length" :data="sessionRows" stripe class="tableBox" style="width: 100%">
            <el-table-column prop="title" label="标题" show-overflow-tooltip />
            <el-table-column prop="round_count" label="轮数" width="90" />
            <el-table-column prop="updated_at" label="更新时间" width="180" />
            <el-table-column prop="created_at" label="创建时间" width="180" />
            <el-table-column label="操作" width="140" align="center">
              <template slot-scope="scope">
                <el-button type="text" size="small" class="blueBug" @click="viewSession(scope.row)">查看</el-button>
                <el-button type="text" size="small" class="delBut" @click="delSession(scope.row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <Empty v-else :is-search="false" />
          <el-dialog title="会话消息" :visible.sync="sessionDialog" width="600px" append-to-body>
            <div v-for="(m, i) in sessionMsgs" :key="i" class="msg-row">
              <span class="msg-role">{{ m.role === 'user' ? '🧑 用户' : '🤖 AI' }}</span>
              <div class="msg-content">{{ m.content }}</div>
            </div>
          </el-dialog>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script lang="ts">
import { Component, Vue } from 'vue-property-decorator'
import Empty from '@/components/Empty/index.vue'
import {
  getAiConfig, putAiConfig, getModelOptions, getAiKb, getAiFaq,
  getAiSessions, deleteAiSession, getAiEvalSample, postAiEval, uploadKbFile
} from '@/api/ai'

@Component({ name: 'AiConfig', components: { Empty } })
export default class extends Vue {
  private activeTab = 'ability'

  // Tab1 config
  private configLoading = true
  private cfg: any = {}

  // Tab2 kb/faq
  private kbLoading = true
  private kbRows: any[] = []
  private sourceFiles: string[] = []
  private faqItems: any[] = []

  // Tab2c 上传入库
  private kbUploadScene = 'sky'
  private kbFile: any = null
  private kbUploading = false

  // Tab2b 模型配置
  private modelKeys = [
    'chat_model_name', 'embedding_model_name', 'multimodal_embedding_model_name', 'rerank_model',
    'rerank_fallback_model', 'vision_model_name'
  ]
  private modelOptions: any = { current: {}, options: {}, labels: {} }
  private modelLabels: any = {}
  private modelDraft: any = {}
  private modelSaving = false

  // Tab3 eval
  private evalSample: any[] = []
  private evalResult: any = {}
  private evalRunning = false

  // Tab4 sessions：默认 sky-admin（聊天页 CURRENT_USER_ID 用 sky-admin，这样管理页默认能看到真实聊天会话）
  private sessionUser = 'sky-admin'
  private sessionRows: any[] = []
  private sessionMsgs: any[] = []
  private sessionDialog = false

  mounted() {
    this.loadConfig()
    this.loadModelOptions()
    this.loadKb()
    this.loadFaq()
    this.loadSessions()
  }

  private async loadModelOptions() {
    try {
      const d = await getModelOptions()
      this.modelOptions = d
      this.modelLabels = d.labels || {}
      // 用当前值初始化草稿（可编辑，保存时才写）
      const cur = d.current || {}
      this.modelKeys.forEach((k) => { this.$set(this.modelDraft, k, cur[k] || '') })
    } catch (e) {
      this.$message.error('加载模型配置失败：' + (e as any).message)
    }
  }

  private async saveModels() {
    this.modelSaving = true
    try {
      const targets = this.modelOptions.targets || {}
      const items: any[] = []
      for (const k of this.modelKeys) {
        const t = targets[k]
        if (t) {
          const v = (this.modelDraft[k] || '').trim()
          if (!v) {
            this.$message.warning(`${this.modelLabels[k] || k} 不能为空`)
            this.modelSaving = false
            return
          }
          items.push({ file: t.file, path: t.path, value: v })
        }
      }
      if (!items.length) { this.modelSaving = false; return }
      const r = await putAiConfig(items)
      this.$message.success(r.msg || '已保存')
      this.loadModelOptions()
      this.loadConfig()
    } catch (e) {
      this.$message.error('保存模型配置失败：' + (e as any).message)
    } finally {
      this.modelSaving = false
    }
  }

  private async loadConfig() {
    try {
      this.cfg = await getAiConfig()
    } catch (e) {
      this.$message.error('加载配置失败：' + (e as any).message)
    } finally {
      this.configLoading = false
    }
  }

  private async saveToggle(file: string, path: string, value: any) {
    try {
      const r = await putAiConfig([{ file, path, value }])
      this.$message.success(r.msg || '已保存')
      this.loadConfig()
    } catch (e) {
      this.$message.error('保存失败：' + (e as any).message)
    }
  }

  private onRerankToggle(v: any) {
    this.saveToggle('rag', 'rerank.enabled', !!v)
  }

  private onMcpToggle(v: any) {
    this.saveToggle('agent', 'enable_mcp_tools', !!v)
  }

  private onVisionChange(v: any) {
    this.saveToggle('rag', 'vision_model_name', v)
  }

  private onBudgetChange(v: any) {
    this.saveToggle('conv', 'history_char_budget', v)
  }

  private async loadKb() {
    try {
      const d = await getAiKb()
      const vec = d.vector || {}
      this.kbRows = ['sky', 'robot'].map((s) => ({
        scene: s === 'sky' ? '苍穹外卖(sky)' : '机器人(robot)',
        collection: vec[s] ? vec[s].collection : '-',
        chunks: vec[s] ? vec[s].chunks : 0,
        collection_mm: vec[s] ? (vec[s].collection_mm || '-') : '-',
        mm_images: vec[s] && typeof vec[s].mm_images === 'number' ? vec[s].mm_images : 0
      }))
      this.sourceFiles = d.source_files || []
    } catch (e) {
      this.$message.error('加载知识库失败：' + (e as any).message)
    } finally {
      this.kbLoading = false
    }
  }

  private async loadFaq() {
    try {
      const d = await getAiFaq()
      this.faqItems = d.items || []
    } catch (e) {
      this.$message.error('加载 FAQ 失败：' + (e as any).message)
    }
  }

  // ======== 上传入库 ========
  private onKbFileChange(file: any) {
    // 每次选文件更新当前待传文件（el-upload on-change）
    this.kbFile = file
  }

  private async doKbUpload() {
    if (!this.kbFile || !this.kbFile.raw) return
    this.kbUploading = true
    try {
      const file = this.kbFile.raw as File
      const r = await uploadKbFile(this.kbUploadScene, 'auto', file)
      this.$message.success(`已入库：${r.saved || file.name}（文本${r.ingested && r.ingested.text ? '✓' : '—'}，多模态${r.ingested && r.ingested.multimodal ? '✓' : '—'}）`)
      if (r.warning) this.$message.warning(r.warning)
      this.kbFile = null
      // 刷新知识库统计
      this.loadKb()
    } catch (e) {
      this.$message.error('上传入库失败：' + (e as any).message)
    } finally {
      this.kbUploading = false
    }
  }

  private async loadEvalSample() {
    try {
      const d = await getAiEvalSample()
      this.evalSample = d.samples || []
    } catch (e) {
      this.$message.error('加载样例失败：' + (e as any).message)
    }
  }

  private async runEval() {
    this.evalRunning = true
    this.evalResult = {}
    try {
      this.$message.info('评估运行中（调用模型，约 1-3 分钟）...')
      this.evalResult = await postAiEval({ limit: 2 })
      this.$message.success('评估完成')
    } catch (e) {
      this.$message.error('评估失败：' + (e as any).message)
    } finally {
      this.evalRunning = false
    }
  }

  private async loadSessions() {
    try {
      const d = await getAiSessions(this.sessionUser)
      this.sessionRows = d.sessions || []
    } catch (e) {
      this.$message.error('加载会话失败：' + (e as any).message)
    }
  }

  private async viewSession(row: any) {
    this.sessionMsgs = []
    try {
      const headers: Record<string, string> = { 'X-User-Id': this.sessionUser }
      const tok = (process.env.VUE_APP_AI_ADMIN_TOKEN || '').trim()
      if (tok) headers['X-AI-Admin-Token'] = tok
      const res = await fetch(`http://localhost:8000/sessions/${row.id}`, { headers })
      const d = await res.json()
      this.sessionMsgs = d.messages || []
      this.sessionDialog = true
    } catch (e) {
      this.$message.error('读取会话失败：' + (e as any).message)
    }
  }

  private async delSession(row: any) {
    try {
      await this.$confirm(`确定删除会话「${row.title}」？`, '提示', { type: 'warning' })
      await deleteAiSession(row.id, this.sessionUser)
      this.$message.success('已删除')
      this.loadSessions()
    } catch (e) {
      if ((e as any) !== 'cancel') this.$message.error('删除失败：' + (e as any).message)
    }
  }
}
</script>

<style lang="scss" scoped>
.container {
  min-height: 400px;
}
.tip {
  color: #999;
  padding: 20px 0;
}
.sec-title {
  font-weight: 600;
  margin: 8px 0 14px;
  color: #333;
}
.model-config {
  margin-bottom: 8px;
}
.model-row {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}
.model-label {
  width: 160px;
  flex-shrink: 0;
  font-size: 13px;
  color: #606266;
  margin-right: 12px;
  text-align: right;
}
.ai-form .el-form-item {
  margin-bottom: 14px;
}
.cfg-on {
  color: #409eff;
}
.cfg-off {
  color: #999;
}
.cfg-hint {
  margin-left: 12px;
  font-size: 12px;
  color: #999;
}
.msg-row {
  border-bottom: 1px dashed #eee;
  padding: 8px 0;
}
.msg-role {
  font-size: 12px;
  color: #909399;
}
.msg-content {
  margin-top: 4px;
  white-space: pre-wrap;
  font-size: 13px;
}
</style>

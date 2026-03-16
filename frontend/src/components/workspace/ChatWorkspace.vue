<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import DeleteSVG from '@/components/svg/DeleteSVG.vue'
import DeleteAllSVG from '@/components/svg/DeleteAllSVG.vue'
import SendSVG from '@/components/svg/SendSVG.vue'

defineOptions({ name: 'ChatWorkspace' })

marked.setOptions({ gfm: true, breaks: true })

const NEW_TALK_ID = ''

const props = defineProps({
  talkTitleList: {
    type: Array,
    default: () => [],
  },
  currentTalkId: {
    type: String,
    default: '',
  },
  currentTalkList: {
    type: Array,
    default: () => [],
  },
  isStreaming: {
    type: Boolean,
    default: false,
  },
  chatLoading: {
    type: Boolean,
    default: false,
  },
  patients: {
    type: Array,
    default: () => [],
  },
  syncPatientId: {
    type: [Number, null],
    default: null,
  },
  syncPatient: {
    type: Object,
    default: null,
  },
  conversationPreview: {
    type: Array,
    default: () => [],
  },
  canSyncConversation: {
    type: Boolean,
    default: false,
  },
  syncResult: {
    type: Object,
    default: null,
  },
})

const syncPatientModel = defineModel('syncPatientId', { default: null })

const emit = defineEmits([
  'select-talk',
  'new-chat',
  'delete-chat',
  'delete-all',
  'send-message',
  'sync-conversation',
  'open-patient-workspace',
])

const draftMessage = ref('')
const inputRef = ref(null)
const chatContainerRef = ref(null)
const isHistoryCollapsed = ref(false)
const isMobileLayout = ref(false)
const isSyncExpanded = ref(false)

function syncLayoutState() {
  const mobile = window.innerWidth <= 960

  if (mobile !== isMobileLayout.value) {
    isMobileLayout.value = mobile
    isHistoryCollapsed.value = mobile
    isSyncExpanded.value = false
    return
  }

  if (!mobile) {
    isHistoryCollapsed.value = false
    isSyncExpanded.value = false
  }
}

function toggleHistoryPanel() {
  if (!isMobileLayout.value) return
  isHistoryCollapsed.value = !isHistoryCollapsed.value
}

function toggleSyncPanel() {
  if (!isMobileLayout.value) return
  isSyncExpanded.value = !isSyncExpanded.value
}

onMounted(() => {
  syncLayoutState()
  window.addEventListener('resize', syncLayoutState)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncLayoutState)
})

watch(
  () => props.currentTalkList.length,
  () => {
    nextTick(scrollToBottom)
  },
)

watch(
  () => props.currentTalkId,
  () => {
    draftMessage.value = ''
    nextTick(() => {
      autoResize()
      scrollToBottom()
    })
  },
)

watch(draftMessage, () => {
  nextTick(autoResize)
})

const renderMarkdown = (raw = '') => {
  if (!raw) return ''

  return DOMPurify.sanitize(
    marked.parse(String(raw), {
      breaks: true,
      gfm: true,
    }),
  )
}

function autoResize() {
  const element = inputRef.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 220)}px`
}

function scrollToBottom() {
  const element = chatContainerRef.value
  if (!element) return
  element.scrollTop = element.scrollHeight
}

function handleSendMessage() {
  const text = draftMessage.value.trim()
  if (!text || props.isStreaming) return
  emit('send-message', text)
  draftMessage.value = ''
  nextTick(autoResize)
}

function handleCopy(text) {
  if (!text) return

  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(() => alert('复制成功')).catch(() => fallbackCopy(text))
    return
  }

  fallbackCopy(text)
}

function fallbackCopy(text) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
  alert('复制成功')
}

function formatDateTime(value) {
  if (!value) return '暂无时间'

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function shortText(value, fallback = '暂无内容') {
  const text = String(value || '').trim()
  return text || fallback
}
</script>

<template>
  <section class="chat-workspace">
    <aside class="history-card">
      <div class="section-head" style="border:none; padding: 8px 0px 0px 0px;">
        <button type="button" class="primary-action" @click="emit('new-chat')">开始新对话</button>
      </div>
      <div class="section-head" style="padding-top: 4px;">
        <div>
          <h3>对话历史</h3>
        </div>
        <div class="history-actions">
          <button type="button" class="ghost-icon collapse-toggle" @click="toggleHistoryPanel">
            {{ isHistoryCollapsed ? '展开' : '收起' }}
          </button>
          <button type="button" class="ghost-icon danger" @click="emit('delete-all')">
            <DeleteAllSVG size="20" color="currentColor" />
          </button>
        </div>
      </div>

      <div class="history-list" :class="{ collapsed: isHistoryCollapsed }">
        <div v-for="talk in talkTitleList" :key="talk.talkId" class="history-item"
          :class="{ active: talk.talkId === currentTalkId }" @click="emit('select-talk', talk.talkId)">
          <div>
            <p class="history-title">{{ talk.title }}</p>
            <small>{{ talk.talkId === NEW_TALK_ID ? '待发送问题' : `会话 #${talk.talkId}` }}</small>
          </div>
          <button type="button" class="ghost-icon" @click.stop="emit('delete-chat', talk.talkId)">
            <DeleteSVG size="16" color="currentColor" />
          </button>
        </div>

        <div v-if="!talkTitleList.length" class="empty-card compact">还没有历史对话，开始一轮新的问诊即可生成记录。</div>
      </div>
    </aside>

    <div class="chat-card">
      <div class="section-head">
        <div style="display: flex; align-items: center; gap: 12px;">
          <h3>实时问诊</h3>
          <span class="state-pill" :class="{ live: isStreaming }">{{ isStreaming ? '生成中' : '待输入' }}</span>
        </div>
      </div>

      <main ref="chatContainerRef" class="chat-messages">
        <div v-if="chatLoading" class="empty-card">正在加载历史对话...</div>

        <div v-else-if="currentTalkList.length" class="message-stack">
          <article v-for="(msg, index) in currentTalkList" :key="`${index}-${msg}`" class="message-wrapper"
            :class="{ user: index % 2 === 0 }">
            <div class="message-meta">
              <span>{{ index % 2 === 0 ? '医生输入' : 'AI回复' }}</span>
              <button type="button" class="copy-btn" @click="handleCopy(msg)">复制</button>
            </div>

            <div class="message" :class="{ user: index % 2 === 0 }">
              <template v-if="index % 2 === 0">
                <div class="plain-text">{{ msg }}</div>
              </template>
              <div v-else class="markdown-body" v-html="renderMarkdown(msg)"></div>
            </div>
          </article>
        </div>

        <div v-else class="empty-card">输入症状、病史或问题后，AI会在这里持续生成回复。</div>
      </main>

      <div class="input-box">
        <textarea ref="inputRef" v-model="draftMessage" rows="1" placeholder="请输入症状、病史或希望AI分析的问题" @input="autoResize"
          @keydown.enter.exact.prevent="handleSendMessage" />
        <button type="button" class="send-btn" :disabled="!draftMessage.trim() || isStreaming"
          @click="handleSendMessage">
          <SendSVG size="24" color="currentColor" />
        </button>
      </div>
    </div>

    <div v-if="isMobileLayout && isSyncExpanded" class="sync-backdrop" @click="toggleSyncPanel"></div>

    <aside class="sync-card" :class="{ mobile: isMobileLayout, expanded: isSyncExpanded }">
      <button v-if="isMobileLayout" type="button" class="sync-expander" :aria-expanded="isSyncExpanded"
        @click="toggleSyncPanel">
        <div class="sync-expander-copy">
          <strong>同步到患者AI意见</strong>
          <small>{{ syncPatient?.name || '请选择患者后同步当前对话' }}</small>
        </div>
        <span class="sync-expander-indicator">{{ isSyncExpanded ? '收起' : '展开' }}</span>
      </button>

      <div class="sync-card-body">
        <div class="section-head compact">
          <div>
            <h3>同步到患者AI意见</h3>
            <p>将当前对话内容合并到指定患者的健康建议。</p>
          </div>
        </div>

        <label class="field-label">
          关联患者
          <select v-model="syncPatientModel">
            <option :value="null">请选择患者</option>
            <option v-for="patient in patients" :key="patient.id" :value="patient.id">{{ patient.name }}</option>
          </select>
        </label>

        <div v-if="syncPatient" class="summary-card">
          <p class="summary-label">当前同步目标</p>
          <h4>{{ syncPatient.name }}</h4>
          <p>{{ shortText(syncPatient.history) }}</p>
          <button type="button" class="link-btn" @click="emit('open-patient-workspace', syncPatient.id)">查看患者详情</button>
        </div>

        <div class="preview-box">
          <div class="preview-head">
            <h3>待同步片段</h3>
            <small>{{ currentTalkId ? `对话 #${currentTalkId}` : '新对话未落库' }}</small>
          </div>
          <div v-if="conversationPreview.length" class="preview-list">
            <article v-for="(item, index) in conversationPreview" :key="`${item.role}-${index}`" class="preview-item">
              <strong>{{ item.role === 'user' ? '问' : '答' }}</strong>
              <p>{{ item.content }}</p>
            </article>
          </div>
          <div v-else class="empty-card compact">至少完成一轮问答后，才可以执行同步。</div>
        </div>

        <button type="button" class="primary-action" :disabled="!canSyncConversation"
          @click="emit('sync-conversation')">
          同步当前对话
        </button>

        <div v-if="syncResult?.aiOpinion" class="result-card">
          <p class="summary-label">最近同步结果</p>
          <h4>{{ syncResult.aiOpinion.riskLevel || '已更新' }}</h4>
          <p>{{ syncResult.aiOpinion.suggestion }}</p>
          <small>{{ formatDateTime(syncResult.aiOpinion.lastUpdatedAt) }}</small>
        </div>
      </div>
    </aside>
  </section>
</template>

<style scoped lang="scss">
.chat-workspace {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 300px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

/* ───────────────── History panel ───────────────── */
.history-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--color-border);
  background: var(--color-bg-light);
  overflow: hidden;
}

/* ───────────────── Chat panel ───────────────── */
.chat-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--color-bg-base);
  overflow: hidden;
}

/* ───────────────── Sync panel ───────────────── */
.sync-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-left: 1px solid var(--color-border);
  background: var(--color-bg-light);
  overflow-y: auto;
}

.sync-card-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.sync-backdrop {
  display: none;
}

.sync-expander {
  display: none;
}

/* ───────────────── Preview head ───────────────── */
.preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;

  h3 {
    margin: 0;
    font-size: 14px;
    font-weight: 700;
    color: var(--color-text-strong);
    letter-spacing: 0;
  }
}

/* ─────────────────── Buttons ─────────────────── */
.send-btn {
  border-radius: 128px;
  border: none;
  cursor: pointer;
  transition: all var(--transition-normal);
  background: transparent;

  &:not(:disabled):hover {
    background: rgba(17, 150, 127, 0.1);
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }
}

.primary-action {
  display: block;
  width: calc(100% - 28px);
  margin: 10px 14px;
}

.copy-btn {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--color-primary-dark);
  cursor: pointer;
  font-size: 12px;
}

/* ─────────────────── History list ─────────────────── */
.history-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.history-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.collapse-toggle {
  display: none;
  width: auto;
  padding: 0 10px;
  font-size: 12px;
  color: var(--color-primary-dark);
  border: 1px solid var(--color-border);
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-item);
  cursor: pointer;
  transition: background var(--transition-fast);
  flex-shrink: 0;

  &:hover {
    background: var(--color-hover-bg);
  }

  &.active {
    background: var(--color-active-bg);
    border-left: 3px solid var(--color-active-border);
    padding-left: 11px;
  }

  small {
    color: var(--color-text-weak);
    font-size: 12px;
    white-space: nowrap;
  }
}

.history-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ─────────────────── Chat area ─────────────────── */
.state-pill {
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 700;
  background: var(--color-badge-status-bg);
  color: var(--color-badge-status-color);

  &.live {
    background: rgba(17, 150, 127, 0.14);
    color: var(--color-primary-dark);
  }
}

.chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
}

.message-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.message-wrapper {
  display: flex;
  flex-direction: column;
  gap: 5px;
  align-items: flex-start;

  &.user {
    align-items: flex-end;
  }
}

.message-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  color: var(--color-text-weak);
}

.message {
  max-width: min(86%, 860px);
  padding: 12px 15px;
  background: var(--color-message-bg);
  border: 1px solid var(--color-border-light);
  border-radius: 2px 12px 12px 12px;
  line-height: 1.72;
  color: var(--color-text-strong);
  font-size: 15px;

  &.user {
    background: var(--color-message-user-bg);
    border-color: var(--color-message-user-border);
    border-radius: 12px 2px 12px 12px;
  }
}

.plain-text {
  white-space: pre-wrap;
  word-break: break-word;
}

/* ─────────────────── Input box ─────────────────── */
.input-box {
  border-top: 1px solid var(--color-border);
  padding: 10px 16px;
  background: var(--color-bg-base);
  display: grid;
  grid-template-columns: minmax(0, 1fr) 42px;
  gap: 10px;
  align-items: end;
  flex-shrink: 0;

  textarea {
    border: none;
    outline: none;
    resize: none;
    min-height: 36px;
    max-height: 180px;
    background: transparent;
    line-height: 1.6;
    font: inherit;
    color: var(--color-text-strong);
    box-sizing: border-box;
    width: 100%;
  }
}

.send-btn {
  width: 48px;
  height: 48px;
  color: var(--color-primary);
}

/* ─────────────────── Sync panel internals ─────────────────── */
.field-label {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light);

  select {
    width: 100%;
    margin-top: 8px;
    padding: 8px 30px 8px 12px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background-color: var(--color-bg-input);
    color: var(--color-text-strong);
    font-size: 14px;
    appearance: none;
    -webkit-appearance: none;
    cursor: pointer;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%235e7379' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 10px center;
    background-size: 16px;

    &:focus {
      outline: none;
      border-color: var(--color-primary);
      box-shadow: 0 0 0 2px rgba(17, 150, 127, 0.1);
    }
  }
}

.summary-card,
.preview-box,
.result-card {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.summary-card h4,
.result-card h4 {
  margin: 0 0 5px;
  font-size: 14px;
  font-weight: 700;
}

.summary-card p,
.result-card p,
.result-card small {
  color: var(--color-text-medium);
  margin: 0;
  font-size: 13px;
}

.preview-head {
  border-bottom: none;
  padding: 0 0 8px;
}

.preview-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.preview-item {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 6px;

  strong {
    color: var(--color-primary-dark);
    font-size: 13px;
  }

  p {
    margin: 0;
    font-size: 13px;
    color: var(--color-text-medium);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.markdown-body :deep(p:first-child) {
  margin-top: 0;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(pre) {
  overflow-x: auto;
  border-radius: var(--radius-md);
  padding: 10px 12px;
  background: var(--color-code-bg);
}

/* ─────────────────── Responsive ─────────────────── */
@media (max-width: 960px) {
  .chat-workspace {
    grid-template-columns: 1fr;
    height: auto;
    overflow: visible;
    margin-bottom: 68px;
  }

  .history-card {
    border-right: none;
    border-bottom: 1px solid var(--color-border);
    max-height: none;
    overflow: hidden;
  }

  .history-list.collapsed {
    display: none;
  }

  .collapse-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .chat-card {
    min-height: 480px;
    overflow: visible;
    padding-bottom: 68px;
  }

  .sync-card {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 40;
    border: none;
    border-top: 1px solid var(--color-border);
    border-radius: 0;
    background: var(--color-bg-light);
    backdrop-filter: blur(12px);
    box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.12);
    max-height: min(72dvh, 560px);
    overflow: hidden;
    transform: translateY(calc(100% - 68px));
    transition: transform var(--transition-slow);

    &.mobile.expanded {
      transform: translateY(0);
    }
  }

  .sync-card-body {
    max-height: calc(min(72dvh, 560px) - 68px);
    overflow-y: auto;
    padding-bottom: 10px;
  }

  .sync-expander {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    min-height: 68px;
    padding: 12px 14px;
    border: none;
    background: transparent;
    color: var(--color-text-strong);
    text-align: left;
    flex-shrink: 0;
  }

  .sync-expander-copy {
    display: flex;
    flex: 1;
    min-width: 0;
    flex-direction: column;
    gap: 3px;

    strong {
      font-size: 14px;
    }

    small {
      color: var(--color-text-medium);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .sync-expander-indicator {
    color: var(--color-text-medium);
    font-size: 12px;
  }

  .sync-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    background: var(--color-overlay-bg);
    z-index: 30;
  }

  .chat-messages {
    padding: 14px 12px;
  }

  .input-box {
    padding: 10px 12px;
  }

  .message {
    font-size: 14px;
    word-break: break-word;
  }
}

@media (max-width: 640px) {
  .chat-workspace {
    min-width: 0;
    margin-bottom: 64px;
  }

  .history-card {
    max-height: none;
  }

  .sync-expander {
    min-height: 64px;
    padding: 10px 16px;
    gap: 10px;
  }

  .sync-card-body {
    max-height: calc(min(76dvh, 560px) - 64px);
  }

  .history-item {
    padding: 10px 12px;
  }

  .section-head,
  .preview-head {
    flex-wrap: wrap;
  }

  .message {
    max-width: 100%;
  }

  .preview-item {
    grid-template-columns: 16px minmax(0, 1fr);

    p {
      white-space: normal;
      overflow: visible;
      text-overflow: clip;
      word-break: break-word;
      line-height: 1.5;
    }
  }
}
</style>

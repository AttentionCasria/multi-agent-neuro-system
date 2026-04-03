<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import DeleteSVG from '@/components/svg/DeleteSVG.vue'
import DeleteAllSVG from '@/components/svg/DeleteAllSVG.vue'
import SendSVG from '@/components/svg/SendSVG.vue'
import ThinkingPanel from './ThinkingPanel.vue'
import PdfPreviewModal from '@/components/PdfPreviewModal.vue'
import { injectRefLinks } from '@/utils/referenceParser'
import { matchDocumentAPI } from '@/api/documents'
import { compressImage } from '@/utils/imageCompress'
import AttachFileSVG from '../svg/AttachFileSVG.vue'

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
  // AI 处于推理阶段（收到 thinking 事件，尚未收到第一个 chunk）
  isThinking: {
    type: Boolean,
    default: false,
  },
  // 当前 thinking 步骤的提示文字（来自 thinking.title / thinking.step）
  thinkingHint: {
    type: String,
    default: '',
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
  // 每条 AI 回答的思考历史（与 currentTalkList 中的 AI 消息一一对应）
  thinkingHistoryList: {
    type: Array,
    default: () => [],
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
// 影像识别：待上传图片列表 [{ dataUrl, name }]，最多 3 张
const imageList = ref([])
const fileInputRef = ref(null)
const isDragOver = ref(false)
const dragDepth = ref(0)
// 用户是否主动上滑（上滑时暂停自动滚动）
const userScrolled = ref(false)
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

// ── 文献引用点击弹窗（方案 A：事件委托） ─────────────────────────────
// 弹窗状态：点击《文献名》后显示，提供[在线预览][下载]操作
const refPopup = ref({
  visible: false,
  name: '',
  loading: false,
  previewUrl: '',
  downloadUrl: '',
  error: '',
})

// PDF 预览弹窗（复用 PdfPreviewModal）
const pdfPreviewState = ref({ visible: false, url: '', downloadUrl: '', fileName: '' })

// 文献名 → 签名 URL 的内存缓存（30 分钟有效，与 OSS 签名 URL 有效期一致）
const refUrlCache = new Map()

// 事件委托：捕获 .ref-link span 的点击
function handleRefClick(e) {
  const span = e.target.closest('.ref-link')
  if (!span) return
  const name = span.dataset.refName
  if (!name) return
  openRefPopup(name)
}

async function openRefPopup(name) {
  refPopup.value = { visible: true, name, loading: true, previewUrl: '', downloadUrl: '', error: '' }

  // 命中缓存则直接使用，避免重复请求
  if (refUrlCache.has(name)) {
    const cached = refUrlCache.get(name)
    refPopup.value = { ...refPopup.value, ...cached, loading: false }
    return
  }

  try {
    const res = await matchDocumentAPI(name)
    const { previewUrl, downloadUrl } = res.data
    // 写入缓存，30 分钟后自动清除
    refUrlCache.set(name, { previewUrl, downloadUrl })
    setTimeout(() => refUrlCache.delete(name), 30 * 60 * 1000)
    refPopup.value = { ...refPopup.value, previewUrl, downloadUrl, loading: false }
  } catch (e) {
    refPopup.value = { ...refPopup.value, loading: false, error: e?.msg ? '获取文献失败：' + e.msg : '网络错误，请稍后重试' }
  }
}

function openPdfPreview() {
  pdfPreviewState.value = {
    visible: true,
    url: refPopup.value.previewUrl,
    downloadUrl: refPopup.value.downloadUrl,
    fileName: refPopup.value.name,
  }
  refPopup.value.visible = false
}

function downloadRef() {
  if (refPopup.value.downloadUrl) window.open(refPopup.value.downloadUrl, '_blank')
}

onMounted(() => {
  syncLayoutState()
  window.addEventListener('resize', syncLayoutState)
  // 监听滚动，检测用户是否主动上滑
  chatContainerRef.value?.addEventListener('scroll', onChatScroll, { passive: true })
  // 文献引用点击委托（捕获 v-html 内部的 .ref-link span）
  chatContainerRef.value?.addEventListener('click', handleRefClick)
  // 组件挂载时立即渲染一次（应对路由切换时 props 已携带历史消息的情况）
  flushRender(true)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncLayoutState)
  chatContainerRef.value?.removeEventListener('scroll', onChatScroll)
  chatContainerRef.value?.removeEventListener('click', handleRefClick)
  // 取消挂起的 RAF，防止组件卸载后仍触发渲染导致 Vue 警告
  if (renderRafId !== null) {
    cancelAnimationFrame(renderRafId)
    renderRafId = null
  }
})

// 智能滚动：距底部 > 50px 视为用户上滑，暂停自动滚动
function onChatScroll() {
  const el = chatContainerRef.value
  if (!el) return
  const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  userScrolled.value = distFromBottom > 50
}

// ── 【重构】拆分"文本状态"与"渲染状态"，解决 O(N²) 性能陷阱 ───────
// 核心思路：currentTalkList（来自 talk.vue）每个字符都会更新，但 Markdown 解析
// 代价高昂（marked.parse + DOMPurify + 整块 DOM 重建）。
// 通过维护独立的 renderedHtmlList，借助 requestAnimationFrame 将渲染频率限定在
// 浏览器帧率（~16ms/帧, 60fps），既消除 Layout Thrashing，又保证视觉上逐字流畅。
//
// 为什么用 RAF 而非 setTimeout(90ms)：
//   setTimeout(90ms) 会让每次渲染跳过 ~90 字，视觉上仍是"块状蹦字"。
//   RAF 每帧（~16ms）渲染一次，打字机在 16ms 内最多输出 ~16 字，
//   用户看到的是每帧 ~16 字的平滑推进，与 Gemini/ChatGPT 体验一致。
const renderedHtmlList = ref([])
let renderRafId = null

// RAF 驱动的渲染刷新
// immediate=true：取消挂起的 RAF，同步执行渲染（流结束、对话切换、新消息等场景）
// immediate=false：若当前帧内已安排渲染则跳过（同一帧内只渲染一次，天然去抖）
function flushRender(immediate = false) {
  if (!immediate) {
    // 同一帧内已有待执行的 RAF，跳过本次（所有高频字符更新自动合并到下一帧）
    if (renderRafId !== null) return
    renderRafId = requestAnimationFrame(() => {
      renderRafId = null
      doRender()
    })
  } else {
    // 立即渲染：取消挂起的 RAF，同步执行
    if (renderRafId !== null) {
      cancelAnimationFrame(renderRafId)
      renderRafId = null
    }
    doRender()
  }
}

function doRender() {
  renderedHtmlList.value = props.currentTalkList.map((msg, idx) => {
    if (isUserMessage(msg, idx)) return ''
    return renderMarkdown(msgText(msg))
  })
}

// 新消息出现（用户发送 or 历史记录加载）：立即渲染 + 强制滚到底部
watch(
  () => props.currentTalkList.length,
  () => {
    flushRender(true)  // 列表长度变化必须立即同步渲染，保证 AI 占位消息及时出现
    userScrolled.value = false
    nextTick(() => scrollToBottom(true))
  },
)

// 流式更新期间：最后一条 AI 消息内容变化，节流渲染（避免每字符触发 marked.parse）
watch(
  () => props.currentTalkList[props.currentTalkList.length - 1],
  () => {
    flushRender()  // 90ms 节流：高频字符更新被合并为低频 DOM 更新
    if (props.isStreaming || props.isThinking) {
      nextTick(() => {
        if (!userScrolled.value) scrollToBottom()
      })
    }
  },
)

// 流结束：强制立即渲染，确保服务端兜底内容（final content）完整显示，
// 不被挂起的节流任务延迟或覆盖
watch(
  () => props.isStreaming,
  (streaming) => {
    if (!streaming) flushRender(true)
  },
)

watch(
  () => props.currentTalkId,
  () => {
    userScrolled.value = false
    draftMessage.value = ''
    nextTick(() => {
      autoResize()
      scrollToBottom(true)
    })
  },
)

watch(draftMessage, () => {
  nextTick(autoResize)
})

watch(
  () => props.isStreaming,
  (streaming) => {
    if (streaming) {
      isDragOver.value = false
      dragDepth.value = 0
    }
  },
)

const renderMarkdown = (raw = '') => {
  if (!raw) return ''

  // 在 marked 解析前，将《文献名》包裹成可点击 span（方案 A）
  const preprocessed = injectRefLinks(String(raw))

  return DOMPurify.sanitize(
    marked.parse(preprocessed, {
      breaks: true,
      gfm: true,
    }),
    // 允许 ref-link span 上的 data-ref-name 属性通过 DOMPurify 过滤
    { ADD_ATTR: ['data-ref-name'] },
  )
}

function autoResize() {
  const element = inputRef.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 220)}px`
}

// force=true 时忽略 userScrolled，用于新消息出现等必须滚到底的场景
function scrollToBottom(force = false) {
  const el = chatContainerRef.value
  if (!el) return
  if (!force && userScrolled.value) return
  el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
}


function handleSendMessage() {
  const text = draftMessage.value.trim()
  // 有图片时允许空文字发送（纯图片提问）
  if ((!text && imageList.value.length === 0) || props.isStreaming) return
  emit('send-message', {
    text: text || '请分析这张图片',
    images: imageList.value.map((item) => item.dataUrl),
  })
  draftMessage.value = ''
  imageList.value = []
  nextTick(autoResize)
}

async function handleImageSelect(event) {
  await appendImagesFromFiles(event.target.files)
  // 清空 input，允许重复选同一文件
  event.target.value = ''
}

function isSupportedImage(file) {
  return ['image/jpeg', 'image/png', 'image/webp'].includes(file?.type)
}

async function appendImagesFromFiles(fileList) {
  const files = Array.from(fileList || [])
  if (!files.length || props.isStreaming) return

  const imageFiles = files.filter(isSupportedImage)
  if (!imageFiles.length) {
    alert('仅支持上传 JPG、PNG、WEBP 图片')
    return
  }

  const remaining = 3 - imageList.value.length
  if (remaining <= 0) {
    alert('最多上传 3 张图片')
    return
  }

  const toProcess = imageFiles.slice(0, remaining)
  for (const file of toProcess) {
    try {
      const dataUrl = await compressImage(file)
      imageList.value.push({ dataUrl, name: file.name })
    } catch (err) {
      alert(err.message)
    }
  }

  if (imageFiles.length > toProcess.length) {
    alert('最多上传 3 张图片')
  }
}

function handleDragEnter(event) {
  if (props.isStreaming) return
  event.preventDefault()
  dragDepth.value += 1
  isDragOver.value = true
}

function handleDragOver(event) {
  if (props.isStreaming) return
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'copy'
  }
  if (!isDragOver.value) isDragOver.value = true
}

function handleDragLeave(event) {
  event.preventDefault()
  dragDepth.value = Math.max(0, dragDepth.value - 1)
  if (dragDepth.value === 0) {
    isDragOver.value = false
  }
}

async function handleFileDrop(event) {
  event.preventDefault()
  event.stopPropagation()
  dragDepth.value = 0
  isDragOver.value = false
  if (props.isStreaming) return
  await appendImagesFromFiles(event.dataTransfer?.files)
}

function removeImage(index) {
  imageList.value.splice(index, 1)
}

// 消息气泡中图片点击放大
const previewImgUrl = ref('')
function previewMsgImage(url) {
  previewImgUrl.value = url
}
function closePreview() {
  previewImgUrl.value = ''
}

function msgRole(msg, fallbackRole = 'user') {
  if (typeof msg === 'object' && msg !== null && msg.role) {
    return msg.role === 'assistant' ? 'assistant' : 'user'
  }
  return fallbackRole
}

function isUserMessage(msg, index) {
  return msgRole(msg, index % 2 === 0 ? 'user' : 'assistant') === 'user'
}

// 从消息中提取纯文本（兼容字符串、旧对象、role/content 新对象）
function msgText(msg) {
  return typeof msg === 'object' && msg !== null ? (msg.content ?? msg.text ?? msg.message ?? '') : (msg || '')
}

// 从消息中提取图片列表
function msgImages(msg) {
  return typeof msg === 'object' && msg !== null ? (msg.images || []) : []
}

function handleCopy(msg) {
  const text = msgText(msg)
  if (!text) return

  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).catch(() => fallbackCopy(text))
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

// 根据当前消息在 AI 消息序列中的位置获取对应思考记录
function getThinkingData(msgIndex) {
  if (isUserMessage(props.currentTalkList[msgIndex], msgIndex)) return null
  const aiMsgIndex = props.currentTalkList.slice(0, msgIndex + 1).filter((msg, index) => !isUserMessage(msg, index)).length - 1
  const entry = props.thinkingHistoryList[aiMsgIndex]
  return entry?.events?.length ? entry : null
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
          <div class="history-item-content">
            <p class="history-title">{{ talk.title }}</p>
            <small>{{ talk.talkId === NEW_TALK_ID ? '待发送问题' : `会话 #${talk.talkId}` }}</small>
          </div>
          <button type="button" class="ghost-icon history-delete-btn" @click.stop="emit('delete-chat', talk.talkId)">
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
          <span class="state-pill" :class="{ live: isStreaming || isThinking, thinking: isThinking }">
            {{ isThinking ? '思考中' : isStreaming ? '生成中' : '待输入' }}
          </span>
        </div>
      </div>

      <main ref="chatContainerRef" class="chat-messages">
        <div v-if="chatLoading" class="empty-card">正在加载历史对话...</div>

        <div v-else-if="currentTalkList.length" class="message-stack">
          <!-- key 使用纯 index：Vue 复用同一元素，避免每次字符更新都销毁重建整个 article -->
          <article v-for="(msg, index) in currentTalkList" :key="index" class="message-wrapper"
            :class="{ user: isUserMessage(msg, index) }">
            <div class="message-meta">
              <span>{{ isUserMessage(msg, index) ? '医生输入' : 'AI回复' }}</span>
              <button type="button" class="copy-btn" @click="handleCopy(msg)">复制</button>
            </div>

            <div class="message" :class="{ user: isUserMessage(msg, index) }">
              <template v-if="isUserMessage(msg, index)">
                <!-- 图片缩略图（有图时显示，点击放大） -->
                <div v-if="msgImages(msg).length" class="msg-image-list">
                  <img v-for="(imgUrl, i) in msgImages(msg)" :key="i" :src="imgUrl" class="msg-image-thumb" alt="上传图片"
                    @click="previewMsgImage(imgUrl)" />
                </div>
                <div class="plain-text">{{ msgText(msg) }}</div>
              </template>
              <template v-else>
                <!-- ThinkingPanel：有思考记录时显示 DeepSeek 风格思考面板 -->
                <ThinkingPanel v-if="getThinkingData(index)" :thinking-data="getThinkingData(index)"
                  :is-streaming="isThinking && index === currentTalkList.length - 1" />
                <!-- 降级 fallback：无思考记录时显示旧版弹跳点（兼容历史消息） -->
                <div
                  v-if="!msgText(msg) && isThinking && index === currentTalkList.length - 1 && !getThinkingData(index)"
                  class="thinking-indicator">
                  <span class="thinking-dots">
                    <span></span><span></span><span></span>
                  </span>
                  <span class="thinking-text">{{ thinkingHint || 'AI 思考中...' }}</span>
                </div>
                <!--
                  【核心优化】使用 renderedHtmlList[index] 替代直接调用 renderMarkdown(msg)。
                  原版 v-html="renderMarkdown(msg)" 会在每个字符更新时触发完整的
                  marked.parse + DOMPurify + DOM 重建，千字文本下 O(N²) 复杂度导致严重卡顿。
                  现在 renderedHtmlList 由 flushRender 以 ~90ms 节流更新，
                  渲染频率从"每字符一次"降低到"每 90ms 至多一次"，彻底消除 Layout Thrashing。
                -->
                <div class="markdown-body"
                  :class="{ 'streaming-active': isStreaming && index === currentTalkList.length - 1 }"
                  v-html="renderedHtmlList[index] || ''"></div>
              </template>
            </div>
          </article>
        </div>

        <div v-else class="empty-card">输入症状、病史或问题后，AI会在这里持续生成回复。</div>
      </main>

      <div class="input-box" :class="{ 'drag-over': isDragOver }" @dragenter="handleDragEnter"
        @dragover="handleDragOver" @dragleave="handleDragLeave" @drop="handleFileDrop">
        <!-- 图片预览区（有图片时显示） -->
        <div v-if="imageList.length" class="image-preview-bar">
          <div v-for="(item, idx) in imageList" :key="idx" class="image-thumb-wrap">
            <img :src="item.dataUrl" :alt="item.name" class="image-thumb" />
            <button type="button" class="image-remove-btn" @click="removeImage(idx)">×</button>
          </div>
          <span class="image-count">{{ imageList.length }}/3</span>
        </div>
        <div class="input-row">
          <!-- 隐藏文件选择器 -->
          <input ref="fileInputRef" type="file" accept="image/jpeg,image/png,image/webp" multiple style="display:none"
            @change="handleImageSelect" />

          <textarea ref="inputRef" v-model="draftMessage" rows="1"
            :placeholder="imageList.length ? '可补充文字描述（直接发送将询问图片内容）' : '请输入症状、病史或希望AI分析的问题'" @input="autoResize"
            @keydown.enter.exact.prevent="handleSendMessage" />

          <!-- 📎 上传图片按钮 -->
          <button type="button" class="attach-btn" :disabled="imageList.length >= 3 || isStreaming" title="上传图片（最多3张）"
            @click="fileInputRef.click()">
            <AttachFileSVG size="24" color="currentColor" />
          </button>
          <button type="button" class="send-btn" :disabled="(!draftMessage.trim() && !imageList.length) || isStreaming"
            @click="handleSendMessage">
            <SendSVG size="24" color="currentColor" />
          </button>
        </div>
      </div>
    </div>

    <!-- ── 文献引用操作弹窗 ─────────────────────────── -->
    <Teleport to="body">
      <div v-if="refPopup.visible" class="ref-popup-backdrop" @click.self="refPopup.visible = false">
        <div class="ref-popup">
          <p class="ref-popup-title">《{{ refPopup.name }}》</p>
          <div v-if="refPopup.loading" class="ref-popup-status">匹配中...</div>
          <div v-else-if="refPopup.error" class="ref-popup-status error">{{ refPopup.error }}</div>
          <div v-else class="ref-popup-actions">
            <button type="button" class="primary-action" style="width:auto;margin:0"
              @click="openPdfPreview">在线预览</button>
            <button type="button" class="secondary-action" @click="downloadRef">下载</button>
          </div>
          <button type="button" class="ref-popup-close" @click="refPopup.visible = false">×</button>
        </div>
      </div>
    </Teleport>

    <!-- ── PDF 预览弹窗（复用 PdfPreviewModal） ──────── -->
    <PdfPreviewModal :visible="pdfPreviewState.visible" :url="pdfPreviewState.url" :file-name="pdfPreviewState.fileName"
      :download-url="pdfPreviewState.downloadUrl" @close="pdfPreviewState.visible = false" />

    <!-- 图片放大预览 -->
    <Teleport to="body">
      <div v-if="previewImgUrl" class="img-preview-backdrop" @click="closePreview">
        <img :src="previewImgUrl" class="img-preview-full" alt="图片预览" @click.stop />
        <button type="button" class="img-preview-close" @click="closePreview">×</button>
      </div>
    </Teleport>

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
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
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
    display: block;
    color: var(--color-text-weak);
    font-size: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.history-item-content {
  min-width: 0;
}

.history-delete-btn {
  flex-shrink: 0;
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: opacity var(--transition-fast), visibility var(--transition-fast), color var(--transition-fast);
}

.history-item:hover .history-delete-btn,
.history-item:focus-within .history-delete-btn {
  opacity: 1;
  visibility: visible;
  pointer-events: auto;
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

  &.thinking {
    background: rgba(99, 102, 241, 0.12);
    color: #6366f1;
  }
}

/* ─────────────────── Thinking indicator ─────────────────── */
.thinking-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 0;
  color: var(--color-text-medium);
  font-size: 13px;
}

.thinking-text {
  line-height: 1.4;
}

.thinking-dots {
  display: flex;
  gap: 5px;
  flex-shrink: 0;

  span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--color-primary);
    animation: thinking-bounce 1.4s ease-in-out infinite both;

    &:nth-child(2) {
      animation-delay: 0.22s;
    }

    &:nth-child(3) {
      animation-delay: 0.44s;
    }
  }
}

@keyframes thinking-bounce {

  0%,
  80%,
  100% {
    transform: scale(0.55);
    opacity: 0.35;
  }

  40% {
    transform: scale(1);
    opacity: 1;
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

/* ─── 文献引用可点击样式（由 renderMarkdown 注入的 span） ─── */
:deep(.ref-link) {
  color: var(--color-primary, #11967f);
  text-decoration: underline dotted;
  cursor: pointer;
  border-radius: 2px;
  transition: background 0.15s;

  &:hover {
    background: rgba(17, 150, 127, 0.1);
  }
}

/* ─── 文献引用操作弹窗 ─────────────────────────────────── */
.ref-popup-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 900;
}

.ref-popup {
  position: relative;
  background: #fff;
  border-radius: 10px;
  padding: 20px 24px;
  min-width: 260px;
  max-width: 360px;
  box-shadow: 0 6px 30px rgba(0, 0, 0, 0.2);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.ref-popup-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
  padding-right: 24px;
}

.ref-popup-status {
  font-size: 14px;
  color: #6b7280;

  &.error {
    color: #dc2626;
  }
}

.ref-popup-actions {
  display: flex;
  gap: 10px;
}

.ref-popup-close {
  position: absolute;
  top: 10px;
  right: 12px;
  border: none;
  background: transparent;
  font-size: 18px;
  color: #9ca3af;
  cursor: pointer;
  line-height: 1;

  &:hover {
    color: #374151;
  }
}

/* ─────────────────── Input box ─────────────────── */
.input-box {
  border-top: 1px solid var(--color-border);
  padding: 10px 16px;
  background: var(--color-bg-base);
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
  transition: background var(--transition-fast), border-color var(--transition-fast);

  &.drag-over {
    border-top-color: var(--color-primary);
    background: rgba(17, 150, 127, 0.08);
  }
}

/* 图片预览条 */
.image-preview-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.image-thumb-wrap {
  position: relative;
  width: 56px;
  height: 56px;
}

.image-thumb {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--color-border);
}

.image-remove-btn {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--color-text-muted, #888);
  color: #fff;
  font-size: 12px;
  line-height: 18px;
  text-align: center;
  padding: 0;
  border: none;
  cursor: pointer;
}

.image-count {
  font-size: 12px;
  color: var(--color-text-muted);
}

/* 输入行：📎 + textarea + 发送按钮 */
.input-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 48px 48px;
  gap: 8px;
  align-items: start;

  textarea {
    border: none;
    outline: none;
    resize: none;
    min-height: 48px;
    max-height: 180px;
    background: transparent;
    line-height: 1.6;
    font: inherit;
    color: var(--color-text-strong);
    box-sizing: border-box;
    width: 100%;
    padding: 12px 0 12px 12px;
  }
}

/* 用户消息气泡中的图片列表 */
.msg-image-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}

.msg-image-thumb {
  width: 80px;
  height: 80px;
  object-fit: cover;
  border-radius: 6px;
  cursor: zoom-in;
  border: 1px solid rgba(255, 255, 255, 0.3);
}

/* 图片放大预览遮罩 */
.img-preview-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  cursor: zoom-out;
}

.img-preview-full {
  max-width: 90vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: 8px;
  cursor: default;
}

.img-preview-close {
  position: fixed;
  top: 16px;
  right: 20px;
  font-size: 32px;
  color: #fff;
  background: transparent;
  border: none;
  cursor: pointer;
  line-height: 1;
}

.attach-btn {
  width: 48px;
  height: 48px;
  font-size: 18px;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-medium);
  opacity: 0.8;
  border-radius: 50%;

  &:hover {
    opacity: 1;
    background: rgba(0, 0, 0, 0.05);
  }

  &:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }
}

.send-btn {
  width: 48px;
  height: 48px;
  color: var(--color-primary-dark);
  border-radius: 50%;

  &:hover {
    background: rgba(17, 150, 127, 0.1);
  }
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

/* ─────────────────── 流式消息：光标 + 淡入 ─────────────────── */
/* ::after 伪元素在最后一个块级子元素后插入闪烁光标，无需 JS 注入 */
.streaming-active::after {
  content: '▍';
  display: inline;
  margin-left: 1px;
  color: var(--color-primary);
  font-weight: 300;
  animation: streaming-blink 1s step-end infinite;
}

@keyframes streaming-blink {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0;
  }
}

.streaming-active {
  animation: streaming-fadein 200ms ease-out forwards;
}

@keyframes streaming-fadein {
  from {
    opacity: 0.35;
  }

  to {
    opacity: 1;
  }
}

/* ─────────────────── Markdown body ─────────────────── */
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

  .ghost-icon {
    display: none;

    :hover {
      display: inline-flex;
    }
  }
}
</style>

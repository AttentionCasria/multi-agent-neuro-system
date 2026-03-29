<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import UserDialog from '@/components/UserDialog.vue'
import ChatWorkspace from '@/components/workspace/ChatWorkspace.vue'
import LearningWorkspace from '@/components/workspace/LearningWorkspace.vue'
import PatientFormDialog from '@/components/workspace/PatientFormDialog.vue'
import PatientWorkspace from '@/components/workspace/PatientWorkspace.vue'
import WorkspaceTabs from '@/components/workspace/WorkspaceTabs.vue'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'
import {
  deleteChatAPI,
  getChatHistoryAPI,
  getChatTitlesAPI,
  newChatStreamAPI,
  sendQuestionStreamAPI,
} from '@/api/talk'
import {
  createPatientAPI,
  deletePatientAPI,
  getPatientDetailAPI,
  getPatientsAPI,
  updatePatientAPI,
} from '@/api/patient'
import { getLearningMaterialDetailAPI, getLearningMaterialsAPI } from '@/api/learning'
import { analyzePatientAPI, syncTalkToPatientAPI } from '@/api/ai'

defineOptions({ name: 'TalkIndex' })

const tabs = [
  { key: 'chat', label: '智能诊疗', hint: '对话与同步分析' },
  { key: 'patients', label: '患者管理', hint: '病历与AI意见' },
  {
    key: 'learning',
    label: '医生学习',
    hint: '资料检索与阅读',
    children: [
      { key: 'pdfs', label: 'PDF 文档库', shortLabel: 'PDF', description: '浏览院内 PDF 资料并在线预览' },
      { key: 'pubmed', label: 'PubMed 文献', shortLabel: 'PubMed', description: '检索外部医学文献并查看摘要' },
    ],
  },
]

const userStore = useUserStore()
const themeStore = useThemeStore()
const NEW_TALK_ID = ''

const activeTab = ref('chat')
const activeLearningView = ref('pdfs')
const isDialogShow = ref(false)

const talkTitleList = ref([])
const currentTalkId = ref(NEW_TALK_ID)
const currentTalkList = ref([])
const isStreaming = ref(false)
// isThinking：收到第一个 chunk 之前，AI 处于推理（thinking）阶段
const isThinking = ref(false)
// thinkingHint：thinking 事件中的 title/step 字段，用于显示当前推理步骤
const thinkingHint = ref('')
// thinkingHistoryList：每条 AI 回答对应一个思考记录 {events, elapsedSeconds, startTime}
const thinkingHistoryList = ref([])
const chatLoading = ref(false)
const deleteAllLoading = ref(false)

const patientQuery = ref({ page: 1, size: 8, name: '', diseases: '' })
const patients = ref([])
const patientTotal = ref(0)
const patientsLoading = ref(false)
const selectedPatientId = ref(null)
const patientDetail = ref(null)
const patientDetailLoading = ref(false)
const patientFormVisible = ref(false)
const patientFormMode = ref('create')
const patientSubmitting = ref(false)
const patientAnalysisLoading = ref(false)
const patientAnalysisText = ref('')
const patientForm = ref({ id: null, name: '', history: '', notes: '' })

const learningQuery = ref({ category: '', page: 1, size: 8 })
const materials = ref([])
const learningTotal = ref(0)
const materialsLoading = ref(false)
const selectedMaterialId = ref(null)
const materialDetail = ref(null)
const materialDetailLoading = ref(false)

const syncPatientId = ref(null)
const syncLoading = ref(false)
const syncResult = ref(null)

const patientsLoaded = ref(false)
const materialsLoaded = ref(false)

const overlayVisible = computed(
  () => deleteAllLoading.value || patientSubmitting.value || patientAnalysisLoading.value || syncLoading.value,
)

const patientPageCount = computed(() => Math.max(1, Math.ceil(patientTotal.value / patientQuery.value.size) || 1))
const materialPageCount = computed(() => Math.max(1, Math.ceil(learningTotal.value / learningQuery.value.size) || 1))

const syncPatient = computed(() => {
  if (!syncPatientId.value) return null

  if (patientDetail.value?.id === syncPatientId.value) {
    return patientDetail.value
  }

  return patients.value.find((patient) => patient.id === syncPatientId.value) || null
})

function normalizeTalkMessage(message, fallbackRole = 'user') {
  if (typeof message === 'string') {
    return {
      role: fallbackRole,
      content: String(message || ''),
      images: [],
    }
  }

  if (!message || typeof message !== 'object') {
    return {
      role: fallbackRole,
      content: '',
      images: [],
    }
  }

  const role = message.role === 'assistant' ? 'assistant' : 'user'
  const content = String(message.content ?? message.text ?? message.message ?? '')
  const images = Array.isArray(message.images)
    ? message.images.map((item) => String(item || '')).filter(Boolean)
    : []

  return {
    role,
    content,
    images,
  }
}

const conversationPayload = computed(() =>
  currentTalkList.value
    .map((message, index) => {
      const normalized = normalizeTalkMessage(message, index % 2 === 0 ? 'user' : 'assistant')
      return {
        role: normalized.role,
        content: normalized.content.trim(),
      }
    })
    .filter((item) => item.content),
)

const canSyncConversation = computed(
  () => !!syncPatientId.value && !!currentTalkId.value && conversationPayload.value.length >= 2 && !isStreaming.value,
)

const conversationPreview = computed(() => conversationPayload.value.slice(-4))

watch(activeTab, (tab) => {
  if (tab === 'patients' && !patientsLoaded.value) {
    fetchPatients()
  }

  if (tab === 'learning' && !materialsLoaded.value) {
    fetchMaterials()
  }
})

onMounted(async () => {
  await Promise.allSettled([fetchTalkTitle(), fetchPatients()])
})

function normalizeTalkTitles(payload) {
  const source = Array.isArray(payload) ? payload : Array.isArray(payload?.titles) ? payload.titles : []

  return source
    .map((item) => ({
      talkId: normalizeTalkId(item?.talkId ?? item?.id),
      title: String(item?.title ?? item?.name ?? '未命名对话'),
    }))
    .filter((item) => item.talkId)
}

function normalizeTalkId(value) {
  if (value === null || value === undefined) return NEW_TALK_ID

  const talkId = String(value).trim()
  return talkId || NEW_TALK_ID
}

function normalizeTalkHistory(payload) {
  const source = Array.isArray(payload) ? payload : Array.isArray(payload?.conversation) ? payload.conversation : []

  return source
    .map((item, index) => normalizeTalkMessage(item, index % 2 === 0 ? 'user' : 'assistant'))
    .filter((item) => item.content || item.images.length)
}

function normalizeAiOpinion(aiOpinion) {
  if (!aiOpinion) return null

  if (typeof aiOpinion === 'string') {
    return {
      riskLevel: '',
      suggestion: aiOpinion,
      analysisDetails: '',
      lastUpdatedAt: '',
    }
  }

  return {
    riskLevel: String(aiOpinion.riskLevel || ''),
    suggestion: String(aiOpinion.suggestion || ''),
    analysisDetails: String(aiOpinion.analysisDetails || ''),
    lastUpdatedAt: String(aiOpinion.lastUpdatedAt || ''),
  }
}

function normalizePatient(patient) {
  const aiOpinion = normalizeAiOpinion(patient?.aiOpinion)

  return {
    id: Number(patient?.id || 0),
    name: String(patient?.name || '未命名患者'),
    history: String(patient?.history || ''),
    notes: String(patient?.notes || ''),
    aiOpinion,
    aiSummary: aiOpinion?.suggestion || aiOpinion?.analysisDetails || '暂无AI建议',
  }
}

// 只刷新标题列表，不重新加载历史对话
// handleSendMessage 结束时调用此函数，避免 fetchTalkHistory 清空并重建 currentTalkList 导致 scroll 归零
async function refreshTitleList() {
  try {
    const res = await getChatTitlesAPI()
    const titles = normalizeTalkTitles(res.data)
    // 只更新列表，不改变 currentTalkId，不触发 fetchTalkHistory
    talkTitleList.value = titles
    // 如果当前是新对话且已有真实 talkId，更新 currentTalkId 使其与列表对齐
    if (currentTalkId.value !== NEW_TALK_ID) {
      const found = titles.find((t) => t.talkId === currentTalkId.value)
      if (found) talkTitleList.value = titles  // 已对齐，无需其他操作
    }
  } catch (error) {
    console.error('刷新标题列表失败', error)
  }
}

async function fetchTalkTitle() {
  try {
    const res = await getChatTitlesAPI()
    talkTitleList.value = normalizeTalkTitles(res.data)

    if (!talkTitleList.value.length) {
      currentTalkId.value = NEW_TALK_ID
      currentTalkList.value = []
      return
    }

    const preferredTalk = talkTitleList.value.find((talk) => talk.talkId === currentTalkId.value)
    const firstValidTalk = preferredTalk || talkTitleList.value.find((talk) => talk.talkId !== NEW_TALK_ID) || talkTitleList.value[0]

    currentTalkId.value = firstValidTalk.talkId
    await fetchTalkHistory(firstValidTalk.talkId)
  } catch (error) {
    console.error('获取对话标题失败', error)
  }
}

async function fetchTalkHistory(talkId = currentTalkId.value) {
  if (!talkId) {
    currentTalkList.value = []
    thinkingHistoryList.value = []
    return
  }

  chatLoading.value = true
  isDialogShow.value = false
  try {
    const res = await getChatHistoryAPI(talkId)
    currentTalkList.value = normalizeTalkHistory(res.data)
    // 加载历史对话时重置思考记录（历史消息不显示思考面板）
    thinkingHistoryList.value = []
  } catch (error) {
    console.error('获取历史对话失败', error)
    currentTalkList.value = []
    thinkingHistoryList.value = []
  } finally {
    chatLoading.value = false
  }
}

function handleSelectTalk(talkId) {
  if (talkId === currentTalkId.value) return
  currentTalkId.value = talkId
  fetchTalkHistory(talkId)
}

function handleNewChat() {
  currentTalkId.value = NEW_TALK_ID
  currentTalkList.value = []
  thinkingHistoryList.value = []
  talkTitleList.value = talkTitleList.value.filter((talk) => talk.talkId !== NEW_TALK_ID)
  talkTitleList.value.unshift({ talkId: NEW_TALK_ID, title: '新对话' })
}

// ── 【新增】Unicode/Emoji 安全拆分 ──────────────────────────────────
// 使用 Intl.Segmenter（现代浏览器原生支持）将 chunk 拆成字位簇（grapheme clusters），
// 保证由多个码位组成的复杂 Emoji（如 👨‍👩‍👧、🏳️‍🌈）不被强行截断导致乱码闪烁。
// 降级到 Array.from() 以正确处理代理对（surrogate pairs），
// 比旧版 charBuffer.push(...chunk) 的展开运算符更安全。
function safeChunkToChars(chunk) {
  if (typeof Intl !== 'undefined' && Intl.Segmenter) {
    const segmenter = new Intl.Segmenter()
    return [...segmenter.segment(chunk)].map((s) => s.segment)
  }
  // 降级方案：Array.from 可处理代理对，但不处理组合字符序列
  return Array.from(chunk)
}

async function handleSendMessage({ text, images } = {}) {
  if (!text || isStreaming.value) return

  isStreaming.value = true
  isThinking.value = true   // 流开始前先进入 thinking 阶段
  thinkingHint.value = ''
  currentTalkList.value.push({
    role: 'user',
    content: text,
    images: Array.isArray(images) ? images : [],
  })
  currentTalkList.value.push({ role: 'assistant', content: '', images: [] })
  const aiIndex = currentTalkList.value.length - 1

  // 为本次 AI 回答初始化独立的思考记录
  const thinkingEntry = reactive({ events: [], elapsedSeconds: null, startTime: Date.now() })
  thinkingHistoryList.value.push(thinkingEntry)

  // thinking 事件回调：更新推理步骤提示，同时追加事件到思考记录
  const onThinking = (thinking) => {
    thinkingHint.value = thinking.title || thinking.step || 'AI 思考中...'
    thinkingEntry.events.push({
      step: thinking.step || '',
      title: thinking.title || '',
      content: thinking.content || '',
    })
  }

  // ── 打字机缓冲区（仅作用于本次对话的生命周期）──────────────────
  const charBuffer = []   // 字符缓冲池，网络 chunk 先推入此处
  let displayText = ''    // 已输出到屏幕的累积文本
  let timerId = null      // setTimeout 句柄（替换 RAF，以便精确控制输出间隔）

  // ── 【重写】打字机调速算法：动态 Delay 而非动态 Batch Size ────────
  // 黄金法则：永远每次输出固定 1-2 个字符，维持极度平滑的视觉感受。
  // 旧算法（改变单次输出数量）在积压时会一次蹦出 8-12 字，彻底失去打字机感。
  // 新算法通过动态调整 setTimeout delay 来追赶积压，视觉上始终平滑：
  //   - 积压 > 200 字：2ms 超短间隔密集吐字（追赶模式）
  //   - 积压 50~200 字：8ms 快速消耗
  //   - 积压 < 50 字：25ms 恢复正常打字节奏
  function startTypewriter() {
    if (timerId !== null) return  // 已在运行，不重复启动
    function tick() {
      if (charBuffer.length === 0) {
        timerId = null
        return
      }
      const pending = charBuffer.length
      const delay = pending > 200 ? 2 : pending > 50 ? 8 : 25
      // 固定每次输出 1-2 个字符，保持视觉连续性（不随积压量增大 batch）
      const chars = charBuffer.splice(0, 2)
      displayText += chars.join('')
      currentTalkList.value[aiIndex] = { role: 'assistant', content: displayText, images: [] }
      timerId = setTimeout(tick, delay)
    }
    timerId = setTimeout(tick, 0)
  }

  // chunk 事件回调：收到第一个 chunk 即结束 thinking 阶段，记录思考用时
  const onChunk = (chunk) => {
    if (isThinking.value) {
      isThinking.value = false
      thinkingHint.value = ''
      thinkingEntry.elapsedSeconds = Math.round((Date.now() - thinkingEntry.startTime) / 1000)
    }
    // 【修复】使用 safeChunkToChars 安全拆分 Unicode/Emoji，
    // 废弃旧版 charBuffer.push(...chunk) 展开字符串，防止多码位字符被截断乱码
    charBuffer.push(...safeChunkToChars(chunk))
    startTypewriter()
  }

  try {
    // 构造请求参数，有图片时携带 images 列表（影像识别功能）
    const imagesPayload = images && images.length ? { images } : {}
    const finalResult =
      currentTalkId.value === NEW_TALK_ID
        ? await newChatStreamAPI({ question: text, ...imagesPayload }, onChunk, onThinking)
        : await sendQuestionStreamAPI(
          { talkId: currentTalkId.value, question: text, ...imagesPayload },
          onChunk,
          onThinking,
        )

    const { title, content } = finalResult.data || {}
    const talkId = normalizeTalkId(finalResult.data?.talkId)

    // done 到达后先等打字机把缓冲区自然排空，解决 consultant/multi-mcq 大块文字一次性蹦出的问题
    // knowledge 的缓冲区在 done 到达时通常已接近空，等待时间极短
    if (charBuffer.length > 0) {
      await new Promise((resolve) => {
        function waitDrain() {
          if (charBuffer.length === 0) resolve()
          else requestAnimationFrame(waitDrain)
        }
        waitDrain()
      })
    }

    // 缓冲区已空，停止打字机，再用服务端最终内容兜底（防止极端情况下少字）
    if (timerId !== null) { clearTimeout(timerId); timerId = null }
    if (typeof content === 'string') {
      currentTalkList.value[aiIndex] = { role: 'assistant', content, images: [] }
    } else {
      currentTalkList.value[aiIndex] = { role: 'assistant', content: displayText, images: [] }
    }

    if (currentTalkId.value === NEW_TALK_ID && talkId) {
      currentTalkId.value = talkId
      const placeholderIndex = talkTitleList.value.findIndex((talk) => talk.talkId === NEW_TALK_ID)

      if (placeholderIndex !== -1) {
        talkTitleList.value[placeholderIndex] = { talkId, title: title || '新对话' }
      } else {
        talkTitleList.value.unshift({ talkId, title: title || '新对话' })
      }
    }

    await refreshTitleList()
  } catch (error) {
    console.error('发送消息失败', error)
    currentTalkList.value.splice(aiIndex, 1)
    currentTalkList.value.pop()
    // 利用结构化错误码：retryable=true 提示用户可以重试
    const retryTip = error.retryable ? '\n请稍后重试。' : ''
    alert(error?.msg || error?.message || `发送失败，请稍后再试${retryTip}`)
  } finally {
    isStreaming.value = false
    isThinking.value = false
    thinkingHint.value = ''
  }
}

async function handleDeleteChat(talkId) {
  if (!talkId || talkId === NEW_TALK_ID) {
    handleNewChat()
    return
  }

  if (!window.confirm('确定要删除此对话吗？')) return

  try {
    await deleteChatAPI(talkId)
    talkTitleList.value = talkTitleList.value.filter((talk) => talk.talkId !== talkId)

    if (currentTalkId.value === talkId) {
      const nextTalk = talkTitleList.value.find((talk) => talk.talkId !== NEW_TALK_ID)
      currentTalkId.value = nextTalk?.talkId || NEW_TALK_ID
      if (nextTalk) {
        await fetchTalkHistory(nextTalk.talkId)
      } else {
        handleNewChat()
      }
    }
  } catch (error) {
    console.error('删除对话失败', error)
    alert(error?.msg || '删除失败')
  }
}

async function handleDeleteAll() {
  const ids = talkTitleList.value.map((talk) => talk.talkId).filter((talkId) => talkId !== NEW_TALK_ID)
  if (!ids.length) return
  if (!window.confirm('确定删除所有历史对话吗？')) return

  deleteAllLoading.value = true
  try {
    await Promise.all(ids.map((talkId) => deleteChatAPI(talkId)))
    talkTitleList.value = []
    handleNewChat()
  } catch (error) {
    console.error('清空对话失败', error)
    alert(error?.msg || '删除失败，请重试')
  } finally {
    deleteAllLoading.value = false
  }
}

async function fetchPatients() {
  patientsLoading.value = true

  try {
    const res = await getPatientsAPI({
      page: patientQuery.value.page,
      size: patientQuery.value.size,
      filter: {
        name: patientQuery.value.name.trim(),
        diseases: patientQuery.value.diseases.trim(),
      },
    })

    const list = Array.isArray(res.data?.patients) ? res.data.patients : []
    patients.value = list.map(normalizePatient)
    patientTotal.value = Number(res.data?.total || 0)
    patientsLoaded.value = true

    if (!patients.value.length) {
      selectedPatientId.value = null
      patientDetail.value = null
      syncPatientId.value = null
      return
    }

    if (!syncPatientId.value || !patients.value.some((patient) => patient.id === syncPatientId.value)) {
      syncPatientId.value = patients.value[0].id
    }

    const preferredId =
      selectedPatientId.value && patients.value.some((patient) => patient.id === selectedPatientId.value)
        ? selectedPatientId.value
        : patients.value[0].id

    if (activeTab.value === 'patients' || !patientDetail.value || patientDetail.value.id !== preferredId) {
      await handleSelectPatient(preferredId)
    }
  } catch (error) {
    console.error('获取患者列表失败', error)
    alert(error?.msg || '获取患者列表失败')
  } finally {
    patientsLoading.value = false
  }
}

async function handleSelectPatient(patientId) {
  if (!patientId) return

  selectedPatientId.value = patientId
  patientDetailLoading.value = true

  try {
    const res = await getPatientDetailAPI(patientId)
    patientDetail.value = normalizePatient(res.data)
  } catch (error) {
    console.error('获取患者详情失败', error)
    alert(error?.msg || '获取患者详情失败')
  } finally {
    patientDetailLoading.value = false
  }
}

function resetPatientForm() {
  patientForm.value = { id: null, name: '', history: '', notes: '' }
}

function openCreatePatient() {
  patientFormMode.value = 'create'
  resetPatientForm()
  patientFormVisible.value = true
}

function openEditPatient(patient) {
  patientFormMode.value = 'edit'
  patientForm.value = {
    id: patient.id,
    name: patient.name,
    history: patient.history,
    notes: patient.notes,
  }
  patientFormVisible.value = true
}

async function submitPatientForm() {
  const payload = {
    name: patientForm.value.name.trim(),
    history: patientForm.value.history.trim(),
    notes: patientForm.value.notes.trim(),
  }

  if (!payload.name) {
    alert('患者姓名不能为空')
    return
  }

  patientSubmitting.value = true

  try {
    if (patientFormMode.value === 'edit' && patientForm.value.id) {
      await updatePatientAPI(patientForm.value.id, payload)
      selectedPatientId.value = patientForm.value.id
    } else {
      const res = await createPatientAPI(payload)
      selectedPatientId.value = Number(res.data?.id || selectedPatientId.value)
    }

    patientFormVisible.value = false
    resetPatientForm()
    await fetchPatients()

    if (selectedPatientId.value) {
      await handleSelectPatient(selectedPatientId.value)
    }
  } catch (error) {
    console.error('保存患者失败', error)
    alert(error?.msg || '保存患者失败')
  } finally {
    patientSubmitting.value = false
  }
}

async function handleDeletePatient(patientId) {
  if (!window.confirm('确定删除该患者吗？')) return

  try {
    await deletePatientAPI(patientId)

    if (selectedPatientId.value === patientId) {
      selectedPatientId.value = null
      patientDetail.value = null
    }

    if (syncPatientId.value === patientId) {
      syncPatientId.value = null
    }

    await fetchPatients()
  } catch (error) {
    console.error('删除患者失败', error)
    alert(error?.msg || '删除患者失败')
  }
}

async function handleAnalyzePatient() {
  if (!selectedPatientId.value) {
    alert('请先选择患者')
    return
  }

  const data = patientAnalysisText.value.trim()
  if (!data) {
    alert('请输入需要提交给AI的补充健康数据')
    return
  }

  patientAnalysisLoading.value = true

  try {
    const res = await analyzePatientAPI({
      patientId: selectedPatientId.value,
      data,
    })

    patientDetail.value = {
      ...(patientDetail.value || {}),
      id: selectedPatientId.value,
      name: patientDetail.value?.name || '',
      history: patientDetail.value?.history || '',
      notes: patientDetail.value?.notes || '',
      aiOpinion: normalizeAiOpinion(res.data),
      aiSummary: res.data?.suggestion || res.data?.analysisDetails || '暂无AI建议',
    }

    patientAnalysisText.value = ''
    await fetchPatients()
    await handleSelectPatient(selectedPatientId.value)
    alert('AI分析已更新')
  } catch (error) {
    console.error('AI分析失败', error)
    alert(error?.msg || 'AI分析失败')
  } finally {
    patientAnalysisLoading.value = false
  }
}

async function fetchMaterials() {
  materialsLoading.value = true

  try {
    const res = await getLearningMaterialsAPI({
      category: learningQuery.value.category.trim(),
      page: learningQuery.value.page,
      size: learningQuery.value.size,
    })

    materials.value = Array.isArray(res.data?.materials) ? res.data.materials : []
    learningTotal.value = Number(res.data?.total || 0)
    materialsLoaded.value = true

    if (!materials.value.length) {
      selectedMaterialId.value = null
      materialDetail.value = null
      return
    }

    const preferredId = materials.value.some((item) => item.id === selectedMaterialId.value)
      ? selectedMaterialId.value
      : materials.value[0].id

    await handleSelectMaterial(preferredId)
  } catch (error) {
    console.error('获取学习资料失败', error)
    alert(error?.msg || '获取学习资料失败')
  } finally {
    materialsLoading.value = false
  }
}

async function handleSelectMaterial(materialId) {
  if (!materialId) return

  selectedMaterialId.value = materialId
  materialDetailLoading.value = true

  try {
    const res = await getLearningMaterialDetailAPI(materialId)
    materialDetail.value = res.data || null
  } catch (error) {
    console.error('获取资料详情失败', error)
    alert(error?.msg || '获取资料详情失败')
  } finally {
    materialDetailLoading.value = false
  }
}

function openMaterialLink(value) {
  if (!value) return
  window.open(value, '_blank', 'noopener,noreferrer')
}

async function handleSyncConversation() {
  if (!canSyncConversation.value) {
    alert('请先选择患者，并确保当前对话已经生成回答')
    return
  }

  if (!window.confirm('确认将当前对话同步到患者AI分析吗？')) return

  syncLoading.value = true

  try {
    const res = await syncTalkToPatientAPI({
      patientId: syncPatientId.value,
      talkId: currentTalkId.value,
      conversation: conversationPayload.value,
      mergeWithHistory: true,
    })

    syncResult.value = res.data || null
    await fetchPatients()

    if (selectedPatientId.value === syncPatientId.value || !selectedPatientId.value) {
      selectedPatientId.value = syncPatientId.value
      await handleSelectPatient(syncPatientId.value)
    }

    alert('同步完成，患者AI意见已更新')
  } catch (error) {
    console.error('同步对话失败', error)
    alert(error?.msg || '同步失败')
  } finally {
    syncLoading.value = false
  }
}

function handlePatientSearch() {
  patientQuery.value.page = 1
  fetchPatients()
}

function goPatientPage(delta) {
  const nextPage = patientQuery.value.page + delta
  if (nextPage < 1 || nextPage > patientPageCount.value) return
  patientQuery.value.page = nextPage
  fetchPatients()
}

function handleMaterialSearch() {
  learningQuery.value.page = 1
  fetchMaterials()
}

function handleWorkspaceTabChange(payload) {
  if (!payload?.key) return

  activeTab.value = payload.key

  if (payload.key === 'learning' && payload.childKey) {
    activeLearningView.value = payload.childKey
  }
}

function goMaterialPage(delta) {
  const nextPage = learningQuery.value.page + delta
  if (nextPage < 1 || nextPage > materialPageCount.value) return
  learningQuery.value.page = nextPage
  fetchMaterials()
}

function openPatientWorkspace(patientId) {
  activeTab.value = 'patients'
  if (patientId) {
    handleSelectPatient(patientId)
  }
}
</script>

<template>
  <div class="workspace-shell">
    <div v-if="overlayVisible" class="page-overlay">
      <div class="overlay-card">
        <div class="spinner"></div>
        <p>正在处理，请稍候...</p>
      </div>
    </div>


    <section class="tab-section">
      <WorkspaceTabs :tabs="tabs" :active-tab="activeTab" :active-child-tab="activeLearningView"
        @change="handleWorkspaceTabChange" />
      <div class="header-right">
        <button type="button" class="theme-toggle" :title="themeStore.dark ? '切换到浅色模式' : '切换到深色模式'"
          @click="themeStore.toggle()">
          <svg v-if="themeStore.dark" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="5" />
            <line x1="12" y1="1" x2="12" y2="3" />
            <line x1="12" y1="21" x2="12" y2="23" />
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
            <line x1="1" y1="12" x2="3" y2="12" />
            <line x1="21" y1="12" x2="23" y2="12" />
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
          </svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </button>
        <div class="user-anchor" @click="isDialogShow = !isDialogShow">
          <AppAvatar class="avatar" :src="userStore.image" :name="userStore.name" :size="24" alt="avatar" />
          <p class="user-name">{{ userStore.name || '医生' }}</p>
          <UserDialog :visible="isDialogShow" @close="isDialogShow = false" />
        </div>
      </div>
    </section>

    <main class="workspace-content">
      <ChatWorkspace v-if="activeTab === 'chat'" v-model:sync-patient-id="syncPatientId"
        :talk-title-list="talkTitleList" :current-talk-id="currentTalkId" :current-talk-list="currentTalkList"
        :is-streaming="isStreaming" :is-thinking="isThinking" :thinking-hint="thinkingHint"
        :thinking-history-list="thinkingHistoryList" :chat-loading="chatLoading" :patients="patients"
        :sync-patient="syncPatient" :conversation-preview="conversationPreview"
        :can-sync-conversation="canSyncConversation" :sync-result="syncResult" @select-talk="handleSelectTalk"
        @new-chat="handleNewChat" @delete-chat="handleDeleteChat" @delete-all="handleDeleteAll"
        @send-message="handleSendMessage" @sync-conversation="handleSyncConversation"
        @open-patient-workspace="openPatientWorkspace" />

      <PatientWorkspace v-else-if="activeTab === 'patients'" v-model:query="patientQuery"
        v-model:analysis-text="patientAnalysisText" :patients="patients" :patient-total="patientTotal"
        :patients-loading="patientsLoading" :selected-patient-id="selectedPatientId" :patient-detail="patientDetail"
        :patient-detail-loading="patientDetailLoading" :patient-page-count="patientPageCount"
        @search="handlePatientSearch" @select-patient="handleSelectPatient" @open-create="openCreatePatient"
        @open-edit="openEditPatient" @delete-patient="handleDeletePatient" @analyze-patient="handleAnalyzePatient"
        @page-change="goPatientPage" />

      <LearningWorkspace v-else v-model:query="learningQuery" v-model:view="activeLearningView" :materials="materials"
        :learning-total="learningTotal" :materials-loading="materialsLoading" :selected-material-id="selectedMaterialId"
        :material-detail="materialDetail" :material-detail-loading="materialDetailLoading"
        :material-page-count="materialPageCount" @search="handleMaterialSearch" @select-material="handleSelectMaterial"
        @page-change="goMaterialPage" @open-material-link="openMaterialLink" />
    </main>

    <PatientFormDialog v-model:form="patientForm" :visible="patientFormVisible" :mode="patientFormMode"
      @close="patientFormVisible = false" @submit="submitPatientForm" />
  </div>
</template>

<style scoped lang="scss">
:global(body) {
  margin: 0;
  background: var(--color-bg-base);
}

.workspace-shell {
  height: 100dvh;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  color: var(--color-text-strong);
  background: var(--color-bg-base);
}

.tab-section {
  height: 52px;
  padding: 0 20px;
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-base);
  flex-shrink: 0;
}

.workspace-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.user-anchor {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  padding: 0 12px;
  margin: 6px 0;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-normal);

  &:hover {
    background: var(--color-ghost-hover);
  }
}

.user-name {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-medium);
  cursor: pointer;
  transition: all var(--transition-normal);

  &:hover {
    background: var(--color-ghost-hover);
    color: var(--color-text-strong);
  }
}

.user-anchor small {
  color: var(--color-text-medium);
  font-size: 12px;
}

.page-overlay {
  position: fixed;
  inset: 0;
  background: var(--color-overlay-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.overlay-card {
  width: 220px;
  padding: 28px 22px;
  border-radius: 16px;
  background: var(--color-bg-base);
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;

  p {
    color: var(--color-text-medium);
    margin: 0;
    font-size: 14px;
  }
}

@keyframes rotate {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 960px) {
  .tab-section {
    height: 44px;
  }

  .user-name {
    display: none;
  }

  .workspace-content {
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
  }

  .user-anchor {
    margin: 0;
  }
}
</style>

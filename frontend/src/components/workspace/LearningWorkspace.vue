<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import VuePdfEmbed from 'vue-pdf-embed'
import * as pdfjsLib from 'pdfjs-dist'
import PapersSidebar from './PapersSidebar.vue'
import { getDocumentsAPI, getDocumentUrlAPI } from '@/api/documents'
import { searchPubMedAPI } from '@/api/learning'
import FileSVG from '../svg/FileSVG.vue'
import UpSVG from '../svg/UpSVG.vue'
import DownSVG from '../svg/DownSVG.vue'

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.js',
  import.meta.url,
).href

defineOptions({ name: 'LearningWorkspace' })

defineProps({
  materials: {
    type: Array,
    default: () => [],
  },
  learningTotal: {
    type: Number,
    default: 0,
  },
  materialsLoading: {
    type: Boolean,
    default: false,
  },
  selectedMaterialId: {
    type: [Number, null],
    default: null,
  },
  materialDetail: {
    type: Object,
    default: null,
  },
  materialDetailLoading: {
    type: Boolean,
    default: false,
  },
  materialPageCount: {
    type: Number,
    default: 1,
  },
})

defineModel('query', { required: true })
const activeView = defineModel('view', { default: 'pdfs' })
defineEmits(['search', 'select-material', 'page-change', 'open-material-link'])

const MOBILE_BREAKPOINT = 900
const isMobileLayout = ref(false)
const activeMobilePane = ref('list')

const pdfLoading = ref(false)
const pdfError = ref('')
const pdfDocuments = ref({})
const activeCategory = ref('')
const selectedPdfId = ref(null)
const pdfPreviewCache = ref({})
const pdfRequestToken = ref(0)
const pdfPreviewState = ref(createEmptyPdfPreview())

const pubmedQuery = ref('')
const pubmedLoading = ref(false)
const pubmedError = ref('')
const pubmedPapers = ref([])
const pubmedSearched = ref(false)
const activePaperPmid = ref('')

const pdfCategories = computed(() => Object.keys(pdfDocuments.value))
const categoryDocs = computed(() =>
  activeCategory.value ? (pdfDocuments.value[activeCategory.value] || []) : [],
)
const currentPdfDoc = computed(() =>
  categoryDocs.value.find((doc) => doc.id === selectedPdfId.value) || null,
)
const currentPaper = computed(() =>
  pubmedPapers.value.find((paper) => paper.pmid === activePaperPmid.value) || null,
)

const EVIDENCE_HIGH = new Set(['Practice Guideline', 'Guideline', 'Meta-Analysis', 'Systematic Review'])
const EVIDENCE_MID = new Set(['Randomized Controlled Trial', 'Clinical Trial'])
const DISPLAY_TYPES = new Set([
  'Practice Guideline',
  'Guideline',
  'Meta-Analysis',
  'Systematic Review',
  'Randomized Controlled Trial',
  'Clinical Trial',
  'Review',
  'Case Reports',
])

function createEmptyPdfPreview() {
  return {
    fileName: '',
    url: '',
    downloadUrl: '',
    loading: false,
    error: '',
    currentPage: 1,
    totalPages: 0,
  }
}

function updateLayoutMode() {
  isMobileLayout.value = window.innerWidth <= MOBILE_BREAKPOINT
  if (!isMobileLayout.value) {
    activeMobilePane.value = 'list'
  }
}

function shortText(value, fallback = '暂无内容') {
  const text = String(value || '').trim()
  return text || fallback
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function getFileExtension(fileName) {
  const match = String(fileName || '').trim().match(/\.([a-z0-9]+)$/i)
  return (match?.[1] || 'FILE').slice(0, 4).toUpperCase()
}

function displayTypes(pubTypes) {
  return (pubTypes || []).filter((type) => DISPLAY_TYPES.has(type))
}

function pillClass(type) {
  if (EVIDENCE_HIGH.has(type)) return 'pill pill--high'
  if (EVIDENCE_MID.has(type)) return 'pill pill--mid'
  return 'pill pill--low'
}

async function loadPdfDocuments() {
  pdfLoading.value = true
  pdfError.value = ''

  try {
    const res = await getDocumentsAPI()
    pdfDocuments.value = res.data || {}
    const categories = Object.keys(pdfDocuments.value)
    activeCategory.value = categories[0] || ''
  } catch (error) {
    pdfError.value = error?.msg || '网络错误，请稍后重试'
  } finally {
    pdfLoading.value = false
  }
}

async function selectPdfDoc(doc, options = {}) {
  if (!doc?.id) return

  selectedPdfId.value = doc.id
  if (options.switchPane && isMobileLayout.value) {
    activeMobilePane.value = 'preview'
  }

  const cached = pdfPreviewCache.value[doc.id]
  pdfPreviewState.value = {
    fileName: doc.name,
    url: cached?.url || '',
    downloadUrl: cached?.downloadUrl || '',
    loading: true,
    error: '',
    currentPage: 1,
    totalPages: cached?.totalPages || 0,
  }

  if (cached?.url) return

  const token = ++pdfRequestToken.value
  try {
    const res = await getDocumentUrlAPI(doc.id)
    if (token !== pdfRequestToken.value || selectedPdfId.value !== doc.id) return

    pdfPreviewCache.value = {
      ...pdfPreviewCache.value,
      [doc.id]: {
        url: res.data.previewUrl,
        downloadUrl: res.data.downloadUrl,
        totalPages: 0,
      },
    }
    pdfPreviewState.value = {
      ...pdfPreviewState.value,
      url: res.data.previewUrl,
      downloadUrl: res.data.downloadUrl,
      loading: true,
      error: '',
    }
  } catch (error) {
    if (token !== pdfRequestToken.value || selectedPdfId.value !== doc.id) return
    pdfPreviewState.value = {
      ...createEmptyPdfPreview(),
      fileName: doc.name,
      error: error?.msg || '网络错误，无法获取预览链接',
    }
  }
}

function handlePdfLoaded(pdf) {
  const totalPages = pdf?.numPages ?? pdfPreviewState.value.totalPages ?? 0
  pdfPreviewState.value = {
    ...pdfPreviewState.value,
    loading: false,
    totalPages,
  }

  if (!selectedPdfId.value) return

  const cached = pdfPreviewCache.value[selectedPdfId.value]
  if (!cached) return

  pdfPreviewCache.value = {
    ...pdfPreviewCache.value,
    [selectedPdfId.value]: {
      ...cached,
      totalPages,
    },
  }
}

function goPdfPage(direction) {
  if (!pdfPreviewState.value.totalPages) return

  const nextPage = pdfPreviewState.value.currentPage + direction
  if (nextPage < 1 || nextPage > pdfPreviewState.value.totalPages) return

  pdfPreviewState.value = {
    ...pdfPreviewState.value,
    currentPage: nextPage,
  }
}

async function handlePubMedSearch() {
  const keyword = pubmedQuery.value.trim()
  if (!keyword) return

  pubmedLoading.value = true
  pubmedError.value = ''
  pubmedPapers.value = []
  activePaperPmid.value = ''
  pubmedSearched.value = true

  try {
    const res = await searchPubMedAPI(keyword, 5)
    const papers = res.data?.papers || []
    pubmedPapers.value = papers
    activePaperPmid.value = papers[0]?.pmid || ''
  } catch (error) {
    // 优先取服务端返回的 msg，其次 HTTP 状态码，最后降级为通用提示
    const serverMsg = error.response?.data?.msg
    const httpStatus = error.response?.status
    pubmedError.value = serverMsg
      || (httpStatus ? `服务错误 ${httpStatus}，请稍后重试` : null)
      || error.message
      || '检索失败，请稍后重试'
    console.error('[PubMed] 检索请求失败:', error)
  } finally {
    pubmedLoading.value = false
  }
}

function handlePaperSelect(paper) {
  if (!paper?.pmid) return
  activePaperPmid.value = paper.pmid
  if (isMobileLayout.value) {
    activeMobilePane.value = 'preview'
  }
}

watch(
  categoryDocs,
  (docs) => {
    if (!docs.length) {
      selectedPdfId.value = null
      pdfPreviewState.value = createEmptyPdfPreview()
      return
    }

    const exists = docs.some((doc) => doc.id === selectedPdfId.value)
    if (!exists) {
      selectPdfDoc(docs[0], { switchPane: false })
    }
  },
  { immediate: true },
)

watch(activeView, (view) => {
  if (view === 'pdfs' && !pdfCategories.value.length && !pdfLoading.value) {
    loadPdfDocuments()
  }

  if (!isMobileLayout.value) return
  activeMobilePane.value = 'list'
}, { immediate: true })

onMounted(() => {
  updateLayoutMode()
  window.addEventListener('resize', updateLayoutMode)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateLayoutMode)
})
</script>

<template>
  <section class="learning-workspace">
    <div class="learning-layout" :class="{
      mobile: isMobileLayout,
      'mobile-show-preview': isMobileLayout && activeMobilePane === 'preview',
    }">
      <aside class="selection-pane">
        <template v-if="activeView === 'pdfs'">
          <div class="section-head compact pane-head">
            <div>
              <h3>文档选择</h3>
            </div>
            <span class="pane-count">{{ categoryDocs.length }} 篇</span>
          </div>

          <div v-if="pdfLoading" class="empty-card pane-state">正在从文档库加载 PDF 列表...</div>
          <div v-else-if="pdfError" class="empty-card error pane-state">{{ pdfError }}</div>

          <template v-else-if="pdfCategories.length">
            <div class="pdf-category-tabs">
              <button v-for="cat in pdfCategories" :key="cat" type="button" class="pdf-cat-tab"
                :class="{ active: activeCategory === cat }" @click="activeCategory = cat">{{ cat
                }}</button>
            </div>

            <div class="selection-list">
              <button v-for="doc in categoryDocs" :key="doc.id" type="button" class="selection-item"
                :class="{ active: selectedPdfId === doc.id }" @click="selectPdfDoc(doc, { switchPane: true })">
                <span class="selection-file-icon" aria-hidden="true">
                  <FileSVG :size="36" />
                  <span class="selection-file-ext">{{ getFileExtension(doc.name) }}</span>
                </span>
                <span class="selection-copy">
                  <strong>{{ doc.name }}</strong>
                  <small>{{ formatSize(doc.size) }}</small>
                </span>
              </button>
            </div>
          </template>

          <div v-else class="empty-card pane-state">文档库暂无内容，请先完成 OSS 上传。</div>
        </template>

        <template v-else>
          <div class="section-head compact pane-head">
            <h3>文献列表</h3>

            <span v-if="pubmedPapers.length" class="pane-count">{{ pubmedPapers.length }} 篇</span>
          </div>

          <form class="toolbar pubmed-toolbar" @submit.prevent="handlePubMedSearch">
            <input v-model="pubmedQuery" type="text" placeholder="例如：acute ischemic stroke thrombolysis" />
            <button type="submit" class="secondary-action" :disabled="pubmedLoading">
              {{ pubmedLoading ? '检索中...' : '检索' }}
            </button>
          </form>

          <div v-if="pubmedError" class="empty-card error pane-state">{{ pubmedError }}</div>
          <PapersSidebar v-else :papers="pubmedPapers" :loading="pubmedLoading" :active-paper-pmid="activePaperPmid"
            :searched="pubmedSearched" @select="handlePaperSelect" />
        </template>
      </aside>

      <section class="preview-pane">
        <header class="section-head compact preview-head" :class="{ 'preview-head--pdf': activeView === 'pdfs' }">
          <div class="preview-head-main">
            <button v-if="isMobileLayout && activeMobilePane === 'preview'" type="button" class="back-link"
              @click="activeMobilePane = 'list'">返回列表</button>

            <template v-if="activeView === 'pdfs'">
              <div>
                <h3>{{ currentPdfDoc?.name || '文档预览' }}</h3>
              </div>

              <div class="preview-actions preview-actions--below-title">
                <span v-if="currentPdfDoc" class="preview-meta">{{ activeCategory || '未分类' }}</span>
                <a v-if="pdfPreviewState.downloadUrl" class="preview-text-link" :href="pdfPreviewState.downloadUrl"
                  target="_blank" rel="noopener noreferrer">
                  下载原文
                </a>
              </div>
            </template>

            <template v-else>
              <div>
                <h3>{{ currentPaper?.journal || '详情' }}</h3>
              </div>
            </template>
          </div>

          <div v-if="activeView !== 'pdfs' && currentPaper?.url" class="preview-actions">
            <a class="secondary-action external-link" :href="currentPaper.url" target="_blank"
              rel="noopener noreferrer">
              打开 PubMed
            </a>
          </div>
        </header>

        <div v-if="activeView === 'pdfs'" class="preview-body pdf-preview-body">
          <div v-if="pdfPreviewState.error" class="empty-card error pane-state">{{ pdfPreviewState.error }}
          </div>

          <template v-else-if="pdfPreviewState.url">
            <div class="pdf-canvas-shell">
              <div v-if="pdfPreviewState.loading" class="inline-pdf-loading">正在加载 PDF...</div>
              <VuePdfEmbed class="pdf-canvas" :key="pdfPreviewState.url" :source="pdfPreviewState.url"
                :page="pdfPreviewState.currentPage" @loaded="handlePdfLoaded" />

              <div class="pdf-floating-toolbar" aria-label="PDF 翻页操作">
                <div class="pdf-page-controls">
                  <button type="button" class="pdf-float-button icon-action"
                    :disabled="pdfPreviewState.currentPage <= 1" @click="goPdfPage(-1)">
                    <UpSVG color="currentColor" />
                  </button>
                  <span class="page-indicator">
                    {{ pdfPreviewState.totalPages ? `第 ${pdfPreviewState.currentPage} /
                    ${pdfPreviewState.totalPages} 页` : '加载中...' }}
                  </span>
                  <button type="button" class="pdf-float-button icon-action"
                    :disabled="pdfPreviewState.currentPage >= pdfPreviewState.totalPages" @click="goPdfPage(1)">
                    <DownSVG color="currentColor" />
                  </button>
                </div>
              </div>
            </div>
          </template>

          <div v-else class="empty-card pane-state">从左侧选择文档后，在这里预览内容。</div>
        </div>

        <div v-else class="preview-body paper-preview-body">
          <article v-if="currentPaper" class="paper-detail-card">
            <div class="paper-detail-topline">{{ shortText(currentPaper.journal, 'PubMed') }}</div>
            <h2 class="paper-detail-title">{{ shortText(currentPaper.title) }}</h2>

            <p class="paper-detail-meta">
              {{ [currentPaper.authors, currentPaper.pub_date].filter(Boolean).join(' · ') || '暂无发表信息' }}
            </p>

            <div v-if="displayTypes(currentPaper.pub_type).length" class="paper-detail-types">
              <span v-for="type in displayTypes(currentPaper.pub_type)" :key="type" :class="pillClass(type)">{{ type
              }}</span>
            </div>

            <section class="paper-detail-section">
              <h4>摘要</h4>
              <p>{{ shortText(currentPaper.abstract, '当前文献未返回摘要。') }}</p>
            </section>

            <section class="paper-detail-section">
              <h4>来源</h4>
              <p>{{ shortText(currentPaper.url, '当前文献暂无外部链接。') }}</p>
            </section>
          </article>

          <div v-else-if="pubmedLoading" class="empty-card pane-state">PubMed 检索中，请稍候...</div>
          <div v-else-if="pubmedSearched" class="empty-card pane-state">暂无可预览文献，请尝试调整关键词。</div>
          <div v-else class="empty-card pane-state">输入关键词后点击检索，将从 PubMed 返回最相关的 5 篇文献。</div>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped lang="scss">
.learning-workspace {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--color-bg-base);
}

.learning-layout {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.selection-pane,
.preview-pane {
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.selection-pane {
  border-right: 1px solid var(--color-border);
  background: var(--color-bg-light);
}

.preview-pane {
  background: var(--color-bg-base);
}

.preview-head-main {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.preview-head--pdf {
  align-items: flex-start;
}

.pane-count,
.preview-meta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 58px;
  padding: 5px 10px;
  border-radius: var(--radius-pill);
  background: var(--color-secondary-bg);
  color: var(--color-text-medium);
  font-size: 12px;
  font-weight: 700;
}

.pdf-category-tabs {
  display: flex;
  gap: 6px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}

.pdf-cat-tab {
  padding: 5px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--color-border);
  background: var(--color-bg-base);
  color: var(--color-text-medium);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition-fast);

  &:hover {
    background: var(--color-hover-bg);
  }

  &.active {
    background: var(--color-primary);
    color: #fff;
    border-color: var(--color-primary);
  }
}

.selection-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.selection-item {
  width: 100%;
  border: none;
  background: transparent;
  text-align: left;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid var(--color-border-item);
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);

  &:hover {
    background: var(--color-hover-bg);
  }

  &.active {
    background: var(--color-active-bg);
    box-shadow: inset 3px 0 0 var(--color-active-border);
  }
}

.selection-file-icon {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  color: var(--color-primary);
  opacity: 0.5;
  flex-shrink: 0;
  transition: color var(--transition-fast), transform var(--transition-fast);
}

.selection-item:hover .selection-file-icon,
.selection-item.active .selection-file-icon {
  opacity: 1;
}


.selection-file-ext {
  position: absolute;
  left: 50%;
  bottom: 12px;
  transform: translateX(-50%);
  max-width: 28px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 7px;
  line-height: 1;
  font-weight: 800;
  letter-spacing: 0.04em;
  color: currentColor;
  pointer-events: none;
}

.selection-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;

  strong,
  small {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    font-size: 14px;
    color: var(--color-text-strong);
  }

  small {
    font-size: 12px;
    color: var(--color-text-medium);
  }
}

.preview-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.pdf-preview-body {
  display: flex;
  flex-direction: column;
}

.pdf-page-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-indicator {
  text-align: center;
  font-size: 14px;
  color: var(--color-text-strong);
}

.pdf-canvas-shell {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--color-pdf-surface);
  padding: 18px 18px 18px;
}

.pdf-canvas {
  display: flex;
  justify-content: center;

  :deep(.vue-pdf-embed__page) {
    margin: 0 auto;
    background: var(--color-pdf-frame);
    box-shadow: var(--color-pdf-page-shadow);
  }

  :deep(canvas) {
    display: block;
    max-width: 100%;
    height: auto;
    filter: var(--filter-pdf-page);
    transition: filter var(--transition-normal);
  }
}

.inline-pdf-loading {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: var(--color-text-medium);
  font-size: 14px;
}

.pdf-floating-toolbar {
  position: sticky;
  right: 18px;
  bottom: 18px;
  margin-left: auto;
  width: fit-content;
  max-width: calc(100% - 24px);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 4px 8px;
  border: 1px solid color-mix(in srgb, var(--color-border) 72%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-bg-base) 50%, transparent);
  box-shadow: 0 18px 34px rgba(15, 23, 42, 0.16);
  backdrop-filter: blur(16px);
  z-index: 2;
  gap: 4px;
}

.icon-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: 50%;
}

.pdf-float-button {
  border: none;
  background: transparent;
  color: var(--color-text-strong);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), transform var(--transition-fast);

  &:hover:not(:disabled) {
    background: color-mix(in srgb, var(--color-bg-base) 32%, transparent);
  }

  &:disabled {
    opacity: 0.38;
    cursor: not-allowed;
  }
}

.paper-preview-body {
  overflow-y: auto;
  padding: 18px;
}

.paper-detail-card {
  max-width: 860px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.paper-detail-topline {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-primary-dark);
}

.paper-detail-title {
  margin: 0;
  font-size: 24px;
  line-height: 1.35;
  color: var(--color-text-strong);
}

.paper-detail-meta {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--color-text-medium);
}

.paper-detail-types {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.paper-detail-section {
  padding: 16px 18px;
  border: 1px solid var(--color-border-item);
  border-radius: var(--radius-lg);
  background: var(--color-bg-light);

  h4 {
    margin: 0 0 8px;
    font-size: 14px;
    color: var(--color-text-strong);
  }

  p {
    margin: 0;
    font-size: 14px;
    line-height: 1.7;
    color: var(--color-text-medium);
    white-space: pre-wrap;
    word-break: break-word;
  }
}

.pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.5;
}

.pill--high {
  background: rgba(220, 38, 38, 0.1);
  color: #b91c1c;
}

.pill--mid {
  background: rgba(180, 83, 9, 0.1);
  color: var(--color-orange);
}

.pill--low {
  background: var(--color-badge-status-bg);
  color: var(--color-badge-status-color);
}

.secondary-action.small {
  padding: 5px 10px;
  font-size: 12px;
}

.preview-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.preview-actions--below-title {
  width: 100%;
  justify-content: flex-start;
}

.preview-text-link {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  color: var(--color-primary);
  font-size: 14px;
  font-weight: 700;
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
  transition: color var(--transition-fast), opacity var(--transition-fast);

  &:hover {
    color: var(--color-primary);
  }

  &:active {
    opacity: 0.75;
  }
}

.external-link {
  text-decoration: none;
}

.back-link {
  align-self: flex-start;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--color-primary-dark);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.pane-state {
  margin: auto 0;
}

.pubmed-toolbar {
  background: var(--color-bg-light);
}

.empty-card.error {
  color: var(--color-red);
}

.section-head {
  align-items: center;
}

@media (max-width: 900px) {
  .learning-layout {
    grid-template-columns: 1fr;
  }

  .selection-pane,
  .preview-pane {
    min-width: 0;
    border-right: none;
  }

  .learning-layout.mobile .preview-pane {
    display: none;
  }

  .learning-layout.mobile.mobile-show-preview .selection-pane {
    display: none;
  }

  .learning-layout.mobile.mobile-show-preview .preview-pane {
    display: flex;
  }

  .paper-preview-body {
    padding: 14px;
  }

  .paper-detail-title {
    font-size: 20px;
  }

  .pdf-floating-toolbar {
    right: 14px;
    bottom: 14px;
    padding: 8px 10px;
  }

  .page-indicator {
    min-width: 104px;
    font-size: 12px;
  }
}

@media (max-width: 640px) {
  .view-tabs {
    padding: 8px 10px 0;
  }

  .view-tab {
    flex: 1;
    padding: 9px 12px;
  }

  .pdf-category-tabs,
  .paper-preview-body {
    padding-left: 12px;
    padding-right: 12px;
  }

  .selection-item {
    padding: 12px;
  }

  .selection-icon {
    min-width: 40px;
    height: 40px;
  }

  .page-indicator {
    min-width: 88px;
    font-size: 12px;
  }

  .pdf-canvas-shell {
    padding: 12px 12px 88px;
  }

  .pdf-floating-toolbar {
    right: 12px;
    bottom: 12px;
    padding: 7px 8px;
  }

  .preview-meta,
  .page-indicator {
    min-width: auto;
  }

  .pdf-page-controls {
    gap: 6px;
  }

  .icon-action {
    width: 34px;
    height: 34px;
  }

  .preview-actions {
    justify-content: flex-end;
  }

  .preview-actions--below-title {
    justify-content: flex-start;
  }

  .preview-text-link {
    min-height: 32px;
  }
}
</style>

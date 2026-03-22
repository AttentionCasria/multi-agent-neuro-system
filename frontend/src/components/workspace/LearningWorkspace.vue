<script setup>
import { ref, computed, onMounted } from 'vue'
import PdfPreviewModal from '@/components/PdfPreviewModal.vue'
import { getDocumentsAPI, getDocumentUrlAPI } from '@/api/documents'

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

const query = defineModel('query', { required: true })

const emit = defineEmits(['search', 'select-material', 'page-change', 'open-material-link'])

function shortText(value, fallback = '暂无内容') {
  const text = String(value || '').trim()
  return text || fallback
}

// ── 顶部视图切换：学习资料 | PDF文档库 ────────────────────────────────
const activeView = ref('materials')   // 'materials' | 'pdfs'

// ── PDF 文档库状态（自管理，不走父组件 props） ─────────────────────────
const pdfLoading = ref(false)
const pdfError = ref('')
// 结构：{ 指南: [DocumentVO], 教材: [...], ... }
const pdfDocuments = ref({})
const pdfCategories = computed(() => Object.keys(pdfDocuments.value))
const activeCategory = ref('')

const categoryDocs = computed(() =>
  activeCategory.value ? (pdfDocuments.value[activeCategory.value] || []) : []
)

// PDF 预览弹窗状态
const pdfPreview = ref({
  visible: false,
  url: '',
  downloadUrl: '',
  fileName: '',
  loading: false,
})

async function loadPdfDocuments() {
  pdfLoading.value = true
  pdfError.value = ''
  try {
    const res = await getDocumentsAPI()
    pdfDocuments.value = res.data || {}
    // 默认选中第一个分类
    const categories = Object.keys(pdfDocuments.value)
    if (categories.length) activeCategory.value = categories[0]
  } catch (e) {
    pdfError.value = e?.msg || '网络错误，请稍后重试'
  } finally {
    pdfLoading.value = false
  }
}

async function openPreview(doc) {
  pdfPreview.value = { visible: true, url: '', downloadUrl: '', fileName: doc.name, loading: true }
  try {
    const res = await getDocumentUrlAPI(doc.id)
    pdfPreview.value.url = res.data.previewUrl
    pdfPreview.value.downloadUrl = res.data.downloadUrl
  } catch (e) {
    alert(e?.msg ? '获取预览链接失败：' + e.msg : '网络错误，无法获取预览链接')
    pdfPreview.value.visible = false
  } finally {
    pdfPreview.value.loading = false
  }
}

async function downloadDoc(doc) {
  try {
    const res = await getDocumentUrlAPI(doc.id)
    window.open(res.data.downloadUrl, '_blank')
  } catch (e) {
    alert(e?.msg ? '获取下载链接失败：' + e.msg : '网络错误，无法获取下载链接')
  }
}

// 切换到 PDF 文档库时懒加载
function switchView(view) {
  activeView.value = view
  if (view === 'pdfs' && !pdfCategories.value.length && !pdfLoading.value) {
    loadPdfDocuments()
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}
</script>

<template>
  <section class="learning-workspace">
    <!-- ── 视图切换 Tab ─────────────────────────────────── -->
    <div class="view-tabs">
      <button
        type="button"
        class="view-tab"
        :class="{ active: activeView === 'materials' }"
        @click="switchView('materials')"
      >学习资料</button>
      <button
        type="button"
        class="view-tab"
        :class="{ active: activeView === 'pdfs' }"
        @click="switchView('pdfs')"
      >PDF 文档库</button>
    </div>

    <!-- ══════════════════════════════════════════════════════ -->
    <!--  视图 A：学习资料（原有逻辑，保持不变）               -->
    <!-- ══════════════════════════════════════════════════════ -->
    <template v-if="activeView === 'materials'">
      <div class="material-list-card">
        <div class="section-head">
          <div>
            <h3>学习资料列表</h3>
            <p>按分类筛选医生学习资料，并查看详情。</p>
          </div>
        </div>

        <form class="toolbar" @submit.prevent="emit('search')">
          <input v-model="query.category" type="text" placeholder="例如：心血管疾病" />
          <button type="submit" class="secondary-action">查询资料</button>
        </form>

        <div v-if="materialsLoading" class="empty-card">正在加载学习资料...</div>

        <div v-else-if="materials.length" class="material-list">
          <article v-for="material in materials" :key="material.id" class="material-item"
            :class="{ active: material.id === selectedMaterialId }" @click="emit('select-material', material.id)">
            <div class="material-head">
              <h4>{{ material.title }}</h4>
              <span class="type-badge">{{ material.type || '资料' }}</span>
            </div>
            <p>{{ shortText(material.url, '点击查看详情') }}</p>
          </article>
        </div>

        <div v-else class="empty-card">暂无学习资料，请调整分类关键词后重试。</div>

        <div class="pager">
          <button type="button" class="secondary-action" :disabled="query.page <= 1"
            @click="emit('page-change', -1)">上一页</button>
          <span>第 {{ query.page }} / {{ materialPageCount }} 页，共 {{ learningTotal }} 条</span>
          <button type="button" class="secondary-action" :disabled="query.page >= materialPageCount"
            @click="emit('page-change', 1)">
            下一页
          </button>
        </div>
      </div>

      <div class="material-detail-card">
        <div class="section-head">
          <div>
            <h3>资料详情</h3>
            <p>支持查看正文或打开外部资源链接。</p>
          </div>
        </div>

        <div v-if="materialDetailLoading" class="empty-card">正在加载资料详情...</div>

        <div v-else-if="materialDetail" class="detail-card accent">
          <div class="detail-title-row">
            <div>
              <p class="summary-label">资料标题</p>
              <h4>{{ materialDetail.title }}</h4>
            </div>
            <button v-if="materialDetail.url" type="button" class="secondary-action"
              @click="emit('open-material-link', materialDetail.url)">
              打开原文
            </button>
          </div>

          <div class="material-content">
            <p>{{ shortText(materialDetail.content, '该资料未返回正文，可通过原文链接查看。') }}</p>
          </div>
        </div>

        <div v-else class="empty-card">从左侧选择一份资料后，这里会显示详情。</div>
      </div>
    </template>

    <!-- ══════════════════════════════════════════════════════ -->
    <!--  视图 B：PDF 文档库                                   -->
    <!-- ══════════════════════════════════════════════════════ -->
    <template v-else>
      <div class="pdf-panel">
        <!-- 加载 / 错误状态 -->
        <div v-if="pdfLoading" class="empty-card">正在从文档库加载 PDF 列表...</div>
        <div v-else-if="pdfError" class="empty-card error">{{ pdfError }}</div>

        <template v-else-if="pdfCategories.length">
          <!-- 分类 Tab -->
          <div class="pdf-category-tabs">
            <button
              v-for="cat in pdfCategories"
              :key="cat"
              type="button"
              class="pdf-cat-tab"
              :class="{ active: activeCategory === cat }"
              @click="activeCategory = cat"
            >{{ cat }}</button>
          </div>

          <!-- 文档列表 -->
          <div class="pdf-list">
            <div v-if="!categoryDocs.length" class="empty-card">该分类暂无文档。</div>
            <article v-for="doc in categoryDocs" :key="doc.id" class="pdf-item">
              <div class="pdf-item-info">
                <span class="pdf-icon">📄</span>
                <div>
                  <p class="pdf-name">{{ doc.name }}</p>
                  <small class="pdf-size">{{ formatSize(doc.size) }}</small>
                </div>
              </div>
              <div class="pdf-item-actions">
                <button type="button" class="secondary-action small" @click="openPreview(doc)">在线预览</button>
                <button type="button" class="secondary-action small" @click="downloadDoc(doc)">下载</button>
              </div>
            </article>
          </div>
        </template>

        <div v-else class="empty-card">文档库暂无内容，请先完成 OSS 上传。</div>
      </div>
    </template>

    <!-- PDF 预览弹窗（全局复用） -->
    <PdfPreviewModal
      :visible="pdfPreview.visible"
      :url="pdfPreview.url"
      :file-name="pdfPreview.fileName"
      :download-url="pdfPreview.downloadUrl"
      @close="pdfPreview.visible = false"
    />
  </section>
</template>

<style scoped lang="scss">
// ── 顶部 Tab ────────────────────────────────────────────────
.view-tabs {
  grid-column: 1 / -1;   // 跨越两列，占满宽度
  display: flex;
  gap: 4px;
  padding: 10px 14px 0;
  background: var(--color-bg-light);
  border-bottom: 1px solid var(--color-border);
}

.view-tab {
  padding: 7px 18px;
  border-radius: 6px 6px 0 0;
  border: none;
  background: transparent;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-medium);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;

  &:hover { background: var(--color-bg-base); }

  &.active {
    background: var(--color-bg-base);
    color: var(--color-primary);
    box-shadow: 0 -2px 0 var(--color-primary) inset;
  }
}

// ── 整体布局 ────────────────────────────────────────────────
.learning-workspace {
  display: grid;
  grid-template-columns: minmax(300px, 380px) minmax(0, 1fr);
  grid-template-rows: auto 1fr;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

/* ───────────────── Panels ───────────────── */
.material-list-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--color-border);
  background: var(--color-bg-light);
  overflow: hidden;
}

.material-detail-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--color-bg-base);
  overflow-y: auto;
}

// ── PDF 文档库面板（占满两列） ───────────────────────────────
.pdf-panel {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  background: var(--color-bg-base);
}

.pdf-category-tabs {
  display: flex;
  gap: 4px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.pdf-cat-tab {
  padding: 5px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--color-border);
  background: var(--color-bg-light);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;

  &:hover { background: var(--color-patient-select-hover); }

  &.active {
    background: var(--color-primary);
    color: #fff;
    border-color: var(--color-primary);
  }
}

.pdf-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.pdf-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--color-border-item);
  gap: 12px;

  &:hover { background: var(--color-patient-select-hover); }
}

.pdf-item-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.pdf-icon { font-size: 20px; flex-shrink: 0; }

.pdf-name {
  margin: 0 0 2px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pdf-size {
  font-size: 12px;
  color: var(--color-text-medium);
}

.pdf-item-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* ───────────────── Material head ───────────────── */
.material-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 4px;
}

/* ───────────────── Material list ───────────────── */
.material-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.material-item {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-item);
  cursor: pointer;
  transition: background var(--transition-fast);
  flex-shrink: 0;

  &:hover { background: var(--color-patient-select-hover); }

  &.active {
    background: var(--color-patient-select-active);
    border-left: 3px solid var(--color-active-border);
    padding-left: 11px;
  }

  h4 {
    margin: 0 0 3px;
    font-size: 14px;
    font-weight: 700;
    color: var(--color-text-strong);
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

.type-badge {
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 700;
  background: var(--color-badge-accent-bg);
  color: var(--color-orange);
  white-space: nowrap;
}

/* ───────────────── Material detail ───────────────── */
.detail-card.accent {
  background: var(--color-detail-accent-bg);
  border-top: 3px solid var(--color-primary);
  border-left: none;
}

.detail-title-row h4 { font-size: 16px; }

.material-content {
  padding: 12px 14px;
  border-left: 2px solid var(--color-border);
  background: var(--color-bg-light);

  p {
    margin: 0;
    color: var(--color-text-medium);
    font-size: 14px;
    line-height: 1.6;
  }
}

/* ───────────────── Buttons ───────────────── */
.secondary-action.small {
  padding: 4px 10px;
  font-size: 12px;
}

/* ───────────────── Error state ───────────────── */
.empty-card.error { color: #dc2626; }

@media (max-width: 1080px) {
  .learning-workspace {
    grid-template-columns: 1fr;
    height: auto;
    overflow: visible;
  }

  .material-list-card {
    border-right: none;
    border-bottom: 1px solid var(--color-border);
    max-height: 340px;
    overflow: hidden;
  }
}

@media (max-width: 640px) {
  .section-head,
  .toolbar,
  .pager,
  .material-head,
  .detail-title-row {
    flex-wrap: wrap;
  }

  .pdf-item {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>

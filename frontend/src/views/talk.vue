<script setup>
import { onMounted, ref, nextTick } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import UserDialog from '@/components/UserDialog.vue'
import { useUserStore } from '@/stores/user'
import { deleteChatAPI, getChatHistoryAPI, getChatTitlesAPI, newChatStreamAPI, sendQuestionStreamAPI } from '@/api/talk'
import LoadingModel from '@/components/LoadingModel.vue'
// 假设 ArrowSVG 是全局组件或已注册，如果不是请取消下面注释并导入
// import ArrowSVG from '@/components/ArrowSVG.vue'

defineOptions({ name: 'TalkIndex' })

const message = ref('')
const isDialogShow = ref(false)
const userStore = useUserStore()
const talkTitleList = ref([])
const inputRef = ref(null)
const chatContainerRef = ref(null) // 用于滚动到底部

const currentTalkId = ref(0)
const currentTalkList = ref([])

const canSendMessage = ref(true)
const loading = ref(false)

marked.setOptions({
  gfm: true,
  breaks: true,
})

const renderMarkdown = (raw = '') => {
  if (!raw) return ''
  return DOMPurify.sanitize(
    marked.parse(String(raw), {
      breaks: true,
      gfm: true
    })
  )
}

onMounted(async () => {
  await fetchTalkTitle()
  if (talkTitleList.value.length > 0) {
    // 过滤掉可能存在的残留占位符
    const validTalk = talkTitleList.value.find(t => t.talkId !== 0)
    if (validTalk) {
      currentTalkId.value = validTalk.talkId
      fetchTalkHistory(currentTalkId.value)
    }
  }
})

async function fetchTalkTitle() {
  try {
    const res = await getChatTitlesAPI()
    if (res.data && res.data.length > 0) {
      talkTitleList.value = res.data
    }
  } catch (e) {
    console.error('获取标题失败', e)
  }
}

function handleClickTalkTitle(talkId) {
  if (talkId === currentTalkId.value) return
  currentTalkId.value = talkId
  fetchTalkHistory(talkId)
}

async function fetchTalkHistory(talkId = currentTalkId.value) {
  try {
    const res = await getChatHistoryAPI(talkId)
    // 确保是数组
    currentTalkList.value = Array.isArray(res.data) ? res.data : []
    nextTick(() => scrollToBottom())
  } catch (e) {
    console.error('获取历史失败', e)
  }
}

function handleNewChat() {
  currentTalkId.value = 0
  currentTalkList.value = []

  // 清理可能存在的旧占位
  talkTitleList.value = talkTitleList.value.filter(t => t.talkId !== 0)
  talkTitleList.value.unshift({ talkId: 0, title: '新对话' })

  if (inputRef.value) inputRef.value.focus()
}

// 发送消息核心逻辑修复
const isStreaming = ref(false)


async function sendMessage() {
  const text = message.value.trim()
  if (!text || isStreaming.value) return

  message.value = ''
  isStreaming.value = true
  loading.value = true

  // 1️⃣ 用户消息上屏
  currentTalkList.value.push(text)

  // 2️⃣ AI 占位
  currentTalkList.value.push('')
  const aiIndex = currentTalkList.value.length - 1

  nextTick(scrollToBottom)

  try {
    let finalResult = null

    if (currentTalkId.value === 0) {
      finalResult = await newChatStreamAPI(
        { question: text },
        (chunk) => {
          currentTalkList.value[aiIndex] += chunk
          nextTick(scrollToBottom)
        }
      )
    } else {
      finalResult = await sendQuestionStreamAPI(
        {
          talkId: currentTalkId.value,
          question: text,
        },
        (chunk) => {
          currentTalkList.value[aiIndex] += chunk
          nextTick(scrollToBottom)
        }
      )
    }

    const { talkId, title, content } = finalResult.data || {}

    if (typeof content === 'string') {
      currentTalkList.value[aiIndex] = content
    }

    // ✅ 新对话真正生成 ID 后再更新
    if (currentTalkId.value === 0 && talkId) {
      currentTalkId.value = talkId

      const index = talkTitleList.value.findIndex(t => t.talkId === 0)

      if (index !== -1) {
        talkTitleList.value[index] = { talkId, title }
      } else {
        talkTitleList.value.unshift({ talkId, title })
      }
    } else if (talkId) {
      const index = talkTitleList.value.findIndex(t => t.talkId === talkId)
      if (index !== -1 && title) {
        talkTitleList.value[index] = {
          ...talkTitleList.value[index],
          title,
        }
      }
    }

    await fetchTalkTitle()

  } catch (err) {
    console.error('发送失败', err)
    currentTalkList.value.splice(aiIndex, 1)
    currentTalkList.value.pop()
    alert(err?.message || '发送失败')
  } finally {
    isStreaming.value = false
    loading.value = false
    nextTick(scrollToBottom)
  }
}

async function handleDeleteChat(talkId) {
  if (!confirm('确定要删除此对话吗？此操作不可撤销！')) return
  try {
    await deleteChatAPI(talkId)
    talkTitleList.value = talkTitleList.value.filter(t => t.talkId !== talkId)
    if (currentTalkId.value === talkId) {
      handleNewChat()
    }
  } catch (err) {
    console.error('删除失败', err)
    alert('删除失败')
  }
}

async function handleDeleteAll() {
  if (!confirm('确定要删除所有对话吗？此操作不可撤销！')) return
  if (!talkTitleList.value || talkTitleList.value.length === 0) return

  loading.value = true
  try {
    // 并行删除以提高速度，或按需串行
    const deletePromises = talkTitleList.value
      .filter(t => t.talkId !== 0)
      .map(t => deleteChatAPI(t.talkId))

    await Promise.all(deletePromises)

    // 清空前端状态
    talkTitleList.value = []
    currentTalkList.value = []
    currentTalkId.value = 0

    // 重新拉取确认
    await fetchTalkTitle()
    handleNewChat() // 重置为新对话状态
  } catch (err) {
    console.error('删除所有失败', err)
    alert('删除失败，请重试')
  } finally {
    loading.value = false
  }
}

function handleUserClick() {
  isDialogShow.value = true
}

function handleCopy(text) {
  if (!text) return
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => alert('复制成功')).catch(() => fallbackCopy(text))
  } else {
    fallbackCopy(text)
  }
}

function fallbackCopy(text) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  alert('复制成功')
}

const autoResize = () => {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

// 新增：滚动到底部
const scrollToBottom = () => {
  const container = document.querySelector('.chat-messages')
  if (container) {
    container.scrollTop = container.scrollHeight
  }
}
</script>

<template>
  <LoadingModel v-model="loading" />
  <UserDialog :visible="isDialogShow" @close="isDialogShow = false"></UserDialog>

  <div class="container">
    <div class="chat-history">
      <div class="new-chat" @click="handleNewChat">开始新对话</div>
      <div class="delete-chat" @click="handleDeleteAll">删除所有对话</div>
      <h3>历史记录</h3>
      <div class="chat-list">
        <div
          v-for="talk in talkTitleList"
          :key="talk.talkId"
          class="chat-item"
          :class="{ active: talk.talkId === currentTalkId }"
          @click="handleClickTalkTitle(talk.talkId)">
          <span class="title">{{ talk.title }}</span>
          <button class="delete-btn" @click.stop="handleDeleteChat(talk.talkId)">删除</button>
        </div>
      </div>
    </div>

    <div class="chat-panel">
      <header class="chat-header">
        <span class="title">Synapse MD</span>
        <div class="user" @click="handleUserClick">
          <img :src="userStore.image" alt="avatar" />
          <p class="username">{{ userStore.name }}</p>
        </div>
      </header>

      <!-- 对话展示区：添加 ref 以便滚动 -->
      <main class="chat-messages" ref="chatContainerRef">
        <div class="chat-content" v-if="currentTalkList.length > 0">
          <div
            v-for="(msg, index) in currentTalkList"
            :key="index + msg"
            class="message-wrapper"
            :class="{ user: index % 2 === 0 }">

            <div
              class="message"
              :class="{ user: index % 2 === 0 }">

              <template v-if="index % 2 === 0">
                {{ msg }}
              </template>
              <div v-else class="markdown-body" v-html="renderMarkdown(msg)"></div>
            </div>

            <button class="copy-btn" @click="handleCopy(msg)">复制</button>
          </div>
        </div>
        <div v-else class="empty">我可以帮助您什么？</div>
      </main>

      <div class="input-box">
        <textarea ref="inputRef" rows="1" placeholder="请输入您的问题" v-model="message" @input="autoResize"
          @keydown.enter.exact.prevent="sendMessage" />
        <button class="send-btn" :disabled="message.trim() === '' || !canSendMessage" @click="sendMessage">
          <ArrowSVG color="#fff" size="24" />
        </button>
      </div>
    </div>
  </div>
</template>



<style scoped lang="scss">
* {
  color: #333;
}

.container {
  width: 100vw;
  height: 100vh;

  display: flex;
  background-color: #f7f9fc;

  .chat-history {
    width: 260px;
    background-color: #fff;
    padding: 10px;
    color: #333;
    border-right: 1px solid #e5e7eb;

    .new-chat,
    .delete-chat {
      margin: 15px auto;
      text-align: center;
      padding: 10px;
      transition: all 0.15s ease;
      cursor: pointer;
      font-size: 14px;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
    }

    .new-chat {
      background-color: #07bf9b;
      color: #fff;
      border: none;
    }

    .new-chat:hover {
      background-color: #05a583;
    }

    .delete-chat {
      color: #ff4d4f;
      background-color: #fff;
    }

    .delete-chat:hover {
      background-color: #fff1f0;
      border-color: #ffa39e;
    }

    h3 {
      font-size: 14px;
      margin: 20px 10px 10px;
      color: #666;
    }

    .chat-list {
      max-height: calc(100vh - 200px);
      overflow-y: auto;

      .chat-item {
        display: flex;
        align-items: center; // 垂直居中
        justify-content: space-between;

        padding: 10px 12px;
        border-radius: 8px;
        cursor: pointer;
        font-size: 14px;
        color: #4b5563;
        transition: all 0.15s ease;
        margin-bottom: 8px;

        .title {
          flex: 1; // 占满剩余空间
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .delete-btn {
          margin-left: 8px; // 和标题拉开一点距离
          padding: 2px 6px;
          font-size: 12px;
          color: #ff4d4f;
          background-color: #fff;
          border: 1px solid #ff4d4f;
          border-radius: 4px;
          cursor: pointer;
          transition: all 0.15s ease;

          // 防止按钮点击触发父级点击（如果有）
          flex-shrink: 0;
        }

        &:hover {
          background-color: #f3f4f6;
          color: #111827;
        }

        &.active {
          background-color: #eff6ff;
          color: #3b82f6;
          font-weight: 500;
        }
      }
    }
  }

  .chat-panel {
    flex: 1;
    background-color: #f7f9fc;
    display: flex;
    flex-direction: column;

    .chat-header {
      height: 60px;
      padding: 0 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background-color: #fff;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
      z-index: 10;

      .title {
        font-size: 18px;
        font-weight: 600;
        color: #3b82f6;
      }

      .user {
        display: flex;
        align-items: center;
        gap: 10px;
        cursor: pointer;
        padding: 4px 8px;
        border-radius: 20px;
        transition: background-color 0.2s;

        &:hover {
          background-color: #f3f4f6;
        }

        img {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          border: 2px solid #eff6ff;
        }

        .username {
          font-weight: 500;
          font-size: 14px;
          color: #4b5563;
        }
      }
    }

    .chat-messages {
      flex: 1;
      display: flex;
      justify-content: center;
      overflow-y: auto;
      padding: 20px 0;

      .chat-content {
        width: 80%;
        max-width: 900px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        padding-bottom: 40px;

        scrollbar-width: thin;
        scrollbar-color: #e5e7eb transparent;

        &::-webkit-scrollbar {
          width: 6px;
        }

        &::-webkit-scrollbar-thumb {
          background-color: #e5e7eb;
          border-radius: 10px;
        }

        .message {
          padding: 12px 20px;
          align-self: flex-start;
          border-radius: 12px;
          background-color: #fff;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
          border: 1px solid #e5e7eb;
          line-height: 1.6;
          display: inline-block;
          width: auto;
          max-width: 85%;
          word-break: break-word;
          overflow-wrap: anywhere;
          color: #374151;

          .markdown-body {
            color: #374151;
            font-size: 15px;
            line-height: 1.6;
            white-space: pre-wrap;
          }

          :deep(.markdown-body pre) {
            background-color: #f8fafc;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            overflow-x: auto;
          }

          :deep(.markdown-body code) {
            font-family: 'Fira Code', 'Consolas', monospace;
            background-color: #f1f5f9;
            color: #ef4444;
            padding: 2px 4px;
            border-radius: 4px;
          }

          &.user {
            background-color: #3b82f6;
            border-radius: 12px 12px 0 12px;
            align-self: flex-end;
            display: inline-block;
            width: auto;
            max-width: 85%;
            color: #fff;
            border: none;
            box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.2);

            * {
              color: #fff;
            }
          }
        }

        .message-wrapper {
          display: flex;
          flex-direction: column;
          position: relative;

          &.user {
            align-items: flex-end;
          }

          &:hover .copy-btn {
            opacity: 1;
          }
        }

        .copy-btn {
          margin-top: 4px;
          font-size: 12px;
          background: transparent;
          border: none;
          color: #9ca3af;
          cursor: pointer;
          opacity: 0;
          transition: opacity 0.2s ease;

          &:hover {
            color: #3b82f6;
          }
        }
      }

      .empty {
        display: flex;
        justify-content: center;
        align-items: center;
        font-size: 32px;
        font-weight: 600;
        text-shadow: 0 1px 0 #fff;
      }
    }

    .input-box {
      width: 80%;
      max-width: 800px;
      margin: 0 auto 30px auto;
      display: flex;
      align-items: flex-end;
      /* 改为 flex-end，防止输入框变高时按钮悬浮在中间 */
      padding: 8px 16px;
      border-radius: 16px;
      background-color: #fff;
      box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
      border: 1px solid #e5e7eb;
      box-sizing: border-box;
      transition: all 0.2s ease;

      &:focus-within {
        border-color: #3b82f6;
        box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1);
      }

      /* 4. 重置 textarea 样式 */
      textarea {
        flex: 1;
        min-height: 44px;
        /* 对应原 input 的高度 */
        max-height: 200px;
        /* 限制最大高度，超出后出现滚动条 */
        padding: 12px 12px;
        /* 调整内边距以匹配视觉 */
        border: none;
        outline: none;
        background-color: transparent;
        font-size: 1rem;
        line-height: 1.5;
        /* 行高影响高度计算 */
        color: #1f2937;
        resize: none;
        /* 禁止手动拖拽调整大小 */
        overflow-y: auto;
        /* 超出最大高度显示滚动条 */
        font-family: inherit;
        /* 继承字体 */
        box-sizing: border-box;

        &::placeholder {
          color: #9ca3af;
        }

        /* 隐藏滚动条但保留功能 (可选，为了美观) */
        &::-webkit-scrollbar {
          width: 4px;
        }

        &::-webkit-scrollbar-thumb {
          background-color: #e5e7eb;
          border-radius: 4px;
        }
      }

      .send-btn {
        width: 36px;
        height: 36px;
        margin-left: 12px;
        /* 调整 margin-bottom 以对齐底部，因为父级改为了 flex-end */
        margin-bottom: 4px;
        border-radius: 10px;
        border: none;
        background-color: #3b82f6;
        color: #fff;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: all 0.2s ease;

        &:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.3);
        }

        &:active:not(:disabled) {
          transform: translateY(0);
        }

        &:disabled {
          background-color: #f3f4f6;
          cursor: not-allowed;

          :deep(svg) {
            color: #d1d5db !important;
          }
        }
      }
    }
  }
}
</style>

import { useUserStore } from '@/stores/user'
import request from '@/utils/request'

function normalizeTalkId(value) {
  if (value === null || value === undefined) return null

  const talkId = String(value).trim()
  return talkId || null
}

// 1. 获取历史对话标题
export const getChatTitlesAPI = () => request.get('/user/title')

// 2. 查询历史对话内容
// talkId: String
export const getChatHistoryAPI = (talkId) => request.get(`/user/ques/getQues/${talkId}`)

// 3. 继续对话（发送问题）
// params = { talkId: String, question: String }
export const sendQuestionAPI = (params) => request.post('/user/ques/getQues', params)

// 4. 新建对话
// params = { question: String }
export const newChatAPI = (params) => request.post('/user/ques/newGetQues', params)

const MAX_RETRIES = 3

/**
 * 核心流式请求函数
 * @param {Object} params        - 请求体 { talkId?, question }
 * @param {Function} onChunk     - 收到答案片段时回调 (text: string) => void
 * @param {Function} onThinking  - 收到 thinking 事件时回调 ({ step, title, content }) => void
 */
function streamRequest(params, onChunk, onThinking) {
  const userStore = useUserStore()
  const token = userStore.token

  return new Promise((resolve, reject) => {
    let fullAnswer = ''
    let realTalkId = null
    let title = '回答'
    let finished = false
    // 记录最近一次收到的 SSE id 字段，用于断线续传
    let lastEventId = null
    let retryCount = 0

    function safeResolve(payload) {
      if (finished) return
      finished = true
      resolve(payload)
    }

    function safeReject(error) {
      if (finished) return
      finished = true
      reject(error)
    }

    function buildResult() {
      return {
        data: {
          talkId: realTalkId,
          title,
          content: fullAnswer,
        },
      }
    }

    /**
     * 解析单个 SSE 消息块（两个 \n\n 之间的内容）
     */
    function handleMessageBlock(block) {
      if (!block.trim()) return

      const lines = block.split(/\r?\n/)
      const dataLines = []
      let eventName = 'message'

      for (const line of lines) {
        if (!line) continue
        // SSE comment（心跳 / close），直接忽略
        if (line.startsWith(':')) continue
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim() || 'message'
          continue
        }
        // 记录 SSE id，用于断线续传的 Last-Event-ID
        if (line.startsWith('id:')) {
          lastEventId = line.slice(3).trim()
          continue
        }
        if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart())
        }
      }

      if (dataLines.length === 0) return

      const jsonStr = dataLines.join('\n').trim()
      if (!jsonStr) return

      try {
        const data = JSON.parse(jsonStr)
        const type = data.type || eventName

        // 任何事件都提取 talkId（init 事件携带真实 talkId，比 done 更早）
        const nextTalkId = normalizeTalkId(data.talkId)
        if (nextTalkId) realTalkId = nextTalkId
        if (data.title) title = data.title
        if (data.name && (!title || title === '回答')) title = data.name

        // ── init：后端确认本次 talkId，早于 done 事件，用于提前更新 talkId ──
        if (type === 'init') {
          return
        }

        // ── thinking：AI 推理中间过程，回调通知 UI 显示进度 ──
        if (type === 'thinking') {
          if (onThinking) {
            onThinking(
              data.thinking || {
                step: data.step || '',
                title: data.title || '',
                content: data.content || '',
              },
            )
          }
          return
        }

        // ── meta / resume：内部事件，前端无需处理 ──
        if (type === 'meta' || type === 'resume') {
          return
        }

        // ── warning：超长行截断等告警，打印日志即可 ──
        if (type === 'warning') {
          console.warn('[SSE Warning]', data.message)
          return
        }

        // ── chunk：答案片段，追加到全文并触发实时渲染 ──
        if (type === 'chunk') {
          const text = data.content || ''
          fullAnswer += text
          if (onChunk) onChunk(text)
          return
        }

        // ── done：流正常结束 ──
        if (type === 'done') {
          safeResolve(buildResult())
          return
        }

        // ── error：业务错误，附加结构化错误码便于调用方判断是否可重试 ──
        if (type === 'error') {
          const err = new Error(data.message || '流式响应错误')
          err.code = data.error?.code || ''
          err.retryable = data.error?.retryable ?? false
          safeReject(err)
        }
      } catch (e) {
        console.error('解析 SSE 块失败', e, jsonStr)
      }
    }

    /**
     * 发起一次 HTTP 连接并消费 SSE 流。
     * 网络意外断开时抛出 isNetworkError=true 的 Error，供外层决策是否重连。
     *
     * @param {Object} connectParams - 本次实际发送的请求体（重连时含正确 talkId）
     */
    async function doConnect(connectParams) {
      const headers = {
        'Content-Type': 'application/json',
        Authorization: token,
        token,
      }
      // 断线续传：携带最近的 SSE id，后端将从该序号之后开始回放
      if (lastEventId) {
        headers['Last-Event-ID'] = lastEventId
      }

      const res = await fetch('/api/user/ques/streamingQues', {
        method: 'POST',
        headers,
        body: JSON.stringify(connectParams),
      })

      if (!res.ok) {
        let message = `请求失败: ${res.status}`
        try {
          const text = await res.text()
          if (text) message = text
        } catch {
          // ignore
        }
        const err = new Error(message)
        err.isHttpError = true
        throw err
      }

      if (!res.body) {
        const err = new Error('ReadableStream 不存在')
        err.isHttpError = true
        throw err
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      try {
        while (true) {
          const { value, done } = await reader.read()

          if (done) {
            // 流关闭：处理缓冲区剩余内容
            buffer += decoder.decode()
            buffer = buffer.replace(/\r\n/g, '\n')
            while (buffer.includes('\n\n')) {
              const idx = buffer.indexOf('\n\n')
              const block = buffer.slice(0, idx)
              buffer = buffer.slice(idx + 2)
              handleMessageBlock(block)
              if (finished) return
            }
            // 流结束但未收到 done 事件：视为网络意外断开，抛出可重试错误
            if (!finished) {
              const err = new Error('连接意外关闭')
              err.isNetworkError = true
              throw err
            }
            return
          }

          buffer += decoder.decode(value, { stream: true })
          buffer = buffer.replace(/\r\n/g, '\n')

          while (buffer.includes('\n\n')) {
            const idx = buffer.indexOf('\n\n')
            const block = buffer.slice(0, idx)
            buffer = buffer.slice(idx + 2)
            handleMessageBlock(block)
            if (finished) {
              try {
                await reader.cancel()
              } catch {
                // ignore cancel errors
              }
              return
            }
          }
        }
      } catch (err) {
        try {
          await reader.cancel()
        } catch {
          // ignore
        }
        throw err
      }
    }

    /**
     * 带指数退避重连的主循环。
     * 仅在网络断开（isNetworkError）且有 lastEventId 时重试，
     * HTTP 错误或 SSE 业务 error 事件不重试。
     */
    async function run() {
      while (true) {
        // 重连时将已捕获的 realTalkId 写入请求体，确保后端能校验 Last-Event-ID
        const connectParams =
          lastEventId && realTalkId ? { ...params, talkId: realTalkId } : params

        try {
          await doConnect(connectParams)
          if (!finished) safeResolve(buildResult())
          return
        } catch (err) {
          if (finished) return

          // 网络断开 + 有续传锚点 + 未超出重试上限 → 等待后重连
          if (err.isNetworkError && lastEventId && retryCount < MAX_RETRIES) {
            retryCount++
            const delay = retryCount * 1000
            console.warn(
              `[SSE] 连接断开，${delay / 1000}s 后重试 (${retryCount}/${MAX_RETRIES})，Last-Event-ID: ${lastEventId}`,
            )
            await new Promise((r) => setTimeout(r, delay))
            continue
          }

          safeReject(err)
          return
        }
      }
    }

    run().catch(safeReject)
  })
}

export const sendQuestionStreamAPI = (params, onChunk, onThinking) =>
  streamRequest(params, onChunk, onThinking)

export const newChatStreamAPI = (params, onChunk, onThinking) =>
  streamRequest(params, onChunk, onThinking)

// 5. 删除对话
// talkId: String
export const deleteChatAPI = (talkId) => request.delete(`/user/deleteTalk/${talkId}`)

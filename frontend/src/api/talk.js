import { useUserStore } from '@/stores/user'
import request from '@/utils/request'

// 1. 获取历史对话标题
export const getChatTitlesAPI = () => request.get('/user/title')

// 2. 查询历史对话内容
// talkId: Number
export const getChatHistoryAPI = (talkId) => request.get(`/user/ques/getQues/${talkId}`)

// 3. 继续对话（发送问题）
// params = { talkId: Number, question: String }
export const sendQuestionAPI = (params) => request.post('/user/ques/getQues', params)

// 4. 新建对话
// params = { question: String }
export const newChatAPI = (params) => request.post('/user/ques/newGetQues', params)

function streamRequest(params, onChunk) {
  const userStore = useUserStore()
  const token = userStore.token

  return new Promise((resolve, reject) => {
    fetch('/api/user/ques/streamingQues', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        token,
      },
      body: JSON.stringify(params),
    })
      .then(async (res) => {
        if (!res.ok) {
          let message = `请求失败: ${res.status}`
          try {
            const text = await res.text()
            if (text) message = text
          } catch {
            // ignore
          }
          reject(new Error(message))
          return
        }

        if (!res.body) {
          reject(new Error('ReadableStream 不存在'))
          return
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder('utf-8')

        let fullAnswer = ''
        let realTalkId = null
        let title = '回答'
        let finished = false
        let buffer = ''
        let currentEvent = 'message'

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

        function handleMessageBlock(block) {
          if (!block.trim()) return

          const lines = block.split(/\r?\n/)
          const dataLines = []
          let eventName = currentEvent || 'message'

          for (const line of lines) {
            if (!line) continue
            if (line.startsWith(':')) continue
            if (line.startsWith('event:')) {
              eventName = line.slice(6).trim() || 'message'
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

            if (data.talkId) {
              realTalkId = data.talkId
            }
            if (data.title) {
              title = data.title
            }
            if (data.name && (!title || title === '回答')) {
              title = data.name
            }

            if (type === 'chunk') {
              const text = data.content || ''
              fullAnswer += text
              if (onChunk) onChunk(text)
              return
            }

            if (type === 'done') {
              safeResolve(buildResult())
              return
            }

            if (type === 'error') {
              safeReject(new Error(data.message || data.error || '流式响应错误'))
            }
          } catch (e) {
            console.error('解析流失败', e, jsonStr)
          }
        }

        async function readChunk() {
          try {
            while (true) {
              const { value, done } = await reader.read()
              if (done) {
                buffer += decoder.decode()
                while (buffer.includes('\n\n')) {
                  const idx = buffer.indexOf('\n\n')
                  const block = buffer.slice(0, idx)
                  buffer = buffer.slice(idx + 2)
                  handleMessageBlock(block)
                  if (finished) return
                }

                // EOF 兜底：如果后端正常关闭但前端漏掉 done，至少结束 loading
                if (!finished) {
                  safeResolve(buildResult())
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
          } catch (error) {
            safeReject(error)
          }
        }

        readChunk()
      })
      .catch(reject)
  })
}

export const sendQuestionStreamAPI = (params, onChunk) => streamRequest(params, onChunk)

export const newChatStreamAPI = (params, onChunk) => streamRequest(params, onChunk)

// 5. 删除对话
// talkId: Number
export const deleteChatAPI = (talkId) => request.delete(`/user/deleteTalk/${talkId}`)

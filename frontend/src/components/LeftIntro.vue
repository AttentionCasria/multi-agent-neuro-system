<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import pause from '@/utils/pause'

const typedText = ref('')
const cursorShow = ref(true)
const typingTextIndex = ref(0)
const introductions = [
  '脑卒中深度检索多智能体助手——以循证医学为引擎的智能临床辅助平台。',
  '融合现代医学最新指南与权威文献，提供基于证据的深度思考与分析。',
  '专注脑卒中医疗，从风险预警、急性识别到辅助治疗。',
  '以可靠信息降低认知负荷，为诊疗决策提供清晰、更新的知识支持。'
]

const currentIndex = ref(0)
const isLeaving = ref(false)
const tailEntering = ref(false)
const alive = ref(true)

const VISIBLE_CARD_COUNT = 3
const TYPE_DELAY = 90
const HOLD_AFTER_TYPING = 1300
const LEAVE_DURATION = 550
const CARD_ANGLES = [-4, 3, -2, 4]
const CARD_LAYOUT = [
  { x: 0, y: 0, scale: 1, opacity: 1 },
  { x: 20, y: 14, scale: 0.94, opacity: 0.88 },
  { x: -20, y: 28, scale: 0.89, opacity: 0.76 },
]

const stackCards = computed(() => {
  const cardCount = isLeaving.value
    ? VISIBLE_CARD_COUNT + 1
    : VISIBLE_CARD_COUNT

  return Array.from({ length: cardCount }, (_, layer) => {
    const textIndex = (currentIndex.value + layer) % introductions.length
    return {
      layer,
      textIndex,
      text: introductions[textIndex]
    }
  })
})

function getCardStyle(layer, textIndex) {
  let rotate = CARD_ANGLES[textIndex % CARD_ANGLES.length]
  const safeLayer = Math.min(layer, VISIBLE_CARD_COUNT - 1)
  const layout = CARD_LAYOUT[safeLayer]
  const baseX = layout.x
  const baseY = layout.y
  const baseScale = layout.scale
  const baseOpacity = layout.opacity

  let x = baseX
  let y = baseY
  let scale = baseScale
  let opacity = baseOpacity
  let zIndex = 20 - layer

  if (isLeaving.value) {
    if (layer === 0) {
      x = -340
      y = -26
      scale = 0.9
      opacity = 0
      rotate -= 14
      zIndex = 22
    } else {
      const frontLayer = Math.min(layer - 1, VISIBLE_CARD_COUNT - 1)
      const frontLayout = CARD_LAYOUT[frontLayer]
      x = frontLayout.x
      y = frontLayout.y
      scale = frontLayout.scale
      opacity = frontLayout.opacity
      zIndex = 21 - layer

      if (layer === VISIBLE_CARD_COUNT && tailEntering.value) {
        x = frontLayout.x + 34
        y = frontLayout.y + 26
        scale = frontLayout.scale - 0.1
        opacity = 0
      }
    }
  }

  return {
    zIndex,
    opacity,
    transform: `translate(${x}px, ${y}px) rotate(${rotate}deg) scale(${scale})`
  }
}

defineOptions({
  name: 'LoginView',
})

onMounted(async () => {
  startTypingLoop()
})

onBeforeUnmount(() => {
  alive.value = false
})

function nextFrame() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve())
  })
}

async function startTypingLoop() {
  while (alive.value) {
    isLeaving.value = false
    typingTextIndex.value = currentIndex.value
    await typing(introductions[currentIndex.value])
    if (!alive.value) {
      break
    }

    await pause(HOLD_AFTER_TYPING)
    if (!alive.value) {
      break
    }

    const nextIndex = (currentIndex.value + 1) % introductions.length
    typedText.value = ''
    cursorShow.value = false
    typingTextIndex.value = nextIndex

    isLeaving.value = true
    tailEntering.value = true
    await nextTick()
    await nextFrame()
    tailEntering.value = false
    await pause(LEAVE_DURATION)

    currentIndex.value = nextIndex
    isLeaving.value = false
  }
}

function typing(text, delay = TYPE_DELAY) {
  return new Promise((resolve) => {
    let index = 0
    typedText.value = ''
    cursorShow.value = true

    const interval = setInterval(() => {
      if (!alive.value) {
        clearInterval(interval)
        resolve()
        return
      }

      typedText.value += text[index]
      index++
      if (index >= text.length) {
        clearInterval(interval)
        cursorShow.value = false
        resolve()
      }
    }, delay)
  })
}
</script>

<template>
  <div class="intro-shell">
    <div class="title">Synapse MD
      <div class="sub-title">
        脑卒中健康辅助诊疗系统，提供健康辅助诊疗
      </div>
    </div>
    <div class="card-area">
      <div class="card-stack">
        <div v-for="card in stackCards" :key="card.textIndex" class="intro-card"
          :class="{ leaving: card.layer === 0 && isLeaving }" :style="getCardStyle(card.layer, card.textIndex)">
          <span class="typing-text">
            {{ card.textIndex === typingTextIndex ? typedText : card.text }}
            <span class="cursor" v-show="card.textIndex === typingTextIndex && cursorShow">●</span>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.intro-shell {
  height: 100%;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.title {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  font-size: 2rem;
  margin-bottom: 2rem;
  color: var(--color-text-strong);
}

.sub-title {
  font-size: 1.4rem;
  margin-top: 12px;
  margin-bottom: 2rem;
  color: var(--color-text-medium);
}

.card-area {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card-stack {
  position: relative;
  width: min(640px, 82vw);
  height: 220px;
  margin: 0 auto;
  perspective: 1200px;
}

.intro-card {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  border-radius: var(--radius-xl);
  border: 1px solid rgba(17, 150, 127, 0.2);
  background: var(--color-card-intro-bg);
  box-shadow: var(--color-card-intro-shadow);
  will-change: transform, opacity;
  transition: transform 0.55s cubic-bezier(0.22, 1, 0.36, 1);

  &.leaving {
    opacity: 0 !important;
    transition:
      transform 0.46s cubic-bezier(0.2, 0.78, 0.2, 1),
      opacity 0.2s cubic-bezier(0.4, 0, 1, 1);
  }
}

.typing-text {
  font-size: 1.85rem;
  line-height: 1.6;
  color: var(--color-text-strong);
  text-align: center;
  white-space: pre-wrap;
  word-break: break-word;
}

.cursor {
  margin-left: 0.3rem;
  color: var(--color-primary);
  animation: blink 1s infinite;
  font-size: 1.8rem;
}

@keyframes blink {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0;
  }
}

@media (max-width: 768px) {
  .card-stack {
    height: 240px;
    width: min(86vw, 520px);
  }

  .intro-card {
    padding: 1.5rem 1.2rem;
    border-radius: 18px;
  }

  .typing-text {
    font-size: 1.35rem;
  }

  .cursor {
    font-size: 1.3rem;
  }
}
</style>

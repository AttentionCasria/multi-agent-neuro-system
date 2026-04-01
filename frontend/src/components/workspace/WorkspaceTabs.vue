<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

defineOptions({ name: 'WorkspaceTabs' })

const props = defineProps({
  tabs: {
    type: Array,
    default: () => [],
  },
  activeTab: {
    type: String,
    required: true,
  },
  activeChildTab: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['change'])

const rootRef = ref(null)
const openMenuKey = ref('')

const activeSubtitles = computed(() => {
  const map = {}

  for (const tab of props.tabs) {
    if (!tab.children?.length) continue
    const currentChild = tab.children.find((item) => item.key === props.activeChildTab)
    map[tab.key] = currentChild?.shortLabel || currentChild?.label || ''
  }

  return map
})

function handleDocumentClick(event) {
  if (!rootRef.value?.contains(event.target)) {
    openMenuKey.value = ''
  }
}

function handleEscape(event) {
  if (event.key === 'Escape') {
    openMenuKey.value = ''
  }
}

function toggleMenu(tabKey) {
  openMenuKey.value = openMenuKey.value === tabKey ? '' : tabKey
}

function handleTabClick(tab) {
  if (tab.children?.length) {
    toggleMenu(tab.key)
    return
  }

  openMenuKey.value = ''
  emit('change', { key: tab.key })
}

function handleChildClick(parentKey, childKey) {
  openMenuKey.value = ''
  emit('change', { key: parentKey, childKey })
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  document.addEventListener('keydown', handleEscape)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
  document.removeEventListener('keydown', handleEscape)
})
</script>

<template>
  <nav ref="rootRef" class="workspace-tabs" aria-label="工作台模块切换">
    <div v-for="tab in tabs" :key="tab.key" class="tab-item">
      <button type="button" class="tab-btn"
        :class="{ active: tab.key === activeTab, expanded: openMenuKey === tab.key }"
        :aria-expanded="tab.children?.length ? String(openMenuKey === tab.key) : undefined"
        :aria-haspopup="tab.children?.length ? 'menu' : undefined" @click.stop="handleTabClick(tab)">
        <span>{{ tab.label }}</span>
        <small v-if="tab.key === activeTab && activeSubtitles[tab.key]" class="tab-subtitle">{{ activeSubtitles[tab.key]
          }}</small>
        <span v-if="tab.children?.length" class="tab-caret" aria-hidden="true"></span>
      </button>

      <transition name="tab-menu-fade">
        <div v-if="tab.children?.length && openMenuKey === tab.key" class="tab-menu" role="menu">
          <button v-for="item in tab.children" :key="item.key" type="button" class="menu-item"
            :class="{ active: tab.key === activeTab && item.key === activeChildTab }" role="menuitem"
            @click.stop="handleChildClick(tab.key, item.key)">
            <span>{{ item.label }}</span>
            <small v-if="item.description">{{ item.description }}</small>
          </button>
        </div>
      </transition>
    </div>
  </nav>
</template>

<style scoped lang="scss">
.workspace-tabs {
  display: flex;
  align-items: stretch;
  height: 100%;
  overflow: visible;
}

.tab-item {
  position: relative;
  height: 100%;
}

.tab-btn {
  border: none;
  border-bottom: 2px solid transparent;
  padding: 0 18px;
  background: transparent;
  color: var(--color-text-medium);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition-normal);
  white-space: nowrap;
  height: 100%;
  display: inline-flex;
  align-items: center;
  gap: 8px;

  span {
    display: block;
  }

  small {
    line-height: 1;
  }

  &:hover {
    color: var(--color-text-strong);
    background: var(--color-ghost-hover);
  }

  &.active,
  &.expanded {
    color: var(--color-primary);
    background: transparent;
  }

  &.active {
    border-bottom-color: var(--color-primary);
  }
}

.tab-subtitle {
  padding: 4px 8px;
  border-radius: var(--radius-pill);
  background: var(--color-secondary-bg);
  color: var(--color-text-medium);
  font-size: 11px;
  font-weight: 700;
}

.tab-caret {
  width: 6px;
  height: 6px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(45deg) translateY(-1px);
  transform-origin: center;
  transition:
    transform 0.22s cubic-bezier(0.22, 1, 0.36, 1),
    opacity 0.18s ease;
}

.expanded .tab-caret {
  transform: rotate(225deg) translateY(-1px);
}

.tab-menu {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  min-width: 220px;
  padding: 8px;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-bg-base);
  box-shadow: var(--shadow-menu);
  z-index: 20;
  transform-origin: top left;
}

.tab-menu-fade-enter-active,
.tab-menu-fade-leave-active {
  transition:
    opacity 0.18s ease,
    transform 0.22s cubic-bezier(0.22, 1, 0.36, 1);
}

.tab-menu-fade-enter-from,
.tab-menu-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.tab-menu-fade-enter-to,
.tab-menu-fade-leave-from {
  opacity: 1;
  transform: translateY(0);
}

.menu-item {
  width: 100%;
  border: none;
  border-radius: 10px;
  background: transparent;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  margin: 4px 0;
  color: var(--color-text-medium);
  text-align: left;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);

  span {
    font-size: 14px;
    font-weight: 700;
  }

  small {
    font-size: 12px;
    color: var(--color-text-medium);
  }

  &:hover {
    background: var(--color-hover-bg);
    color: var(--color-text-strong);
  }

  &.active {
    background: var(--color-active-bg);
    color: var(--color-primary);
  }
}
</style>

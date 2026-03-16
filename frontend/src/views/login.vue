<script setup>
defineOptions({
  name: 'LoginIndex',
})
import LeftIntro from '@/components/LeftIntro.vue'
import RightForm from '@/components/form/RightForm.vue'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()
</script>

<template>
  <div class="login-page">
    <button type="button" class="login-theme-toggle" :title="themeStore.dark ? '切换到浅色模式' : '切换到深色模式'"
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
    <div class="login-left">
      <LeftIntro></LeftIntro>
    </div>
    <div class="login-right">
      <RightForm></RightForm>
    </div>
  </div>
</template>

<style scoped lang="scss">
.login-page {
  position: relative;
  display: flex;
  width: 100%;
  height: 100vh;
  background: var(--color-bg-base);
}

.login-theme-toggle {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-base);
  color: var(--color-text-medium);
  cursor: pointer;
  transition: all var(--transition-normal);

  &:hover {
    background: var(--color-ghost-hover);
    color: var(--color-text-strong);
  }
}

.login-left {
  flex: 6;
  min-width: 0;
  background: var(--color-bg-light);
  color: var(--color-text-strong);
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  padding: 2rem;
  border-right: 1px solid var(--color-border);
}

.login-right {
  flex: 4;
  min-width: 0;
  background:
    radial-gradient(circle at top, rgba(17, 150, 127, 0.08), transparent 42%),
    linear-gradient(180deg, var(--color-bg-base), var(--color-bg-light));
  color: var(--color-text-strong);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
}

@media (max-width: 960px) {
  .login-page {
    flex-direction: column;
  }

  .login-left {
    flex: none;
    display: none;
    min-height: 280px;
    border-right: none;
    border-bottom: 1px solid var(--color-border);
  }

  .login-right {
    flex: 1;
    padding: 2rem 1rem;
  }
}
</style>

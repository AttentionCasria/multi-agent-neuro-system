<script lang="ts" setup>
defineProps({
  size: {
    type: String,
    default: '32',
  },
  color: {
    type: String,
    default: '#000000',
  },
})
</script>

<template>
  <svg xmlns="http://www.w3.org/2000/svg" :height="size" viewBox="0 -960 960 960" :width="size" :fill="color">
    <path d="M480-344 240-584l56-56 184 184 184-184 56 56-240 240Z" />
  </svg>

</template>

<style scoped lang="scss"></style>

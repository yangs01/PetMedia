<script setup>
defineProps({
  message: { type: String, required: true },
  title: { type: String, default: '' },
  actionLabel: { type: String, default: '' },
  tone: { type: String, default: 'failed' },
})
defineEmits(['action'])
</script>

<template>
  <div class="banner fade-in" :class="`banner--${tone}`" role="alert">
    <div>
      <strong v-if="title" class="banner__title">{{ title }}</strong>
      <span class="banner__message">{{ message }}</span>
    </div>
    <button v-if="actionLabel" type="button" class="button button--small" @click="$emit('action')">
      {{ actionLabel }}
    </button>
  </div>
</template>

<style scoped>
.banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 14px;
  padding: 10px 14px;
  border: 1px solid;
  border-radius: var(--radius-small);
  font-size: 0.9rem;
  overflow-wrap: anywhere;
}

.banner--failed {
  background: var(--failed-soft);
  border-color: color-mix(in srgb, var(--failed) 35%, transparent);
}

.banner--waiting {
  background: var(--waiting-soft);
  border-color: color-mix(in srgb, var(--waiting) 35%, transparent);
}

.banner__title {
  display: block;
}
</style>

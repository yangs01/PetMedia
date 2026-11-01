<script setup>
defineProps({
  title: { type: String, required: true },
  message: { type: String, default: '' },
})
</script>

<template>
  <div class="empty">
    <h3>{{ title }}</h3>
    <p v-if="message" class="muted small">{{ message }}</p>
    <div v-if="$slots.default" class="empty__action"><slot /></div>
  </div>
</template>

<style scoped>
.empty {
  padding: 30px 16px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-small);
  text-align: center;
}

.empty__action {
  margin-top: 12px;
}
</style>

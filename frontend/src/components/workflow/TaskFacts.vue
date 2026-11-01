<script setup>
import { formatDateTime } from '@/utils/format'

defineProps({
  task: { type: Object, required: true },
  brandName: { type: String, default: '' },
  productNames: { type: Array, default: () => [] },
})
</script>

<template>
  <section class="card">
    <div class="card__title"><h2>Task details</h2></div>
    <dl class="facts small">
      <dt>Brand</dt>
      <dd>{{ brandName || '…' }}</dd>
      <dt>Products</dt>
      <dd>{{ productNames.length ? productNames.join(', ') : '…' }}</dd>
      <dt>Market</dt>
      <dd>{{ task.target_market }}</dd>
      <template v-if="task.target_audience">
        <dt>Audience</dt>
        <dd>{{ task.target_audience }}</dd>
      </template>
      <template v-if="task.marketing_goal">
        <dt>Goal</dt>
        <dd>{{ task.marketing_goal }}</dd>
      </template>
      <dt>Channels</dt>
      <dd>{{ task.channels.join(', ') }}</dd>
      <dt>Slides</dt>
      <dd>{{ task.image_count }}</dd>
      <dt>Created</dt>
      <dd>{{ formatDateTime(task.created_at) }}</dd>
      <dt>Updated</dt>
      <dd>{{ formatDateTime(task.updated_at) }}</dd>
      <template v-if="task.completed_at">
        <dt>Completed</dt>
        <dd>{{ formatDateTime(task.completed_at) }}</dd>
      </template>
      <dt>Thread</dt>
      <dd class="mono">{{ task.thread_id }}</dd>
    </dl>
  </section>
</template>

<style scoped>
.facts {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 4px 12px;
  margin: 0;
}

.facts dt {
  color: var(--text-muted);
}

.facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}
</style>

<script setup>
import { computed } from 'vue'

import StatusBadge from '@/components/common/StatusBadge.vue'
import { formatDateTime } from '@/utils/format'
import { STATE_LABELS } from '@/workflow/graph'

const props = defineProps({
  node: { type: Object, required: true },
  isActive: { type: Boolean, default: false },
})

const tone = computed(() => props.node.state)
const usesModel = computed(() => props.node.kind === 'ai')
</script>

<template>
  <section class="card">
    <div class="card__title">
      <h2>{{ node.title }}</h2>
      <StatusBadge :label="STATE_LABELS[node.state]" :tone="tone" />
    </div>
    <p class="small">{{ node.detail }}</p>
    <p v-if="isActive" class="small active">Current active node</p>

    <dl class="facts small">
      <template v-if="usesModel">
        <dt>Provider</dt>
        <dd>{{ node.provider || 'Not reported yet' }}</dd>
        <dt>Model</dt>
        <dd>{{ node.model || 'Not recorded' }}</dd>
      </template>
      <template v-else>
        <dt>Handled by</dt>
        <dd>{{ node.engine }}</dd>
      </template>
      <template v-for="item in node.perChannel ?? []" :key="item.platform">
        <dt>{{ item.platform }}</dt>
        <dd>{{ item.provider }}</dd>
      </template>
      <template v-if="node.promptVersion">
        <dt>Prompt</dt>
        <dd class="mono">{{ node.promptVersion }}</dd>
      </template>
    </dl>
    <p v-if="usesModel && !node.model && node.modelNote" class="muted small note">{{ node.modelNote }}</p>

    <h3 class="timeline-title">Timeline</h3>
    <ol v-if="node.timeline.length" class="timeline small">
      <li v-for="(entry, index) in node.timeline" :key="index">
        <span>{{ entry.label }}</span>
        <time class="muted">{{ formatDateTime(entry.at) }}</time>
      </li>
    </ol>
    <p v-else class="muted small">Nothing recorded for this node yet.</p>
  </section>
</template>

<style scoped>
.active {
  margin-top: 2px;
  color: var(--accent-strong);
  font-weight: 600;
}

.facts {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 3px 12px;
  margin: 12px 0 0;
}

.facts dt {
  color: var(--text-muted);
  text-transform: capitalize;
}

.facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.note {
  margin-top: 6px;
}

.timeline-title {
  margin-top: 14px;
  margin-bottom: 6px;
}

.timeline {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.timeline li {
  display: grid;
  overflow-wrap: anywhere;
}

.timeline time {
  font-size: 0.78rem;
}
</style>

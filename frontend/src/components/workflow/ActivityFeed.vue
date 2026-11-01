<script setup>
import { computed } from 'vue'

import { formatDateTime } from '@/utils/format'
import { statusInfo } from '@/utils/status'

const props = defineProps({
  events: { type: Array, required: true },
})

const entries = computed(() =>
  [...props.events].reverse().map((event) => ({
    ...event,
    summary: summarize(event),
    tone: event.to_status ? statusInfo(event.to_status).tone : 'failed',
  })),
)

function summarize(event) {
  if (event.event_type === 'STATUS_CHANGED') return statusInfo(event.to_status).label
  return event.event_type.replaceAll('_', ' ').toLowerCase()
}
</script>

<template>
  <section class="card">
    <div class="card__title">
      <h2>Execution history</h2>
      <span class="muted small">{{ events.length }} events</span>
    </div>
    <p v-if="!events.length" class="muted small">No events yet.</p>
    <ol v-else class="feed small">
      <li v-for="event in entries" :key="event.id" class="feed__item fade-in">
        <span class="feed__dot" :class="`feed__dot--${event.tone}`" aria-hidden="true" />
        <div class="feed__body">
          <strong class="feed__summary">{{ event.summary }}</strong>
          <span v-if="event.from_status" class="muted"> from {{ statusInfo(event.from_status).label }}</span>
          <div v-if="event.node_name && event.node_name !== 'review'" class="mono muted">{{ event.node_name }}</div>
          <div v-if="event.message" class="feed__message">{{ event.message }}</div>
          <time class="muted feed__time">{{ formatDateTime(event.created_at) }}</time>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.feed {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.feed__item {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr);
  gap: 10px;
  padding: 6px 0;
}

.feed__dot {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 50%;
}

.feed__dot--completed {
  background: var(--completed);
}

.feed__dot--running {
  background: var(--running);
}

.feed__dot--waiting {
  background: var(--waiting);
}

.feed__dot--failed {
  background: var(--failed);
}

.feed__dot--queued {
  background: var(--queued);
}

.feed__dot--cancelled,
.feed__dot--pending {
  background: var(--cancelled);
}

.feed__summary {
  text-transform: none;
  font-weight: 600;
}

.feed__body {
  min-width: 0;
  overflow-wrap: anywhere;
}

.feed__time {
  display: block;
  font-size: 0.78rem;
}
</style>

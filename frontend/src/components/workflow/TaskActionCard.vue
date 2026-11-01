<script setup>
import { computed } from 'vue'

import ConfirmButton from '@/components/common/ConfirmButton.vue'
import ErrorBanner from '@/components/common/ErrorBanner.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import CopyReview from '@/components/review/CopyReview.vue'
import ImageReview from '@/components/review/ImageReview.vue'
import TopicReview from '@/components/review/TopicReview.vue'
import { statusInfo } from '@/utils/status'

const QUEUE_HINT_SECONDS = 20
const STALL_HINT_SECONDS = 180

const props = defineProps({
  task: { type: Object, required: true },
  workflow: { type: Object, required: true },
  topics: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  actionError: { type: String, default: '' },
  idleSeconds: { type: Number, default: 0 },
})
const emit = defineEmits(['decide', 'retry', 'cancel'])

const status = computed(() => props.task.status)
const isReview = computed(() => props.task.review_stage !== null)
const activeTitle = computed(() => props.workflow.nodes[props.workflow.activeNode]?.title ?? '')

const heading = computed(() => {
  if (status.value === 'AWAITING_TOPIC_REVIEW') return 'Your turn: choose a topic'
  if (status.value === 'AWAITING_COPY_REVIEW') return 'Your turn: review the copy'
  if (status.value === 'AWAITING_IMAGE_REVIEW') return 'Your turn: review the images'
  if (status.value === 'FAILED') return `Stopped at ${activeTitle.value}`
  if (status.value === 'READY') return 'Workflow complete'
  if (status.value === 'CANCELLED') return `Cancelled at ${activeTitle.value}`
  if (status.value === 'QUEUED' || status.value === 'CREATED') return `Waiting for a worker: ${activeTitle.value}`
  return `The agent is working: ${activeTitle.value}`
})

const errorDetails = computed(() => {
  const details = props.task.error?.details
  return details && Object.keys(details).length ? JSON.stringify(details, null, 2) : ''
})

const isQueued = computed(() => status.value === 'QUEUED' || status.value === 'CREATED')
const looksStuck = computed(() => {
  if (isQueued.value) return props.idleSeconds > QUEUE_HINT_SECONDS
  return statusInfo(status.value).tone === 'running' && props.idleSeconds > STALL_HINT_SECONDS
})
const canCancelQueued = computed(() => props.task.available_actions.includes('cancel'))
</script>

<template>
  <section class="card action" :class="{ 'action--review': isReview }">
    <div class="card__title">
      <h2>{{ heading }}</h2>
      <StatusBadge :label="statusInfo(status).label" :tone="statusInfo(status).tone" />
    </div>

    <ErrorBanner v-if="actionError" :message="actionError" title="That action did not go through" class="action__error" />

    <TopicReview
      v-if="status === 'AWAITING_TOPIC_REVIEW'"
      :topics="topics"
      :busy="busy"
      @decide="emit('decide', 'topic', $event)"
    />
    <CopyReview
      v-else-if="status === 'AWAITING_COPY_REVIEW' && task.current_version"
      :version="task.current_version"
      :busy="busy"
      @decide="emit('decide', 'copy', $event)"
    />
    <ImageReview
      v-else-if="status === 'AWAITING_IMAGE_REVIEW'"
      :task="task"
      :busy="busy"
      @decide="emit('decide', 'image', $event)"
    />

    <div v-else-if="status === 'FAILED'" class="stack">
      <ErrorBanner
        :title="task.error?.code ?? 'Error'"
        :message="task.error?.message ?? 'The workflow stopped with an error.'"
      />
      <details v-if="errorDetails" class="small">
        <summary>Technical details</summary>
        <pre class="details-text mono">{{ errorDetails }}</pre>
      </details>
      <p class="small muted">Retrying continues from the last checkpoint. Finished work is not repeated.</p>
      <div class="row">
        <button type="button" class="button button--primary" :disabled="busy" @click="emit('retry')">Retry</button>
        <ConfirmButton
          label="Cancel task"
          question="Cancel this task?"
          confirm-label="Yes, cancel"
          :disabled="busy"
          @confirm="emit('cancel')"
        />
      </div>
    </div>

    <p v-else-if="status === 'READY'" class="small muted">
      All approvals are done. Preview the content below and download the package.
    </p>
    <p v-else-if="status === 'CANCELLED'" class="small muted">This task was cancelled and will not run again.</p>

    <div v-else class="stack">
      <p class="small muted">
        {{
          isQueued
            ? 'The task is in the queue and starts when a worker picks it up.'
            : 'No action is needed. A running step cannot be cancelled. You can cancel at the next review.'
        }}
      </p>
      <ErrorBanner
        v-if="looksStuck"
        tone="waiting"
        title="No progress for a while"
        :message="
          isQueued
            ? 'Check that the worker is running: uv run python -m app.workers.main'
            : 'The step may just be slow. If the worker stopped, restart it and the task will recover.'
        "
      />
      <div v-if="isQueued && canCancelQueued">
        <ConfirmButton
          label="Cancel task"
          question="Cancel this task?"
          confirm-label="Yes, cancel"
          :disabled="busy"
          @confirm="emit('cancel')"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.action--review {
  border-color: var(--waiting);
  box-shadow:
    0 0 0 1px var(--waiting),
    var(--shadow);
}

.action__error {
  margin-bottom: 12px;
}

.details-text {
  margin: 8px 0 0;
  padding: 8px;
  max-height: 200px;
  overflow: auto;
  background: var(--surface-2);
  border-radius: var(--radius-small);
  white-space: pre-wrap;
}
</style>

<script setup>
import { computed, ref, watch } from 'vue'

import ConfirmButton from '@/components/common/ConfirmButton.vue'

const props = defineProps({
  topics: { type: Array, required: true },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['decide'])

const selectedId = ref(null)
const feedback = ref('')

const latestBatch = computed(() => Math.max(0, ...props.topics.map((topic) => topic.batch_number)))
const current = computed(() => props.topics.filter((topic) => topic.batch_number === latestBatch.value))
const earlier = computed(() => props.topics.filter((topic) => topic.batch_number !== latestBatch.value))

watch(latestBatch, () => {
  selectedId.value = null
})

function select() {
  emit('decide', { action: 'select', selected_topic_id: selectedId.value })
}

function regenerate() {
  emit('decide', { action: 'regenerate', feedback: feedback.value.trim() || null })
}
</script>

<template>
  <div class="stack">
    <p class="small muted">Batch {{ latestBatch }}. Choose the topic the agent should write about.</p>
    <p v-if="!current.length" class="muted small">Loading topics…</p>

    <div class="topics" role="radiogroup" aria-label="Topics">
      <label v-for="topic in current" :key="topic.id" class="topic" :class="{ 'topic--selected': selectedId === topic.id }">
        <input v-model="selectedId" type="radio" name="topic" :value="topic.id" />
        <span class="topic__body">
          <strong class="topic__title">{{ topic.title }}</strong>
          <span class="small">{{ topic.angle }}</span>
          <span class="small muted"><em>Hook:</em> {{ topic.hook }}</span>
          <span class="small muted"><em>Audience:</em> {{ topic.target_audience }}</span>
          <span class="small muted"><em>Why it fits:</em> {{ topic.product_relevance }}</span>
          <span class="tag topic__type">{{ topic.content_type.replaceAll('_', ' ') }}</span>
        </span>
      </label>
    </div>

    <div class="row">
      <button type="button" class="button button--primary" :disabled="!selectedId || busy" @click="select">
        Select topic and continue
      </button>
      <ConfirmButton
        label="Cancel task"
        question="Cancel this task?"
        confirm-label="Yes, cancel"
        :disabled="busy"
        @confirm="emit('decide', { action: 'cancel' })"
      />
    </div>

    <div class="field regenerate">
      <label class="field__label" for="topic-feedback">Not right? Ask for new topics</label>
      <textarea
        id="topic-feedback"
        v-model="feedback"
        class="textarea"
        maxlength="5000"
        placeholder="Optional direction, such as: focus on senior cats"
      />
      <div>
        <button type="button" class="button" :disabled="busy" @click="regenerate">Regenerate topics</button>
      </div>
    </div>

    <details v-if="earlier.length" class="small">
      <summary>Earlier suggestions ({{ earlier.length }})</summary>
      <ul class="earlier">
        <li v-for="topic in earlier" :key="topic.id">Batch {{ topic.batch_number }}: {{ topic.title }}</li>
      </ul>
    </details>
  </div>
</template>

<style scoped>
.topics {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}

.topic {
  display: flex;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
  cursor: pointer;
  transition:
    border-color 0.15s,
    background-color 0.15s;
}

.topic:hover {
  border-color: var(--border-strong);
}

.topic--selected {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.topic input {
  flex: none;
  align-self: flex-start;
  margin-top: 4px;
  accent-color: var(--accent);
}

.topic__body {
  display: grid;
  gap: 3px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.topic__title {
  line-height: 1.3;
}

.topic__type {
  justify-self: start;
  margin-top: 4px;
}

.regenerate {
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.earlier {
  margin: 6px 0 0;
  padding-left: 18px;
  color: var(--text-muted);
}
</style>

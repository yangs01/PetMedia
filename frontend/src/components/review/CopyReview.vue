<script setup>
import { computed, reactive, ref, watch } from 'vue'

import ConfirmButton from '@/components/common/ConfirmButton.vue'
import MasterCopyView from '@/components/results/MasterCopyView.vue'
import { listToText, textToList } from '@/utils/format'

import ValidationReport from './ValidationReport.vue'

const props = defineProps({
  version: { type: Object, required: true },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['decide'])

const mode = ref('review')
const feedback = ref('')
const draft = reactive({ title: '', opening_hook: '', body: '', takeaways: '', call_to_action: '' })

const hasErrors = computed(() => props.version.validation && !props.version.validation.passed)

watch(
  () => props.version.id,
  () => {
    mode.value = 'review'
    feedback.value = ''
  },
)

function startEditing() {
  const { content } = props.version
  Object.assign(draft, {
    title: content.title,
    opening_hook: content.opening_hook,
    body: content.body,
    takeaways: listToText(content.key_takeaways),
    call_to_action: content.call_to_action,
  })
  mode.value = 'edit'
}

function decide(action, extra = {}) {
  emit('decide', { action, current_version_id: props.version.id, ...extra })
}

function saveEdit() {
  decide('edit_and_approve', {
    edited_content: {
      ...props.version.content,
      title: draft.title,
      opening_hook: draft.opening_hook,
      body: draft.body,
      key_takeaways: textToList(draft.takeaways),
      call_to_action: draft.call_to_action,
    },
  })
}
</script>

<template>
  <div class="stack">
    <div class="row small muted">
      <span class="tag">Version {{ version.version_number }}</span>
      <span class="tag">{{ version.generation_source.replaceAll('_', ' ').toLowerCase() }}</span>
      <span>Provider: {{ version.provider }}</span>
    </div>
    <p v-if="version.revision_feedback" class="small muted">Written from: {{ version.revision_feedback }}</p>

    <ValidationReport :report="version.validation" />

    <template v-if="mode === 'review'">
      <MasterCopyView :content="version.content" />

      <div class="row actions">
        <button type="button" class="button button--primary" :disabled="busy" @click="decide('approve')">
          {{ hasErrors ? 'Approve despite problems' : 'Approve copy' }}
        </button>
        <button type="button" class="button" :disabled="busy" @click="startEditing">Edit and approve</button>
        <ConfirmButton
          label="Cancel task"
          question="Cancel this task?"
          confirm-label="Yes, cancel"
          :disabled="busy"
          @confirm="decide('cancel')"
        />
      </div>

      <div class="field revise">
        <label class="field__label" for="copy-feedback">Request a revision</label>
        <textarea
          id="copy-feedback"
          v-model="feedback"
          class="textarea"
          maxlength="5000"
          placeholder="What should change? For example: make it more natural and less promotional."
        />
        <div>
          <button
            type="button"
            class="button"
            :disabled="busy || !feedback.trim()"
            @click="decide('revise', { feedback: feedback.trim() })"
          >
            Send revision request
          </button>
        </div>
      </div>
    </template>

    <form v-else class="stack" @submit.prevent="saveEdit">
      <div class="field">
        <label class="field__label" for="edit-title">Title</label>
        <input id="edit-title" v-model="draft.title" class="input" required minlength="3" maxlength="200" />
      </div>
      <div class="field">
        <label class="field__label" for="edit-hook">Opening hook</label>
        <textarea id="edit-hook" v-model="draft.opening_hook" class="textarea" required minlength="3" />
      </div>
      <div class="field">
        <label class="field__label" for="edit-body">Body</label>
        <textarea id="edit-body" v-model="draft.body" class="textarea edit-body" required minlength="20" />
      </div>
      <div class="field">
        <label class="field__label" for="edit-takeaways">Key takeaways</label>
        <textarea id="edit-takeaways" v-model="draft.takeaways" class="textarea" required />
        <span class="field__hint">One per line, up to 10.</span>
      </div>
      <div class="field">
        <label class="field__label" for="edit-cta">Call to action</label>
        <input id="edit-cta" v-model="draft.call_to_action" class="input" required minlength="3" />
      </div>
      <p class="small muted">Saving creates a new version and approves it. The agent then adapts it for each channel.</p>
      <div class="row">
        <button type="submit" class="button button--primary" :disabled="busy">Save and approve</button>
        <button type="button" class="button" :disabled="busy" @click="mode = 'review'">Back</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.actions {
  padding-top: 4px;
}

.revise {
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.edit-body {
  min-height: 260px;
}
</style>

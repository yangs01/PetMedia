<script setup>
import { computed, ref, watch } from 'vue'

import { absoluteUrl } from '@/api/client'
import ConfirmButton from '@/components/common/ConfirmButton.vue'

const props = defineProps({
  task: { type: Object, required: true },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['decide'])

const chosen = ref([])
const feedback = ref('')

const slides = computed(() =>
  [...props.task.assets]
    .sort((a, b) => a.slide_number - b.slide_number)
    .map((asset) => ({
      asset,
      plan: props.task.carousel_plan?.find((slide) => slide.slide_number === asset.slide_number),
    })),
)
const hasMock = computed(() => props.task.assets.some((asset) => asset.is_mock))

watch(
  () => props.task.review_key,
  () => {
    chosen.value = []
    feedback.value = ''
  },
)

function decide(action, extra = {}) {
  emit('decide', { action, review_key: props.task.review_key, ...extra })
}

function regenerate() {
  decide('regenerate', { slide_numbers: chosen.value, feedback: feedback.value.trim() || null })
}
</script>

<template>
  <div class="stack">
    <p class="small muted">Tick any slides you want redone. The others stay as they are.</p>
    <p v-if="hasMock" class="small mock">These are mock images. They must not be published.</p>

    <div class="slides">
      <label v-for="{ asset, plan } in slides" :key="asset.id" class="slide" :class="{ 'slide--chosen': chosen.includes(asset.slide_number) }">
        <img
          :src="absoluteUrl(asset.url)"
          :alt="plan?.alt_text ?? `Slide ${asset.slide_number}`"
          :width="asset.width"
          :height="asset.height"
          class="slide__image"
          loading="lazy"
        />
        <span class="slide__caption small">
          <span class="check">
            <input v-model="chosen" type="checkbox" :value="asset.slide_number" />
            Slide {{ asset.slide_number }}
          </span>
          <span class="tag">v{{ asset.asset_version }}</span>
        </span>
        <span v-if="plan" class="small muted slide__text">{{ plan.headline }}</span>
      </label>
    </div>

    <div class="row">
      <button type="button" class="button button--primary" :disabled="busy" @click="decide('approve')">
        Approve all images
      </button>
      <ConfirmButton
        label="Cancel task"
        question="Cancel this task?"
        confirm-label="Yes, cancel"
        :disabled="busy"
        @confirm="decide('cancel')"
      />
    </div>

    <div class="field regenerate">
      <label class="field__label" for="image-feedback">Regenerate selected slides</label>
      <textarea
        id="image-feedback"
        v-model="feedback"
        class="textarea"
        maxlength="5000"
        placeholder="Optional art direction. This changes the background art, not the slide text."
      />
      <div>
        <button type="button" class="button" :disabled="busy || !chosen.length" @click="regenerate">
          Regenerate {{ chosen.length || '' }} {{ chosen.length === 1 ? 'slide' : 'slides' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slides {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px;
}

.slide {
  display: grid;
  align-content: start;
  gap: 6px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
  cursor: pointer;
  transition: border-color 0.15s;
}

.slide--chosen {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.slide__image {
  width: 100%;
  height: auto;
  border-radius: 4px;
  background: var(--surface-2);
}

.slide__caption {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.slide__text {
  overflow-wrap: anywhere;
}

.mock {
  color: var(--waiting);
  font-weight: 600;
}

.regenerate {
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
</style>

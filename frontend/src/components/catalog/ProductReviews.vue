<script setup>
import { onMounted, reactive, ref } from 'vue'

import { api } from '@/api/client'
import ErrorBanner from '@/components/common/ErrorBanner.vue'

const props = defineProps({
  productId: { type: String, required: true },
})

const reviews = ref([])
const error = ref('')
const saving = ref(false)
const blank = () => ({
  rating: 5,
  review_text: '',
  source: '',
  source_reference: '',
  permission_to_use: false,
  verified: false,
})
const form = reactive(blank())

async function load() {
  try {
    reviews.value = await api.listReviews(props.productId)
  } catch (problem) {
    error.value = problem.message
  }
}

async function submit() {
  saving.value = true
  error.value = ''
  try {
    await api.createReview(props.productId, {
      rating: Number(form.rating),
      review_text: form.review_text.trim(),
      source: form.source.trim(),
      source_reference: form.source_reference.trim(),
      permission_to_use: form.permission_to_use,
      verified_status: form.verified ? 'VERIFIED' : 'UNVERIFIED',
    })
    Object.assign(form, blank())
    await load()
  } catch (problem) {
    error.value = problem.message
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="stack">
    <h3>Customer reviews</h3>
    <p class="small muted">Only reviews with permission and a verified status reach the AI, when a task starts.</p>
    <ErrorBanner v-if="error" :message="error" />
    <ul v-if="reviews.length" class="reviews small">
      <li v-for="review in reviews" :key="review.id">
        <strong>{{ review.rating }}/5</strong>
        <span class="tag">{{ review.permission_to_use && review.verified_status === 'VERIFIED' ? 'Usable by AI' : 'Not used' }}</span>
        <div>{{ review.review_text }}</div>
        <div class="muted">{{ review.source }}: {{ review.source_reference }}</div>
      </li>
    </ul>
    <form class="form-grid" @submit.prevent="submit">
      <div class="field form-grid__wide">
        <label class="field__label" :for="`review-text-${productId}`">Review text</label>
        <textarea :id="`review-text-${productId}`" v-model="form.review_text" class="textarea" required />
      </div>
      <div class="field">
        <label class="field__label" :for="`review-source-${productId}`">Source</label>
        <input :id="`review-source-${productId}`" v-model="form.source" class="input" required placeholder="order_review" />
      </div>
      <div class="field">
        <label class="field__label" :for="`review-ref-${productId}`">Reference</label>
        <input :id="`review-ref-${productId}`" v-model="form.source_reference" class="input" required placeholder="ORDER-1001" />
      </div>
      <div class="field">
        <label class="field__label" :for="`review-rating-${productId}`">Rating</label>
        <select :id="`review-rating-${productId}`" v-model="form.rating" class="select">
          <option v-for="rating in [5, 4, 3, 2, 1]" :key="rating" :value="rating">{{ rating }}</option>
        </select>
      </div>
      <div class="review-checks">
        <label class="check"><input v-model="form.permission_to_use" type="checkbox" /> Permission to use</label>
        <label class="check"><input v-model="form.verified" type="checkbox" /> Verified</label>
      </div>
      <div class="form-grid__wide">
        <button type="submit" class="button" :disabled="saving">{{ saving ? 'Saving…' : 'Add review' }}</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.reviews {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow-wrap: anywhere;
}

.review-checks {
  display: grid;
  align-content: end;
  gap: 4px;
}
</style>

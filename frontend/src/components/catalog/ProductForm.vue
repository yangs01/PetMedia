<script setup>
import { reactive, ref } from 'vue'

import { api } from '@/api/client'
import ErrorBanner from '@/components/common/ErrorBanner.vue'
import { blankToNull, listToText, textToList } from '@/utils/format'

const props = defineProps({
  product: { type: Object, default: null },
})
const emit = defineEmits(['saved', 'close'])

const form = reactive({
  name: props.product?.name ?? '',
  category: props.product?.category ?? '',
  description: props.product?.description ?? '',
  sku: props.product?.sku ?? '',
  key_features: listToText(props.product?.key_features),
  materials: listToText(props.product?.materials),
  suitable_pets: listToText(props.product?.suitable_pets),
  usage_instructions: props.product?.usage_instructions ?? '',
  safety_notes: props.product?.safety_notes ?? '',
  price: props.product?.price ?? '',
  currency: props.product?.currency ?? '',
  product_url: props.product?.product_url ?? '',
})
const image = ref(null)
const saving = ref(false)
const error = ref('')

async function submit() {
  saving.value = true
  error.value = ''
  try {
    const body = {
      name: form.name.trim(),
      category: form.category.trim(),
      description: form.description.trim(),
      sku: blankToNull(form.sku),
      key_features: textToList(form.key_features),
      materials: textToList(form.materials),
      suitable_pets: textToList(form.suitable_pets),
      usage_instructions: blankToNull(form.usage_instructions),
      safety_notes: blankToNull(form.safety_notes),
      price: blankToNull(String(form.price)),
      currency: blankToNull(form.currency.toUpperCase()),
      product_url: blankToNull(form.product_url),
    }
    const saved = props.product ? await api.updateProduct(props.product.id, body) : await api.createProduct(body)
    if (image.value) await api.uploadProductImage(saved.id, image.value)
    emit('saved', saved)
  } catch (problem) {
    error.value = problem.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="stack" @submit.prevent="submit">
    <ErrorBanner v-if="error" :message="error" />
    <p class="small muted">The AI may only state facts found in these fields, so fill in what you want it to be able to say.</p>
    <div class="form-grid">
      <div class="field">
        <label class="field__label" for="product-name">Name</label>
        <input id="product-name" v-model="form.name" class="input" required maxlength="255" />
      </div>
      <div class="field">
        <label class="field__label" for="product-category">Category</label>
        <input id="product-category" v-model="form.category" class="input" required maxlength="100" />
      </div>
      <div class="field form-grid__wide">
        <label class="field__label" for="product-description">Description</label>
        <textarea id="product-description" v-model="form.description" class="textarea" required />
      </div>
      <div class="field">
        <label class="field__label" for="product-features">Key features</label>
        <textarea id="product-features" v-model="form.key_features" class="textarea" />
        <span class="field__hint">One per line</span>
      </div>
      <div class="field">
        <label class="field__label" for="product-materials">Materials</label>
        <textarea id="product-materials" v-model="form.materials" class="textarea" />
        <span class="field__hint">One per line</span>
      </div>
      <div class="field">
        <label class="field__label" for="product-pets">Suitable pets</label>
        <textarea id="product-pets" v-model="form.suitable_pets" class="textarea" />
        <span class="field__hint">One per line</span>
      </div>
      <div class="field">
        <label class="field__label" for="product-usage">Usage instructions</label>
        <textarea id="product-usage" v-model="form.usage_instructions" class="textarea" />
      </div>
      <div class="field form-grid__wide">
        <label class="field__label" for="product-safety">Safety notes</label>
        <textarea id="product-safety" v-model="form.safety_notes" class="textarea" />
      </div>
      <div class="field">
        <label class="field__label" for="product-sku">SKU</label>
        <input id="product-sku" v-model="form.sku" class="input" maxlength="100" />
      </div>
      <div class="field">
        <label class="field__label" for="product-url">Product URL</label>
        <input id="product-url" v-model="form.product_url" class="input" type="url" placeholder="https://" />
      </div>
      <div class="field">
        <label class="field__label" for="product-price">Price</label>
        <input id="product-price" v-model="form.price" class="input" type="number" min="0" step="0.01" />
      </div>
      <div class="field">
        <label class="field__label" for="product-currency">Currency</label>
        <input id="product-currency" v-model="form.currency" class="input" maxlength="3" placeholder="USD" />
      </div>
      <div class="field form-grid__wide">
        <label class="field__label" for="product-image">Add a photo, optional</label>
        <input
          id="product-image"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          class="input"
          @change="image = $event.target.files[0] ?? null"
        />
        <span class="field__hint">Without a photo, slides show no product. The system never invents one.</span>
      </div>
    </div>
    <div class="row">
      <button type="submit" class="button button--primary" :disabled="saving">
        {{ saving ? 'Saving…' : product ? 'Save product' : 'Create product' }}
      </button>
      <button type="button" class="button" :disabled="saving" @click="emit('close')">Close</button>
    </div>
  </form>
</template>

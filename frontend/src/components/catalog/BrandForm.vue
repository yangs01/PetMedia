<script setup>
import { reactive, ref } from 'vue'

import { api } from '@/api/client'
import ErrorBanner from '@/components/common/ErrorBanner.vue'
import { blankToNull, listToText, textToList } from '@/utils/format'

const props = defineProps({
  brand: { type: Object, default: null },
})
const emit = defineEmits(['saved', 'close'])

const form = reactive({
  brand_name: props.brand?.brand_name ?? '',
  brand_description: props.brand?.brand_description ?? '',
  brand_voice: listToText(props.brand?.brand_voice),
  target_audience: props.brand?.target_audience ?? '',
  target_markets: listToText(props.brand?.target_markets),
  marketing_goals: listToText(props.brand?.marketing_goals),
  preferred_cta: props.brand?.preferred_cta ?? '',
  prohibited_claims: listToText(props.brand?.prohibited_claims),
  style_guidelines: props.brand?.style_guidelines ?? '',
})
const logo = ref(null)
const saving = ref(false)
const error = ref('')

async function submit() {
  saving.value = true
  error.value = ''
  try {
    const body = {
      brand_name: form.brand_name.trim(),
      brand_description: blankToNull(form.brand_description),
      brand_voice: textToList(form.brand_voice),
      target_audience: blankToNull(form.target_audience),
      target_markets: textToList(form.target_markets),
      marketing_goals: textToList(form.marketing_goals),
      preferred_cta: blankToNull(form.preferred_cta),
      prohibited_claims: textToList(form.prohibited_claims),
      style_guidelines: blankToNull(form.style_guidelines),
    }
    let saved = props.brand ? await api.updateBrand(props.brand.id, body) : await api.createBrand(body)
    if (logo.value) saved = await api.uploadBrandLogo(saved.id, logo.value)
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
    <div class="form-grid">
      <div class="field form-grid__wide">
        <label class="field__label" for="brand-name">Brand name</label>
        <input id="brand-name" v-model="form.brand_name" class="input" required maxlength="255" />
      </div>
      <div class="field form-grid__wide">
        <label class="field__label" for="brand-description">Description</label>
        <textarea id="brand-description" v-model="form.brand_description" class="textarea" />
      </div>
      <div class="field">
        <label class="field__label" for="brand-voice">Brand voice</label>
        <textarea id="brand-voice" v-model="form.brand_voice" class="textarea" placeholder="Friendly&#10;Trustworthy" />
        <span class="field__hint">One per line</span>
      </div>
      <div class="field">
        <label class="field__label" for="brand-claims">Prohibited claims</label>
        <textarea id="brand-claims" v-model="form.prohibited_claims" class="textarea" placeholder="best in the world" />
        <span class="field__hint">One per line</span>
      </div>
      <div class="field">
        <label class="field__label" for="brand-markets">Target markets</label>
        <textarea id="brand-markets" v-model="form.target_markets" class="textarea" placeholder="US" />
        <span class="field__hint">One per line</span>
      </div>
      <div class="field">
        <label class="field__label" for="brand-goals">Marketing goals</label>
        <textarea id="brand-goals" v-model="form.marketing_goals" class="textarea" />
        <span class="field__hint">One per line</span>
      </div>
      <div class="field">
        <label class="field__label" for="brand-audience">Target audience</label>
        <input id="brand-audience" v-model="form.target_audience" class="input" />
      </div>
      <div class="field">
        <label class="field__label" for="brand-cta">Preferred call to action</label>
        <input id="brand-cta" v-model="form.preferred_cta" class="input" maxlength="255" />
      </div>
      <div class="field form-grid__wide">
        <label class="field__label" for="brand-style">Style guidelines</label>
        <textarea id="brand-style" v-model="form.style_guidelines" class="textarea" />
      </div>
      <div class="field form-grid__wide">
        <label class="field__label" for="brand-logo">Logo, optional</label>
        <input
          id="brand-logo"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          class="input"
          @change="logo = $event.target.files[0] ?? null"
        />
        <span class="field__hint">
          {{ brand?.has_logo ? 'A logo is saved. Choosing a file replaces it.' : 'Shown on slides. JPEG, PNG or WebP.' }}
        </span>
      </div>
    </div>
    <div class="row">
      <button type="submit" class="button button--primary" :disabled="saving">
        {{ saving ? 'Saving…' : brand ? 'Save brand' : 'Create brand' }}
      </button>
      <button type="button" class="button" :disabled="saving" @click="emit('close')">Close</button>
    </div>
  </form>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  label: { type: String, required: true },
  confirmLabel: { type: String, default: 'Yes, confirm' },
  question: { type: String, default: 'Are you sure?' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['confirm'])
const asking = ref(false)

function confirm() {
  asking.value = false
  emit('confirm')
}
</script>

<template>
  <span v-if="asking" class="row confirm fade-in">
    <span class="small">{{ question }}</span>
    <button type="button" class="button button--danger-solid button--small" :disabled="disabled" @click="confirm">
      {{ confirmLabel }}
    </button>
    <button type="button" class="button button--small" @click="asking = false">Keep</button>
  </span>
  <button v-else type="button" class="button button--danger" :disabled="disabled" @click="asking = true">
    {{ label }}
  </button>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  tone: { type: String, default: 'pending' },
})
</script>

<template>
  <span class="badge" :class="`badge--${tone}`">
    <span class="badge__dot" aria-hidden="true" />
    {{ label }}
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
}

.badge__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentcolor;
}

.badge--completed {
  background: var(--completed-soft);
  color: var(--completed);
}

.badge--running {
  background: var(--running-soft);
  color: var(--running);
}

.badge--running .badge__dot {
  animation: blink 1.2s ease-in-out infinite;
}

.badge--waiting {
  background: var(--waiting-soft);
  color: var(--waiting);
}

.badge--failed {
  background: var(--failed-soft);
  color: var(--failed);
}

.badge--queued {
  background: var(--queued-soft);
  color: var(--queued);
}

.badge--pending {
  background: var(--pending-soft);
  color: var(--pending);
}

.badge--cancelled {
  background: var(--cancelled-soft);
  color: var(--cancelled);
}

@keyframes blink {
  50% {
    opacity: 0.3;
  }
}
</style>

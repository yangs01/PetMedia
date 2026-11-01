<script setup>
defineProps({
  report: { type: Object, default: null },
})
</script>

<template>
  <div v-if="report" class="report small" :class="report.passed ? 'report--passed' : 'report--failed'">
    <strong>{{ report.passed ? 'Integrity checks passed' : 'Integrity checks found problems' }}</strong>
    <ul v-if="report.findings?.length" class="report__list">
      <li v-for="(finding, index) in report.findings" :key="index">
        <span class="tag">{{ finding.severity }}</span>
        {{ finding.message }}
        <q v-if="finding.excerpt" class="muted">{{ finding.excerpt }}</q>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.report {
  padding: 9px 12px;
  border-radius: var(--radius-small);
}

.report--passed {
  background: var(--completed-soft);
}

.report--failed {
  background: var(--failed-soft);
}

.report__list {
  display: grid;
  gap: 4px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}
</style>

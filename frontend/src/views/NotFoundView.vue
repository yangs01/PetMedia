<script setup>
import EmptyState from '@/components/common/EmptyState.vue'
</script>

<template>
  <div class="page page--narrow">
    <EmptyState title="Page not found">
      <RouterLink :to="{ name: 'dashboard' }" class="button">Back to dashboard</RouterLink>
    </EmptyState>
  </div>
</template>

<script setup>
import { onErrorCaptured, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import ErrorBanner from './components/common/ErrorBanner.vue'
import AppSidebar from './components/layout/AppSidebar.vue'

const route = useRoute()
const pageError = ref('')

// A bug in one page should say so, not leave a loading message on screen forever.
onErrorCaptured((error) => {
  console.error(error)
  pageError.value = error.message
  return false
})

watch(
  () => route.fullPath,
  () => {
    pageError.value = ''
  },
)

function reload() {
  window.location.reload()
}
</script>

<template>
  <div class="shell">
    <AppSidebar />
    <main class="shell__main">
      <div v-if="pageError" class="page">
        <ErrorBanner title="This page hit an error" :message="pageError" action-label="Reload" @action="reload" />
      </div>
      <RouterView v-else :key="route.fullPath" />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: 228px minmax(0, 1fr);
  min-height: 100dvh;
}

.shell__main {
  min-width: 0;
}

@media (max-width: 820px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

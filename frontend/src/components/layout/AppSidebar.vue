<script setup>
import { onMounted, ref } from 'vue'

import { api } from '@/api/client'
import { usePolling } from '@/composables/usePolling'

const health = ref(null)
const reachable = ref(null)

const links = [
  { to: { name: 'dashboard' }, label: 'Dashboard' },
  { to: { name: 'create' }, label: 'New content' },
  { to: { name: 'catalog' }, label: 'Brands & products' },
]

async function checkHealth() {
  try {
    health.value = await api.health()
    reachable.value = true
  } catch (error) {
    // /health/ready answers 503 with a body when a dependency is down, so 503 is still reachable.
    reachable.value = error.status === 503
    health.value = null
  }
}

const polling = usePolling(checkHealth, { interval: 15000 })
onMounted(polling.start)
</script>

<template>
  <aside class="sidebar">
    <RouterLink :to="{ name: 'dashboard' }" class="sidebar__brand">
      <span class="sidebar__logo" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="28" height="28">
          <rect width="32" height="32" rx="8" fill="#14b8a6" />
          <circle cx="16" cy="20" r="5" fill="#fff" />
          <circle cx="8.5" cy="13.5" r="2.5" fill="#fff" />
          <circle cx="13" cy="9" r="2.5" fill="#fff" />
          <circle cx="19" cy="9" r="2.5" fill="#fff" />
          <circle cx="23.5" cy="13.5" r="2.5" fill="#fff" />
        </svg>
      </span>
      PetMedia AI
    </RouterLink>

    <nav class="sidebar__nav" aria-label="Main">
      <RouterLink v-for="link in links" :key="link.label" :to="link.to" class="sidebar__link">
        {{ link.label }}
      </RouterLink>
    </nav>

    <div class="sidebar__footer small">
      <div class="sidebar__status">
        <span
          class="sidebar__dot"
          :class="{ 'is-ok': reachable && health, 'is-bad': reachable === false || (reachable && !health) }"
          aria-hidden="true"
        />
        <span v-if="reachable === null">Checking API…</span>
        <span v-else-if="health">API ready</span>
        <span v-else-if="reachable">API not ready</span>
        <span v-else>API unreachable</span>
      </div>
      <div v-if="health" class="sidebar__providers">
        <span>Text: {{ health.providers.llm }}</span>
        <span>Images: {{ health.providers.image }}</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  height: 100dvh;
  padding: 18px 12px;
  background: var(--sidebar);
  color: var(--sidebar-text);
}

.sidebar__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 8px 18px;
  color: #fff;
  font-size: 1.05rem;
  font-weight: 650;
  text-decoration: none;
}

.sidebar__nav {
  display: grid;
  gap: 3px;
}

.sidebar__link {
  padding: 8px 12px;
  border-radius: var(--radius-small);
  color: inherit;
  font-size: 0.93rem;
  font-weight: 500;
  text-decoration: none;
  transition: background-color 0.15s;
}

.sidebar__link:hover {
  background: var(--sidebar-active);
}

.sidebar__link.router-link-exact-active {
  background: var(--sidebar-active);
  color: #fff;
  box-shadow: inset 3px 0 0 #2dd4bf;
}

.sidebar__footer {
  margin-top: auto;
  padding: 10px 8px 2px;
  border-top: 1px solid rgb(255 255 255 / 12%);
}

.sidebar__status {
  display: flex;
  align-items: center;
  gap: 7px;
}

.sidebar__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
}

.sidebar__dot.is-ok {
  background: #4ade80;
}

.sidebar__dot.is-bad {
  background: #f87171;
}

.sidebar__providers {
  display: grid;
  margin-top: 4px;
  opacity: 0.8;
}

.sidebar a:focus-visible {
  outline-color: #2dd4bf;
}

@media (max-width: 820px) {
  .sidebar {
    position: static;
    flex-flow: row wrap;
    align-items: center;
    gap: 4px 12px;
    height: auto;
    padding: 10px 16px;
  }

  .sidebar__brand {
    padding: 0;
  }

  .sidebar__nav {
    display: flex;
    flex-wrap: wrap;
    order: 3;
    width: 100%;
  }

  .sidebar__link {
    padding: 5px 10px;
    font-size: 0.87rem;
  }

  .sidebar__footer {
    margin: 0 0 0 auto;
    padding: 0;
    border: 0;
  }

  .sidebar__providers {
    display: none;
  }
}
</style>

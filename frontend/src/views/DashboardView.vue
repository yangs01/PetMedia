<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '@/api/client'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorBanner from '@/components/common/ErrorBanner.vue'
import LoadingBlock from '@/components/common/LoadingBlock.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { usePolling } from '@/composables/usePolling'
import { formatDateTime, shortId } from '@/utils/format'
import { statusInfo } from '@/utils/status'

const router = useRouter()

const tasks = ref([])
const loading = ref(true)
const error = ref(null)
const filter = ref('all')
const brandNames = ref({})
// The task list has no names, so details are fetched once per change and kept here.
const details = reactive({})
const detailKeys = {}

const FILTERS = [
  { id: 'all', label: 'All tasks' },
  { id: 'review', label: 'Needs review' },
  { id: 'active', label: 'In progress' },
  { id: 'ready', label: 'Ready' },
  { id: 'failed', label: 'Failed' },
]

function countFor(id) {
  if (id === 'all') return tasks.value.length
  return tasks.value.filter((task) => statusInfo(task.status).group === id).length
}

const visibleTasks = computed(() =>
  filter.value === 'all' ? tasks.value : tasks.value.filter((task) => statusInfo(task.status).group === filter.value),
)

async function loadDetails(list) {
  const stale = list.filter((task) => detailKeys[task.id] !== task.updated_at)
  await Promise.allSettled(
    stale.slice(0, 12).map(async (task) => {
      details[task.id] = await api.getTask(task.id)
      detailKeys[task.id] = task.updated_at
    }),
  )
}

async function refresh() {
  try {
    const list = await api.listTasks()
    tasks.value = list
    error.value = null
    await loadDetails(list)
  } catch (problem) {
    error.value = problem
  } finally {
    loading.value = false
  }
}

const polling = usePolling(refresh, { interval: 2000 })

onMounted(async () => {
  polling.start()
  try {
    const brands = await api.listBrands()
    brandNames.value = Object.fromEntries(brands.map((brand) => [brand.id, brand.brand_name]))
  } catch {
    // Task rows still work without brand names, and the banner reports a real outage.
  }
})

function taskTitle(task) {
  return details[task.id]?.selected_topic?.title ?? `Task ${shortId(task.id)}`
}

function brandOf(task) {
  return brandNames.value[details[task.id]?.brand_id] ?? ''
}

function open(task) {
  router.push({ name: 'task', params: { id: task.id } })
}
</script>

<template>
  <div class="page">
    <header class="page__header">
      <div>
        <h1>Dashboard</h1>
        <p class="page__sub">Content tasks and where each one is in the workflow.</p>
      </div>
      <RouterLink :to="{ name: 'create' }" class="button button--primary">New content task</RouterLink>
    </header>

    <ErrorBanner
      v-if="error"
      class="dashboard-error"
      title="Could not load tasks"
      :message="error.message"
      action-label="Try again"
      @action="polling.trigger()"
    />

    <div class="tiles" role="group" aria-label="Filter tasks">
      <button
        v-for="item in FILTERS"
        :key="item.id"
        type="button"
        class="tile"
        :class="[`tile--${item.id}`, { 'tile--selected': filter === item.id }]"
        :aria-pressed="filter === item.id"
        @click="filter = item.id"
      >
        <span class="tile__count">{{ countFor(item.id) }}</span>
        <span class="tile__label">{{ item.label }}</span>
      </button>
    </div>

    <section class="card">
      <LoadingBlock v-if="loading" label="Loading tasks…" />

      <EmptyState
        v-else-if="!tasks.length && !error"
        title="No content tasks yet"
        message="Create a task to watch the agent propose topics, write copy and build a carousel."
      >
        <RouterLink :to="{ name: 'create' }" class="button button--primary">Create your first task</RouterLink>
      </EmptyState>

      <EmptyState v-else-if="!visibleTasks.length && !error" title="No tasks in this view" />

      <div v-else-if="visibleTasks.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">Task</th>
              <th scope="col">Status</th>
              <th scope="col">Market</th>
              <th scope="col">Channels</th>
              <th scope="col">Slides</th>
              <th scope="col">Created</th>
              <th scope="col">Last update</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in visibleTasks" :key="task.id" class="task-row" @click="open(task)">
              <td class="task-row__title">
                <RouterLink :to="{ name: 'task', params: { id: task.id } }" @click.stop>{{ taskTitle(task) }}</RouterLink>
                <div v-if="brandOf(task)" class="small muted">{{ brandOf(task) }}</div>
              </td>
              <td><StatusBadge :label="statusInfo(task.status).label" :tone="statusInfo(task.status).tone" /></td>
              <td>{{ task.target_market }}</td>
              <td>{{ task.channels.join(', ') }}</td>
              <td>{{ task.image_count }}</td>
              <td class="nowrap small muted">{{ formatDateTime(task.created_at) }}</td>
              <td class="nowrap small muted">{{ formatDateTime(task.updated_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dashboard-error {
  margin-bottom: 14px;
}

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.tile {
  --tile: var(--text);

  display: grid;
  justify-items: start;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s;
}

.tile:hover {
  border-color: var(--border-strong);
}

.tile--selected {
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent);
}

.tile--review {
  --tile: var(--waiting);
}

.tile--active {
  --tile: var(--running);
}

.tile--ready {
  --tile: var(--completed);
}

.tile--failed {
  --tile: var(--failed);
}

.tile__count {
  color: var(--tile);
  font-size: 1.5rem;
  font-weight: 650;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.tile__label {
  color: var(--text-muted);
  font-size: 0.84rem;
}

.task-row {
  cursor: pointer;
  transition: background-color 0.12s;
}

.task-row:hover {
  background: var(--surface-2);
}

.task-row__title {
  min-width: 220px;
  overflow-wrap: anywhere;
}

.task-row__title a {
  font-weight: 600;
  text-decoration: none;
}

.nowrap {
  white-space: nowrap;
}
</style>

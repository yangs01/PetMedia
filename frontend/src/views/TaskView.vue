<script setup>
import { computed, ref, watch } from 'vue'

import { api } from '@/api/client'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorBanner from '@/components/common/ErrorBanner.vue'
import LoadingBlock from '@/components/common/LoadingBlock.vue'
import ResultsPanel from '@/components/results/ResultsPanel.vue'
import ActivityFeed from '@/components/workflow/ActivityFeed.vue'
import NodeInspector from '@/components/workflow/NodeInspector.vue'
import TaskActionCard from '@/components/workflow/TaskActionCard.vue'
import TaskFacts from '@/components/workflow/TaskFacts.vue'
import WorkflowDiagram from '@/components/workflow/WorkflowDiagram.vue'
import { useTaskMonitor } from '@/composables/useTaskMonitor'
import { formatTime, shortId } from '@/utils/format'

const props = defineProps({ id: { type: String, required: true } })

const monitor = useTaskMonitor(props.id)
const { task, events, topics, versions, assetHistory, exportsList, workflow } = monitor
const { loading, notFound, connectionError, lastUpdated, idleSeconds } = monitor

const pickedNode = ref(null)
const busy = ref(false)
const actionError = ref('')
const brandName = ref('')
const productNames = ref([])

// The inspector follows the active node until the operator picks one to look at.
const selectedNode = computed(() => pickedNode.value ?? workflow.value?.activeNode ?? 'finalize_content')
const inspected = computed(() => workflow.value?.nodes[selectedNode.value])

const title = computed(() => task.value?.selected_topic?.title ?? `Task ${shortId(props.id)}`)

function selectNode(id) {
  pickedNode.value = pickedNode.value === id ? null : id
}

let namesLoaded = false
watch(task, async (detail) => {
  if (!detail || namesLoaded) return
  namesLoaded = true
  // Names are helpful but not essential, so a failure leaves the rest of the page working.
  const [brand, ...products] = await Promise.allSettled([
    api.getBrand(detail.brand_id),
    ...detail.product_ids.map((productId) => api.getProduct(productId)),
  ])
  brandName.value = brand.status === 'fulfilled' ? brand.value.brand_name : shortId(detail.brand_id)
  productNames.value = products.map((item, index) =>
    item.status === 'fulfilled' ? item.value.name : shortId(detail.product_ids[index]),
  )
})

async function run(action) {
  busy.value = true
  actionError.value = ''
  try {
    await action()
  } catch (error) {
    actionError.value = error.message
  } finally {
    // After a conflict the task has moved on, so a refresh shows the operator why.
    await monitor.refresh()
    busy.value = false
  }
}

const DECIDERS = { topic: api.decideTopic, copy: api.decideCopy, image: api.decideImages }

function decide(kind, body) {
  return run(() => DECIDERS[kind](props.id, body))
}
</script>

<template>
  <div class="page task-page">
    <LoadingBlock v-if="loading" label="Loading task…" />

    <EmptyState v-else-if="notFound" title="Task not found" message="It may have been created on a different database.">
      <RouterLink :to="{ name: 'dashboard' }" class="button">Back to dashboard</RouterLink>
    </EmptyState>

    <ErrorBanner
      v-else-if="!task"
      title="Could not load this task"
      :message="connectionError?.message ?? 'Unknown error.'"
      action-label="Try again"
      @action="monitor.refresh()"
    />

    <template v-else>
      <header class="page__header">
        <div class="task-heading">
          <RouterLink :to="{ name: 'dashboard' }" class="small back">Dashboard</RouterLink>
          <h1>{{ title }}</h1>
        </div>
        <div class="small muted live" aria-live="off">
          <span class="live__dot" :class="{ 'live__dot--off': connectionError }" aria-hidden="true" />
          {{ connectionError ? 'Reconnecting' : `Updated ${formatTime(lastUpdated)}` }}
        </div>
      </header>

      <ErrorBanner
        v-if="connectionError"
        class="connection"
        title="Lost contact with the API"
        :message="`${connectionError.message} The page shows the last known state and keeps retrying.`"
      />

      <div class="task-layout">
        <div class="task-layout__main">
          <section class="card">
            <div class="card__title"><h2>Agent workflow</h2></div>
            <WorkflowDiagram :workflow="workflow" :selected="selectedNode" @select="selectNode" />
          </section>

          <TaskActionCard
            :task="task"
            :workflow="workflow"
            :topics="topics"
            :busy="busy"
            :action-error="actionError"
            :idle-seconds="idleSeconds"
            @decide="decide"
            @retry="run(() => api.retryTask(id))"
            @cancel="run(() => api.cancelTask(id))"
          />

          <ResultsPanel :task="task" :versions="versions" :asset-history="assetHistory" :exports-list="exportsList" />
        </div>

        <aside class="task-layout__side" aria-label="Task details and activity">
          <NodeInspector v-if="inspected" :node="inspected" :is-active="selectedNode === workflow.activeNode" />
          <ActivityFeed :events="events" />
          <TaskFacts :task="task" :brand-name="brandName" :product-names="productNames" />
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.task-page {
  max-width: 1560px;
}

.task-heading {
  min-width: 0;
}

.back {
  text-decoration: none;
}

.back::before {
  content: '← ';
}

.live {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding-top: 4px;
  font-variant-numeric: tabular-nums;
}

.live__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--completed);
}

.live__dot--off {
  background: var(--failed);
}

.connection {
  margin-bottom: 14px;
}

.task-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  align-items: start;
  gap: 16px;
}

.task-layout__main,
.task-layout__side {
  min-width: 0;
}

.task-layout__side {
  position: sticky;
  top: 16px;
  max-height: calc(100dvh - 32px);
  overflow-y: auto;
}

@media (max-width: 1400px) {
  .task-layout {
    grid-template-columns: minmax(0, 1fr) 300px;
  }
}

/* The diagram text gets too small beside the panel below this width. */
@media (max-width: 1320px) {
  .task-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .task-layout__side {
    position: static;
    max-height: none;
    overflow: visible;
  }
}
</style>

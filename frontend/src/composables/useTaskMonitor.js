import { computed, ref, shallowRef } from 'vue'

import { api } from '@/api/client'
import { deriveWorkflow, isTerminal } from '@/workflow/state'

import { usePolling } from './usePolling'

const EVENT_PAGE_SIZE = 500

/** Follows one task from the real API, about every 2 seconds, until it finishes. */
export function useTaskMonitor(taskId) {
  const task = shallowRef(null)
  const events = ref([])
  const topics = shallowRef([])
  const versions = shallowRef([])
  const assetHistory = shallowRef([])
  const exportsList = shallowRef(null)
  const loading = ref(true)
  const notFound = ref(false)
  const connectionError = ref(null)
  const lastUpdated = ref(null)
  const lastChangeAt = ref(Date.now())
  const now = ref(Date.now())

  let lastEventId = 0
  let lastRecordsKey = null
  let lastChangeKey = null

  async function fetchNewEvents() {
    for (;;) {
      const page = await api.listEvents(taskId, lastEventId)
      if (page.length) {
        events.value.push(...page)
        lastEventId = page[page.length - 1].id
      }
      if (page.length < EVENT_PAGE_SIZE) return
    }
  }

  /** History lists change rarely, so they are fetched only when the task has moved on. */
  async function fetchRecordsIfChanged(detail) {
    const key = `${detail.version}|${detail.current_version?.id}|${detail.assets.length}`
    if (key === lastRecordsKey) return
    const [topicList, versionList, assetList, exportList] = await Promise.all([
      api.listTopics(taskId),
      api.listVersions(taskId),
      api.listAssetHistory(taskId),
      detail.status === 'READY' ? api.listExports(taskId) : null,
    ])
    topics.value = topicList
    versions.value = versionList
    assetHistory.value = assetList
    exportsList.value = exportList
    lastRecordsKey = key
  }

  function noteProgress(detail) {
    const key = [
      detail.version,
      detail.current_version?.id,
      detail.current_version?.validation ? 1 : 0,
      detail.channel_contents.length,
      detail.carousel_plan?.length,
      detail.assets.map((asset) => asset.id).join(),
      events.value.length,
    ].join('|')
    if (key !== lastChangeKey) {
      lastChangeKey = key
      lastChangeAt.value = Date.now()
    }
  }

  async function poll() {
    try {
      const detail = await api.getTask(taskId)
      await Promise.all([fetchNewEvents(), fetchRecordsIfChanged(detail)])
      task.value = detail
      noteProgress(detail)
      connectionError.value = null
      lastUpdated.value = Date.now()
      now.value = Date.now()
      if (isTerminal(detail.status)) polling.stop()
    } catch (error) {
      if (error.status === 404) {
        notFound.value = true
        polling.stop()
      } else {
        connectionError.value = error
        now.value = Date.now()
      }
    } finally {
      loading.value = false
    }
  }

  const polling = usePolling(poll, { interval: 2000 })
  polling.start()

  const workflow = computed(() =>
    task.value
      ? deriveWorkflow({
          task: task.value,
          events: events.value,
          topics: topics.value,
          versions: versions.value,
        })
      : null,
  )

  const idleSeconds = computed(() => Math.max(0, (now.value - lastChangeAt.value) / 1000))

  function refresh() {
    return polling.trigger()
  }

  return {
    task,
    events,
    topics,
    versions,
    assetHistory,
    exportsList,
    workflow,
    loading,
    notFound,
    connectionError,
    lastUpdated,
    idleSeconds,
    refresh,
  }
}

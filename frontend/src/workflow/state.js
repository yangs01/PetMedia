/**
 * Works out each graph node's state from what the backend actually reports.
 *
 * Task statuses are coarser than graph nodes: GENERATING_ASSETS, for example, spans
 * three nodes. So the active node is located from saved records, such as whether the
 * channel copy exists yet. Nothing here runs on a timer or guesses at progress.
 */
import { statusInfo } from '../utils/status.js'
import { NODE_ORDER, NODES } from './graph.js'

const TERMINAL = new Set(['READY', 'CANCELLED'])
const NON_PHASE = new Set(['CREATED', 'QUEUED', 'FAILED', 'READY', 'CANCELLED'])

export function isTerminal(status) {
  return TERMINAL.has(status)
}

function latestTopicBatch(topics) {
  const latest = Math.max(0, ...topics.map((topic) => topic.batch_number))
  return { number: latest, topics: topics.filter((topic) => topic.batch_number === latest) }
}

function copyNode(task) {
  const version = task.current_version
  if (!version) return 'generate_copy'
  if (version.approval_status === 'REVISION_REQUESTED') return 'generate_copy'
  if (!version.validation) return 'validate_copy'
  // A failing report during generation means a bounded automatic fix is being written.
  return version.validation.passed ? 'validate_copy' : 'generate_copy'
}

function approvedChannels(task) {
  return task.channel_contents.filter((item) => item.content_version_id === task.approved_version_id)
}

function assetsNode(task) {
  if (approvedChannels(task).length < task.channels.length) return 'adapt_channels'
  if (!task.carousel_plan) return 'plan_carousel'
  return 'generate_images'
}

function nodeForPhase(status, task) {
  switch (status) {
    case 'GENERATING_TOPICS':
      return 'generate_topics'
    case 'AWAITING_TOPIC_REVIEW':
      return 'review_topic'
    case 'GENERATING_COPY':
      return copyNode(task)
    case 'AWAITING_COPY_REVIEW':
      return 'review_copy'
    case 'GENERATING_ASSETS':
      return assetsNode(task)
    case 'AWAITING_IMAGE_REVIEW':
      return 'review_images'
    case 'FINALIZING':
      return 'finalize_content'
    default:
      return 'load_context'
  }
}

/** The last real phase before a failure, retry or cancellation. */
function lastPhase(events) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const from = events[index].from_status
    if (from && !NON_PHASE.has(from)) return from
  }
  return null
}

function locate(task, events) {
  const { status } = task
  if (status === 'FAILED') return { node: nodeForPhase(lastPhase(events), task), state: 'failed' }
  if (status === 'CANCELLED') return { node: nodeForPhase(lastPhase(events), task), state: 'cancelled' }
  if (status === 'QUEUED' || status === 'CREATED') {
    return { node: nodeForPhase(lastPhase(events), task), state: 'queued' }
  }
  const state = status.startsWith('AWAITING_') ? 'waiting' : 'running'
  return { node: nodeForPhase(status, task), state }
}

function unique(values) {
  return [...new Set(values.filter(Boolean))]
}

/** Image records store "provider:model". Text records store only the provider so far. */
function splitProvider(value) {
  const [provider, ...model] = value.split(':')
  return { provider, model: model.join(':') || null }
}

function modelInfo(values, modelNote) {
  const parsed = unique(values).map(splitProvider)
  return {
    provider: unique(parsed.map((item) => item.provider)).join(', ') || null,
    model: unique(parsed.map((item) => item.model)).join(', ') || null,
    modelNote,
  }
}

const TEXT_MODEL_NOTE = 'The backend does not record the model for text steps yet.'

function describeNodes({ task, topics, versions }) {
  const batch = latestTopicBatch(topics)
  const aiVersions = versions.filter((version) => version.generation_source !== 'HUMAN_EDIT')
  const latestAi = aiVersions[aiVersions.length - 1]
  const version = task.current_version
  const findings = version?.validation?.findings ?? []
  const channels = approvedChannels(task)
  const slideCount = task.carousel_plan?.length ?? 0
  const assets = task.assets

  return {
    load_context: { detail: 'Freezes the facts', engine: 'No model used' },
    generate_topics: {
      detail: batch.number ? `Batch ${batch.number} · ${batch.topics.length} topics` : 'Proposes topics',
      ...modelInfo(batch.topics.map((topic) => topic.provider), TEXT_MODEL_NOTE),
      promptVersion: null,
    },
    review_topic: {
      detail: task.selected_topic ? 'Topic selected' : 'Choose a topic',
      engine: 'Human decision',
    },
    generate_copy: {
      detail: latestAi ? `Latest AI draft: v${latestAi.version_number}` : 'Writes the draft',
      ...modelInfo(latestAi ? [latestAi.provider] : [], TEXT_MODEL_NOTE),
      promptVersion: latestAi?.prompt_version ?? null,
    },
    validate_copy: {
      detail: version?.validation
        ? version.validation.passed
          ? `Passed · ${findings.length} notes`
          : `${findings.filter((item) => item.severity === 'ERROR').length} errors found`
        : 'Checks claims',
      engine: 'Rule-based checks, no model used',
    },
    review_copy: {
      detail: task.approved_version_id ? 'Draft approved' : 'Approve or revise',
      engine: 'Human decision',
    },
    adapt_channels: {
      detail: channels.length
        ? `${channels.length} of ${task.channels.length} channels`
        : task.channels.join(' + '),
      ...modelInfo(channels.map((item) => item.provider), TEXT_MODEL_NOTE),
      perChannel: channels.map((item) => ({ platform: item.platform, provider: item.provider })),
    },
    plan_carousel: {
      detail: slideCount ? `${slideCount} slides planned` : `Plans ${task.image_count} slides`,
      provider: null,
      model: null,
      modelNote: 'The API does not report the provider for carousel plans yet.',
    },
    generate_images: {
      detail: assets.length ? `${assets.length} of ${task.image_count} slides` : 'Renders slides',
      ...modelInfo(assets.map((asset) => asset.provider), null),
    },
    review_images: {
      detail: assets.some((asset) => asset.status === 'APPROVED') ? 'Images approved' : 'Approve or redo',
      engine: 'Human decision',
    },
    finalize_content: { detail: 'Builds the package', engine: 'No model used' },
  }
}

const ENTERS_NODE = {
  GENERATING_TOPICS: 'generate_topics',
  AWAITING_TOPIC_REVIEW: 'review_topic',
  GENERATING_COPY: 'generate_copy',
  AWAITING_COPY_REVIEW: 'review_copy',
  AWAITING_IMAGE_REVIEW: 'review_images',
  FINALIZING: 'finalize_content',
  READY: 'finalize_content',
}

/** Which node a status event belongs to, using the node name the backend logged if any. */
function nodeForEvent(event) {
  if (event.to_status === 'GENERATING_ASSETS') {
    return event.from_status === 'AWAITING_IMAGE_REVIEW' ? 'generate_images' : (event.node_name ?? 'adapt_channels')
  }
  if (event.node_name && event.node_name !== 'review') return event.node_name
  return ENTERS_NODE[event.to_status] ?? null
}

function buildTimelines({ task, events, topics, versions }) {
  const timelines = Object.fromEntries(NODE_ORDER.map((id) => [id, []]))
  const add = (node, at, label) => timelines[node].push({ at, label })

  for (const event of events) {
    const node = nodeForEvent(event)
    if (node) add(node, event.created_at, `Status: ${statusInfo(event.to_status).label}`)
    if (event.from_status?.startsWith('AWAITING_') && ENTERS_NODE[event.from_status]) {
      add(ENTERS_NODE[event.from_status], event.created_at, `Decision received: ${statusInfo(event.to_status).label}`)
    }
  }
  const batches = new Map()
  for (const topic of topics) if (!batches.has(topic.batch_number)) batches.set(topic.batch_number, topic)
  for (const [number, topic] of batches) add('generate_topics', topic.created_at, `Saved topic batch ${number}`)
  for (const version of versions) {
    if (version.generation_source === 'HUMAN_EDIT') {
      add('review_copy', version.created_at, `Operator saved edited draft v${version.version_number}`)
    } else {
      add('generate_copy', version.created_at, `Saved draft v${version.version_number}`)
    }
  }
  for (const channel of task.channel_contents) add('adapt_channels', channel.created_at, `Saved ${channel.platform} copy`)
  for (const asset of task.assets) {
    add('generate_images', asset.created_at, `Saved slide ${asset.slide_number} v${asset.asset_version}`)
  }
  for (const list of Object.values(timelines)) list.sort((a, b) => a.at.localeCompare(b.at))
  return timelines
}

/** Automatic fixes store the validator's feedback, which always starts this way. */
function isAutoFix(version) {
  return Boolean(version.revision_feedback?.startsWith('Remove or rewrite these unsupported'))
}

export function deriveWorkflow({ task, events = [], topics = [], versions = [] }) {
  const descriptions = describeNodes({ task, topics, versions })
  const timelines = buildTimelines({ task, events, topics, versions })
  const located = task.status === 'READY' ? null : locate(task, events)
  const cursor = located ? NODE_ORDER.indexOf(located.node) : NODE_ORDER.length

  const nodes = {}
  NODES.forEach((node, index) => {
    let state = 'pending'
    if (index < cursor) state = 'completed'
    else if (index === cursor) state = located.state
    nodes[node.id] = { ...node, state, ...descriptions[node.id], timeline: timelines[node.id] }
  })

  const batch = latestTopicBatch(topics)
  const loops = {
    'review_topic>generate_topics': batch.number > 1,
    'validate_copy>generate_copy': versions.some((version) => isAutoFix(version)),
    'review_copy>generate_copy': versions.some(
      (version) => version.generation_source === 'AI_REVISION' && !isAutoFix(version),
    ),
    'review_images>generate_images': task.assets.some((asset) => asset.asset_version > 1),
  }

  return {
    nodes,
    activeNode: located?.node ?? null,
    activeState: located?.state ?? 'completed',
    loops,
  }
}

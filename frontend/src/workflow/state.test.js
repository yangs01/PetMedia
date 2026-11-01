import assert from 'node:assert/strict'
import { test } from 'node:test'

import { deriveWorkflow, isTerminal } from './state.js'

function makeTask(overrides = {}) {
  return {
    status: 'QUEUED',
    channels: ['instagram', 'facebook'],
    image_count: 4,
    selected_topic: null,
    current_version: null,
    approved_version_id: null,
    carousel_plan: null,
    assets: [],
    channel_contents: [],
    ...overrides,
  }
}

function event(from_status, to_status, extra = {}) {
  return {
    from_status,
    to_status,
    node_name: null,
    event_type: 'STATUS_CHANGED',
    created_at: '2026-11-01T10:00:00+00:00',
    ...extra,
  }
}

function states(workflow) {
  return Object.fromEntries(Object.values(workflow.nodes).map((node) => [node.id, node.state]))
}

const channel = (platform) => ({
  platform,
  content_version_id: 'v1',
  provider: 'openai',
  created_at: '2026-11-01T10:00:00+00:00',
})
const bothChannels = [channel('instagram'), channel('facebook')]

test('a new task is queued at the first node', () => {
  const flow = deriveWorkflow({ task: makeTask() })
  assert.equal(flow.activeNode, 'load_context')
  assert.equal(flow.nodes.load_context.state, 'queued')
  assert.equal(flow.nodes.generate_topics.state, 'pending')
})

test('topic generation completes load_context', () => {
  const flow = deriveWorkflow({ task: makeTask({ status: 'GENERATING_TOPICS' }) })
  assert.equal(flow.nodes.load_context.state, 'completed')
  assert.equal(flow.nodes.generate_topics.state, 'running')
})

test('a review pause waits for approval and leaves later nodes pending', () => {
  const flow = deriveWorkflow({ task: makeTask({ status: 'AWAITING_TOPIC_REVIEW' }) })
  assert.equal(flow.activeState, 'waiting')
  assert.equal(flow.nodes.review_topic.state, 'waiting')
  assert.equal(flow.nodes.generate_copy.state, 'pending')
})

test('copy generation distinguishes writing from validating using saved records', () => {
  const writing = deriveWorkflow({ task: makeTask({ status: 'GENERATING_COPY' }) })
  assert.equal(writing.activeNode, 'generate_copy')

  const version = { id: 'v1', approval_status: 'PENDING', validation: null, generation_source: 'AI_INITIAL' }
  const saved = deriveWorkflow({ task: makeTask({ status: 'GENERATING_COPY', current_version: version }) })
  assert.equal(saved.activeNode, 'validate_copy')

  const autofix = deriveWorkflow({
    task: makeTask({
      status: 'GENERATING_COPY',
      current_version: { ...version, validation: { passed: false, findings: [] } },
    }),
  })
  assert.equal(autofix.activeNode, 'generate_copy')

  const revising = deriveWorkflow({
    task: makeTask({
      status: 'GENERATING_COPY',
      current_version: {
        ...version,
        approval_status: 'REVISION_REQUESTED',
        validation: { passed: true, findings: [] },
      },
    }),
  })
  assert.equal(revising.activeNode, 'generate_copy')
})

test('asset generation is located from saved channels, plan and images', () => {
  const base = { status: 'GENERATING_ASSETS', approved_version_id: 'v1' }
  assert.equal(deriveWorkflow({ task: makeTask(base) }).activeNode, 'adapt_channels')
  assert.equal(
    deriveWorkflow({ task: makeTask({ ...base, channel_contents: [channel('instagram')] }) }).activeNode,
    'adapt_channels',
  )
  assert.equal(
    deriveWorkflow({ task: makeTask({ ...base, channel_contents: bothChannels }) }).activeNode,
    'plan_carousel',
  )
  assert.equal(
    deriveWorkflow({
      task: makeTask({ ...base, channel_contents: bothChannels, carousel_plan: [{}, {}, {}, {}] }),
    }).activeNode,
    'generate_images',
  )
})

test('channel copy for an older draft does not count', () => {
  const flow = deriveWorkflow({
    task: makeTask({
      status: 'GENERATING_ASSETS',
      approved_version_id: 'v2',
      channel_contents: bothChannels,
    }),
  })
  assert.equal(flow.activeNode, 'adapt_channels')
})

test('a failure is shown on the node that was running', () => {
  const task = makeTask({ status: 'FAILED', approved_version_id: 'v1', channel_contents: bothChannels })
  const events = [
    event(null, 'QUEUED'),
    event('QUEUED', 'GENERATING_TOPICS'),
    event('GENERATING_TOPICS', 'AWAITING_TOPIC_REVIEW'),
    event('AWAITING_TOPIC_REVIEW', 'GENERATING_COPY'),
    event('GENERATING_COPY', 'AWAITING_COPY_REVIEW'),
    event('AWAITING_COPY_REVIEW', 'GENERATING_ASSETS'),
    event('GENERATING_ASSETS', 'FAILED'),
  ]
  const flow = deriveWorkflow({ task, events })
  assert.equal(flow.activeNode, 'plan_carousel')
  assert.equal(flow.nodes.plan_carousel.state, 'failed')
  assert.equal(flow.nodes.adapt_channels.state, 'completed')
  assert.equal(flow.nodes.generate_images.state, 'pending')
})

test('a retried task is queued at the node that failed', () => {
  const events = [
    event('QUEUED', 'GENERATING_TOPICS'),
    event('GENERATING_TOPICS', 'FAILED'),
    event('FAILED', 'QUEUED'),
  ]
  const flow = deriveWorkflow({ task: makeTask({ status: 'QUEUED' }), events })
  assert.equal(flow.activeNode, 'generate_topics')
  assert.equal(flow.activeState, 'queued')
})

test('a cancelled review stays on its node, and later nodes never ran', () => {
  const events = [event('AWAITING_COPY_REVIEW', 'CANCELLED')]
  const flow = deriveWorkflow({ task: makeTask({ status: 'CANCELLED' }), events })
  assert.equal(flow.nodes.review_copy.state, 'cancelled')
  assert.equal(flow.nodes.generate_copy.state, 'completed')
  assert.equal(flow.nodes.adapt_channels.state, 'pending')
})

test('a cancelled queued task never left the first node', () => {
  const flow = deriveWorkflow({
    task: makeTask({ status: 'CANCELLED' }),
    events: [event(null, 'QUEUED'), event('QUEUED', 'CANCELLED')],
  })
  assert.equal(flow.nodes.load_context.state, 'cancelled')
})

test('a ready task has every node completed and none active', () => {
  const flow = deriveWorkflow({ task: makeTask({ status: 'READY' }) })
  assert.equal(flow.activeNode, null)
  assert.ok(Object.values(states(flow)).every((state) => state === 'completed'))
})

test('regenerating slides returns to generate_images', () => {
  const flow = deriveWorkflow({
    task: makeTask({
      status: 'GENERATING_ASSETS',
      approved_version_id: 'v1',
      channel_contents: bothChannels,
      carousel_plan: [{}, {}, {}, {}],
    }),
  })
  assert.equal(flow.nodes.generate_images.state, 'running')
  assert.equal(flow.nodes.review_images.state, 'pending')
})

test('provider data comes only from saved records, and missing data stays missing', () => {
  const asset = {
    id: 'a1',
    provider: 'openai_compatible:image-model',
    status: 'ACTIVE',
    slide_number: 1,
    asset_version: 1,
    created_at: '2026-11-01T10:00:00+00:00',
  }
  const flow = deriveWorkflow({
    task: makeTask({ status: 'AWAITING_IMAGE_REVIEW', assets: [asset], channel_contents: bothChannels, approved_version_id: 'v1' }),
    topics: [{ batch_number: 1, provider: 'deepseek', created_at: '2026-11-01T10:00:00+00:00' }],
  })
  assert.equal(flow.nodes.generate_topics.provider, 'deepseek')
  assert.equal(flow.nodes.generate_topics.model, null)
  assert.equal(flow.nodes.generate_images.provider, 'openai_compatible')
  assert.equal(flow.nodes.generate_images.model, 'image-model')
  assert.equal(flow.nodes.adapt_channels.provider, 'openai')
  assert.equal(flow.nodes.plan_carousel.provider, null)
  assert.ok(flow.nodes.plan_carousel.modelNote)
})

test('loop edges light up only when the loop really ran', () => {
  const quiet = deriveWorkflow({ task: makeTask({ status: 'GENERATING_TOPICS' }) })
  assert.ok(Object.values(quiet.loops).every((ran) => !ran))

  const looped = deriveWorkflow({
    task: makeTask({ status: 'AWAITING_COPY_REVIEW' }),
    topics: [
      { batch_number: 1, provider: 'mock', created_at: 'a' },
      { batch_number: 2, provider: 'mock', created_at: 'b' },
    ],
    versions: [
      { generation_source: 'AI_INITIAL', revision_feedback: null, version_number: 1, created_at: 'c', provider: 'mock' },
      { generation_source: 'AI_REVISION', revision_feedback: 'Warmer.', version_number: 2, created_at: 'd', provider: 'mock' },
    ],
  })
  assert.equal(looped.loops['review_topic>generate_topics'], true)
  assert.equal(looped.loops['review_copy>generate_copy'], true)
})

test('only READY and CANCELLED stop polling', () => {
  assert.ok(isTerminal('READY') && isTerminal('CANCELLED'))
  assert.ok(!isTerminal('FAILED') && !isTerminal('AWAITING_COPY_REVIEW'))
})

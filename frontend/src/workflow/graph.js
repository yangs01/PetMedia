/**
 * The ContentProductionGraph from backend/app/ai/graphs/content_graph.py.
 * Positions place nodes on the diagram; `kind` says what does the work at that node.
 */
export const NODES = [
  { id: 'load_context', title: 'Load Context', kind: 'system', row: 0, col: 0 },
  { id: 'generate_topics', title: 'Generate Topics', kind: 'ai', row: 0, col: 1 },
  { id: 'review_topic', title: 'Topic Review', kind: 'human', row: 0, col: 2 },
  { id: 'generate_copy', title: 'Generate Copy', kind: 'ai', row: 1, col: 0 },
  { id: 'validate_copy', title: 'Validate Copy', kind: 'system', row: 1, col: 1 },
  { id: 'review_copy', title: 'Copy Review', kind: 'human', row: 1, col: 2 },
  { id: 'adapt_channels', title: 'Adapt Channels', kind: 'ai', row: 1, col: 3 },
  { id: 'plan_carousel', title: 'Plan Carousel', kind: 'ai', row: 2, col: 0 },
  { id: 'generate_images', title: 'Generate Images', kind: 'ai', row: 2, col: 1 },
  { id: 'review_images', title: 'Image Review', kind: 'human', row: 2, col: 2 },
  { id: 'finalize_content', title: 'Finalize', kind: 'system', row: 2, col: 3 },
]

export const NODE_ORDER = NODES.map((node) => node.id)

export const FORWARD_EDGES = [
  ['load_context', 'generate_topics'],
  ['generate_topics', 'review_topic'],
  ['review_topic', 'generate_copy'],
  ['generate_copy', 'validate_copy'],
  ['validate_copy', 'review_copy'],
  ['review_copy', 'adapt_channels'],
  ['adapt_channels', 'plan_carousel'],
  ['plan_carousel', 'generate_images'],
  ['generate_images', 'review_images'],
  ['review_images', 'finalize_content'],
]

export const LOOP_EDGES = [
  { from: 'review_topic', to: 'generate_topics', label: 'regenerate', side: 'top' },
  { from: 'validate_copy', to: 'generate_copy', label: 'auto-fix', side: 'bottom' },
  { from: 'review_copy', to: 'generate_copy', label: 'revise', side: 'top' },
  { from: 'review_images', to: 'generate_images', label: 'regenerate', side: 'top' },
]

export const STATE_LABELS = {
  completed: 'Completed',
  running: 'Running',
  waiting: 'Needs approval',
  failed: 'Failed',
  queued: 'Queued',
  cancelled: 'Cancelled',
  pending: 'Pending',
}

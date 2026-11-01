/** How each backend task status appears in the interface. */
export const TASK_STATUS = {
  CREATED: { label: 'Created', tone: 'queued', group: 'active' },
  QUEUED: { label: 'Queued', tone: 'queued', group: 'active' },
  GENERATING_TOPICS: { label: 'Generating topics', tone: 'running', group: 'active' },
  AWAITING_TOPIC_REVIEW: { label: 'Topic review', tone: 'waiting', group: 'review' },
  GENERATING_COPY: { label: 'Generating copy', tone: 'running', group: 'active' },
  AWAITING_COPY_REVIEW: { label: 'Copy review', tone: 'waiting', group: 'review' },
  GENERATING_ASSETS: { label: 'Generating assets', tone: 'running', group: 'active' },
  AWAITING_IMAGE_REVIEW: { label: 'Image review', tone: 'waiting', group: 'review' },
  FINALIZING: { label: 'Finalizing', tone: 'running', group: 'active' },
  READY: { label: 'Ready', tone: 'completed', group: 'ready' },
  FAILED: { label: 'Failed', tone: 'failed', group: 'failed' },
  CANCELLED: { label: 'Cancelled', tone: 'cancelled', group: 'cancelled' },
}

export function statusInfo(status) {
  return TASK_STATUS[status] ?? { label: status, tone: 'pending', group: 'active' }
}

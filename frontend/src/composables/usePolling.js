import { onBeforeUnmount } from 'vue'

/**
 * Runs an async function repeatedly. The next run is scheduled only after the
 * current one finishes, so slow responses cannot overlap. Hidden tabs do not poll.
 */
export function usePolling(work, { interval = 2000 } = {}) {
  let timer = null
  let active = false
  let inFlight = null

  function schedule() {
    clearTimeout(timer)
    if (active) timer = setTimeout(tick, interval)
  }

  async function execute() {
    inFlight = Promise.resolve(work()).finally(() => {
      inFlight = null
    })
    await inFlight
    schedule()
  }

  function tick() {
    if (!active || inFlight) return
    if (document.hidden) {
      schedule()
      return
    }
    execute()
  }

  function onVisibilityChange() {
    if (!document.hidden) tick()
  }

  function start() {
    if (active) return
    active = true
    document.addEventListener('visibilitychange', onVisibilityChange)
    tick()
  }

  function stop() {
    active = false
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }

  /** Fetch now, after any run in progress, because that run may predate what just changed. */
  async function trigger() {
    clearTimeout(timer)
    if (inFlight) await inFlight
    if (!inFlight) await execute()
  }

  onBeforeUnmount(stop)
  return { start, stop, trigger }
}

import { onUnmounted, ref } from 'vue'

import { cursorOf, foldEvents } from '../api/fold'
import { fetchEvents, streamUrl } from '../api/observe'
import type { ObservationEvent } from '../api/types'

export type FeedMode = 'live' | 'polling' | 'offline'

const POLL_MS = 1500
// How many stream errors before the page stops trusting the push channel.  One
// is a reconnect; two in a row is a channel that is not coming back on its own.
const ERRORS_BEFORE_POLLING = 2

/**
 * The page's read of the observation feed: the push channel, with a polling
 * floor under it.
 *
 * The stream is the primary path.  It is an ``EventSource`` pointed at the
 * gateway, which adds the observer credential the browser does not hold and
 * passes ``Last-Event-ID`` through, so a browser reconnect resumes from the last
 * seq it rendered.  If the stream errors twice the page stops waiting on it and
 * polls ``/api/observe/events`` from that same seq: slower, but it cannot
 * silently show a screen that has stopped moving.
 *
 * Neither path advances anything: both are read-only GETs, and the gateway could
 * not carry anything else if they were not.
 */
export function useObserveStream() {
  const events = ref<ObservationEvent[]>([])
  const cursor = ref(0)
  const mode = ref<FeedMode>('offline')
  const pausedAt = ref<number | null>(null)

  let source: EventSource | null = null
  let timer: number | null = null
  let errors = 0

  function ingest(incoming: ObservationEvent[]) {
    events.value = foldEvents(events.value, incoming)
    cursor.value = cursorOf(events.value)
  }

  async function poll() {
    try {
      const page = await fetchEvents(cursor.value)
      ingest(page.events)
      mode.value = 'polling'
    } catch {
      mode.value = 'offline'
    }
  }

  function startPolling() {
    if (timer !== null) return
    timer = window.setInterval(poll, POLL_MS)
  }

  function stopPolling() {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  function connect() {
    source = new EventSource(streamUrl(0))
    source.onopen = () => {
      errors = 0
      mode.value = 'live'
      stopPolling()
    }
    source.onmessage = (message) => {
      try {
        ingest([JSON.parse(message.data) as ObservationEvent])
      } catch {
        // One unreadable frame is not the feed; the next one will do.
      }
    }
    source.onerror = () => {
      errors += 1
      mode.value = 'offline'
      if (errors >= ERRORS_BEFORE_POLLING && source) {
        source.close()
        source = null
        void poll()
        startPolling()
      }
    }
  }

  /** Stop the screen where it is, without stopping the read behind it. */
  function pause() {
    pausedAt.value = cursor.value
  }

  function resume() {
    pausedAt.value = null
  }

  connect()
  onUnmounted(() => {
    source?.close()
    stopPolling()
  })

  return { events, cursor, mode, pausedAt, pause, resume }
}

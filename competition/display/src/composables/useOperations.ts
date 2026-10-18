import { ref } from 'vue'

import { fetchOperation, fetchOperations } from '../api/observe'
import type { OperationRow, OperationSnapshot } from '../api/types'

/**
 * The committed operations, and the one the display is looking at.
 *
 * This is the polling half of the page: a list read on demand and a snapshot for
 * whichever operation was picked.  It is refreshed when the stream passes a
 * milestone, not on every step, so a long flow does not turn into a request storm.
 */
export function useOperations() {
  const rows = ref<OperationRow[]>([])
  const selected = ref<string | null>(null)
  const snapshot = ref<OperationSnapshot | null>(null)
  const error = ref('')

  async function refresh() {
    try {
      rows.value = await fetchOperations()
      error.value = ''
    } catch (exc) {
      error.value = String(exc)
    }
  }

  async function select(oid: string) {
    selected.value = oid
    try {
      snapshot.value = await fetchOperation(oid)
      error.value = ''
    } catch (exc) {
      error.value = String(exc)
    }
  }

  /** Re-read the list, and the open snapshot if there is one. */
  async function sync() {
    await refresh()
    if (selected.value) await select(selected.value)
  }

  void refresh()
  return { rows, selected, snapshot, error, refresh, select, sync }
}

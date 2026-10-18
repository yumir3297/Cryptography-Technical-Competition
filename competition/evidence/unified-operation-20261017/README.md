# Unified operation evidence (recovered delivery)

The current acceptance run is recovered-joint-01. Its actual result, duration and
scope are recorded in summary.json and joint-final.log. Source hashes cover the
same Python implementation before and after this run. The original 159 tests
retain their internal/optional V1 configurations; 37 new tests include framing
checks. Counts from separate suites or demos must not be added.

The earlier temporary workspace disappeared before durable delivery. Full old
raw traces, old failure snapshots and the earlier demo could not be recovered.
The local historical-output-excerpts.json held saved conversation excerpts; its public replacement records provenance only, without the mixed payload. Older narrative statements
that all old evidence was preserved are superseded by this notice. Full raw traces and mixed excerpts are retained in the original local delivery only. This GitHub view publishes redacted logs and result summaries.

The demo uses genuine synthetic lab signatures and actual MCP stdio / loopback
HTTP. Its offline verification checks exported signatures and references, not
the full current authorization graph. No runtime private keys or raw runtime
databases are exported. Historical clock attribution remains explicitly open.
manifest.json covers payload files other than itself and this README.

This is a sanitized publication view. public-demo-summary.json is explicitly not a signed bundle; the original local audit result is retained as a historical result. Re-run the supplied experiment to generate independent identities and evidence. manifest.json hashes the current sanitized files only.

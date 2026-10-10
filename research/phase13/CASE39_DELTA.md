# Phase 13 case-level delta

- `CORE-01`: added a three-profile process-separated experiment with actual persisted SQLite acceptance, C-clock claim, simulated tool result, settlement, restart redispatch rejection, read-only verifier and 9 transcript mutation rejections. Local candidate only, status stays `BLOCKED_FULL_CONFORMANCE`.
- `CORE-02` through `AUD-02D`: no new official completeness claim; statuses unchanged.

### Concrete architecture blocker confirmed

Recreating `HardenedSceneW` for `IND-DEMO-1` and `MED-DEMO-1` exposes private C controller signing key via `w.controller` and X actor signing key via `w.actors['X'].key`. The experiment deliberately does not conceal this. Closing CORE-01 requires a redesigned verifier-only W with independently generated C/E/X keys and external signing, not another wrapper around this fixture. See `phase13_report.json` for other unmet requirements.

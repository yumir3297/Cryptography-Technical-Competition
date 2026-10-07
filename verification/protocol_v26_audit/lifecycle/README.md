# v2.6-R1 lifecycle audit (read-only specification review)

Scope: `01_core_contract.md`, `02_pay1_profile.md`, `03_industrial_medical_profiles.md`, README and the recovery contract explicitly referenced by these documents. Trust C/X/W correctness and ordinary key custody. Do not treat EXEC-0's stated lack of external exactly-once execution as a defect. No product or protocol file was edited.

## L1 — A first delayed tool final has no specified recovery route (P2, specification gap / conditional liveness finding)

Locations: core lines 206, 208, 210, 212; PAY lines 224–232; industrial/medical lines 337, 347–353.

Trace, with relative seconds for clarity:

1. t=100: W legally claims a previously accepted pending dispatch and records its unique attempt. The tool has current trust key K1. All acceptance/claim guards were T.
2. t=101: the honest tool atomically records the frozen request's unique effect and a canonical SUCCEEDED final F, signed by K1, with iat=101 and exp=1001. Only the delivery to W fails. W has not yet confirmed or saved a trusted final.
3. t=1002: the network and W recover; read/query of the original attempt returns the original immutable F. Its signature and effect binding are valid, but the final's time is expired. First settlement cannot be T under the 900-second/current-authentication rules.
4. Alternatively, first delivery occurs at t=200 within F's interval, after C correctly rotates the current TOOL_TRUST mapping to K2. F has the wrong kid for the current mapping. The line-208 old-key exception only covers a final already confirmed and saved by W, which F is not.
5. The operation is started, so it cannot be safely cancelled, returned to pending, or re-executed. Its reserved resource, inflight and TaskFlight remain occupied. The tool knows the outcome; the protocol has no explicit way to admit that historical outcome for first settlement after these ordinary delays.

This is not a duplicate-effect trace. It is a gap in authenticated recovery of known tool facts. It is conditional because the contract may intend the tool to issue a fresh attestation when queried. That behavior, its authorization, and its equivalence to F are not specified. A correct implementation returning only its durable original final satisfies the written fixed-record contract yet cannot recover.

Suggested revision: define an immutable semantic final identity and a current authenticated query/re-attestation of that same original final; bind scope, attempt, frozen action, outcome, effect_id and no_late_effect. Specify that a refresh of time/key does not create a new effect or a second settlement. Alternatively define carefully authenticated historical first-final verification; simply trusting a timestamp and archived public key is insufficient when an old tool key may have been compromised. Add semantic cases for delayed first receipt and key rotation before first settlement.

## L2 — Equivalent final re-attestation is conflated with contradictory facts (P2 clarification, related to L1)

Locations: core line 210 versus industrial/medical line 351.

Core says any different final triggers HALTED. The scene appendix instead names a different effect_id, opposite outcome, or other established contradiction. Refreshing F with a later iat/exp, current key, or final_seq changes its RecordRef while preserving every effect fact. Under the core wording this is different and must HALT; under the scene wording it is not an established contradiction. Thus the natural recovery mechanism for L1 requires a normative decision before it can be implemented consistently.

Suggested revision: compare immutable effect facts for contradiction and separately validate current attestation identity/freshness. If instead finals must remain byte-immutable forever, explicitly declare delayed/rotated first-final settlement unrecoverable and align the recovery claims.

## B1 — Unsigned Acceptance after expiry or key loss is a declared boundary, not a new safety bug

Locations: core 142, 158, 197; `system_dev/docs/14_协议符合性补全合同.md` 98–102.

If W commits acceptance but crashes before the original signature is generated/saved, recovery must sign the frozen original core. Once the original key is revoked or unavailable, it cannot do so, and it cannot switch kid/core/ref. The referenced recovery contract explicitly disclaims guaranteed recovery in this case, so this is not counted as an undisclosed protocol vulnerability. R1 also requires signing-time validity; consequently even an otherwise valid long-lived key cannot fill an unsigned Acceptance after its frozen exp (at most 900 seconds). Because STATUS for an accepted operation must attach a verifiable original Acceptance, authenticated STATUS can remain unavailable too. This expiry-only extension should be called out alongside the declared key-loss boundary.

## Checks with no demonstrated counterexample

- New acceptance, nonce/Permit consumption, intent deduplication and resource reservations are one W transaction with range/empty-set conflict protection; concurrent same-intent permits do not yield a second acceptance under the stated W assumptions.
- Pending cancellation and dispatch claiming share one W order and CAS; a cancelled pending dispatch cannot also become started.
- Started unknowns retain reservations and prohibit re-dispatch. This is the declared EXEC-0 tradeoff, not an unknown-release bug.
- Permanent intent and key-revocation tombstones prevent ordinary version migration or A→B→A rollback from restoring consumed action rights.
- Industrial phase advance requires the same unit's settled cycle-1 INSPECT success, with a current AWAITING_REINSPECT row and CAS. Cycle 2 is the final automatic phase; source evidence and approvals must be rebuilt. No route/cycle retry bypass was established from the normative rules.

`model.py` isolates only the already-started final-admission guards relevant to L1. It is not a full protocol implementation, a cryptographic vector, or a proof of a deployed defect. Its output shows the recovery gap for one allowed interpretation in which tools return their original durable final. The claims above depend on the quoted specification, not on these model outputs alone.

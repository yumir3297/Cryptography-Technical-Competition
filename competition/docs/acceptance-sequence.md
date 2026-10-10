# P-01–P-03 industrial time and frozen receipt slice

2026-10-10, `COMP-APP-MIN-1.0` / `COMP-IND-TIME-1.0`. Source base:
`dbda1cac814306fddcdd508cd9e45b5b62551299`. This is a local implementation,
not evidence of remote adoption or three-profile delivery.

## Durable acceptance and receipt

`prepare(op)` validates genuine signed IND input and current W dependencies,
then stores a non-authorizing ticket. It consumes no permit, business nonce,
intent or reservation. Outer Action, AH, Basis, Assessment and every signed
Ctx must agree with current authenticated records; caller Ctx is not an oracle.

`challenge_accept(ticket)` returns a one-use 30-second application challenge.
H signs `['COMP-APP-ACCEPT-v1', claim]`; `accept(ticket, signer=None, proof=...)`
verifies the pinned H signature, current KEY/HOLDER/READER, current POLICY
readers and TASK holder. A ticket alone is insufficient. Retry uses a fresh
identity challenge and the original stored signed request. The original
CommitProof may be historical for retrieval, but grants and caller identity
must still be current. Identity challenges are separate from business proof
nonce consumption and roll back with a failed decision.

W opens `BEGIN IMMEDIATE`, checks a fresh ACCEPT_GUARD, builds the plan using
the original pure verifier, then samples again after signature work. This final
logical guard rechecks every relevant time window, including all required
READER grants. W locks serialize authenticated control revisions. The final
`lo` is accepted_at; it does not assert physical disk completion at that second.
SQLite COMMIT is the durability boundary. One transaction freezes COMMIT,
unsigned Acceptance Core and their Refs, records intent/permit/proof/session/
nonce consumption, scene/behavior/flight transitions and one reservation.

The committed Core has iat=accepted_at and exp=accepted_at+900. X reads only
that committed Core from the configured W through a read-only SQLite handle.
The signing RPC accepts operation_id and acceptance_ref, never arbitrary Core
bytes. W holds its serialized write guard across signing and receipt saving;
X checks actual current OS time, pinned key and committed current grants.
W additionally checks RECEIPT_SIGN_GUARD and RECEIPT_PUBLISH, age and reported
signature generation time, current X KEY/EXECUTOR and the unchanged original
receipt window. The RPC deadline is 1.5 seconds. Same-W revisions cannot
interleave in this guard. This proves the defined logical guard/publish behavior
under the trusted local-process model, not hardware signature-time isolation.

Signature failure, current X revocation or expired X grant leaves the original
acceptance and reservation as COMMITTED_RECEIPT_PENDING. Recovery signs only
the original Core with its original kid; COMMIT/Core/Refs/iat/exp are immutable.
Existing saved receipt is retransmitted verbatim. No second accept/reservation
is allowed. The actual runner exits with code 97 after SQLite COMMIT and before
signing/response; reopen and authenticated retry recover the original fact.
An ACK timeout is COMMIT_UNKNOWN at the client, never proof of rollback.

`claim` conservatively rejects pending receipts. Even with a saved receipt it
returns DISPATCH_NOT_IMPLEMENTED. No tool/outbox delivery is implemented by
this patch. Legacy prepare/finalize/claim/cancel/settle and initialization
mutation entrypoints are disabled on this adapter; source research remains intact.

## Time Provider and truth values

C signs actual advancing host wall/monotonic readings, profile/scope/operation/
stage/request Ref, provider_id=local-c, epoch=1, random process instance_id and
durable global source sequence. W pins C public key and current instance.
Packets from a previous process instance are U; new samples after restart
continue source sequence and honor W's durable lo floor. Epoch rotation,
host reboot monotonic continuity and independent time infrastructure are not
claimed. New epoch recovery requires a future explicit contract.

Maximum total age is 2 seconds, with a 25 ms drift margin: transport age must
be at most 1.975 seconds. C marks unhealthy if wall/monotonic divergence since
its process origin exceeds 12.5 ms. W advances the interval upper end by actual
monotonic age plus margin, requires width ≤2 seconds and updates the durable
floor using lo. Failed W transactions roll back sample consumption; reuse must
still pass current age, instance and event binding checks. A new sequence does
not make an old wall sample fresh. Client timestamps are never decision time.

T: iat≤lo and hi<exp. F: lo≥exp → EXPIRED. A straddled boundary, unhealthy,
stale/overwide/unavailable clock or unknown instance is U → CLOCK_UNKNOWN.
Bad signatures, replay, wrong event or rollback retain their exact error codes;
no such result produces new acceptance/reservation.

## Status and scope

`challenge_status(operation_id)` plus H signature over
`['COMP-APP-READ-v1', claim]` authenticate a one-use read. `status` checks
current KEY/READER, POLICY readers/window and TASK holder/window, then returns
one W snapshot with status_seq, frozen objects, receipt and receipt witnesses.
It does not sign a receipt, accept, reserve, claim or call a tool; only read
nonce and clock evidence advance. `_view`/snapshot are internal operator/test
inspection, not external authenticated routes. `complete_receipt` is a trusted
background recovery action, not a public caller identity substitute.

This is an application projection, not a complete original R2 signed STATUS
or Result attachment when Acceptance never legally formed. No HTTP/UI session
adapter, execute_once/query_attempt/settle/audit service, three-profile shared
W, Linux DAC isolation or long-term historical Observation is claimed. C/X are
separate subprocesses in Windows; trusted bootstrap sees keys and the same OS
user retains filesystem access. The clock assumes trusted single-host OS time.

## Reproduce and inspect

Run from the repository root with a writable TMP/TEMP if sandboxed:

```text
python -m unittest discover -s competition/tests -v
python -m competition.run_time_slice --output competition/evidence/time-slice-20261010-final
```

Exports contain genuine signed inputs, C time packets/public root, frozen
records/receipt, public W tables, counts, source digest and hashed manifest.
Private run keys stay in ignored `.runtime/`. Only named IND subcases are PASS;
the 21-group matrix and original 39 full-case obligations are not promoted.

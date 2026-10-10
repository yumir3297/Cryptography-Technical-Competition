# Phase12 — 39 official cases, scoped evidence index

Original expectations and case IDs are drawn from the pinned upstream manifest; status has not been promoted.

| Official ID | Profile | Formal status | Phase12 evidence |
|---|---|---|---|
| CORE-01 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-02 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-03 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-04 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-05 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-06 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-07 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-08 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-09 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-10 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-11 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-12 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-13 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-14 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-15 | ALL | BLOCKED_FULL_CONFORMANCE | `research/phase12/evidence/CORE-15.json` |
| CORE-16 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-17 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-18 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-19 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| CORE-20 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| PAY-01 | PAY-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| PAY-02 | PAY-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| PAY-03 | PAY-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| PAY-04 | PAY-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| PAY-05 | PAY-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| IND-01 | IND-DEMO-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| IND-02 | IND-DEMO-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| IND-03 | IND-DEMO-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| IND-04 | IND-DEMO-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| MED-01 | MED-DEMO-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| MED-02 | MED-DEMO-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| MED-03 | MED-DEMO-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| MED-04 | MED-DEMO-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| SC-01 | IND-DEMO-1,MED-DEMO-1 | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| SC-02 | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| AUD-02A | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| AUD-02B | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |
| AUD-02C | ALL | BLOCKED_FULL_CONFORMANCE | `research/phase12/evidence/AUD-02C.json` |
| AUD-02D | ALL | BLOCKED_FULL_CONFORMANCE | No new Phase12 facet (earlier evidence preserved) |

## CORE-15
Official scenario: pending取消与领取竞争、started后进程故障
Official expected: 一个转换获胜；未知不回pending、不重派

Current full-conformance blockers:
- Three-profile local serialized C-clocked CANCEL/CLAIM racing and subprocess crash-after-claim observed; distributed delivery vs external tool started/effect-unknown reconciliation unproven
- Globally operated W, independently governed C/E, transport lifecycle and exhaustive scheduler interleavings unverified

## AUD-02C
Official scenario: 账丢失/查不到原attempt，新工具ledger不同
Official expected: 未知保留预占；不得凭不存在签失败或用新账结算原账

Current full-conformance blockers:
- PAY prior ledger-free first settlement was reproducible; hardened PAY now verifies immutable original fact and origin, alongside IND/MED; real authenticated external ledger outage and recovery unproven
- Proof against forged negative final, across independent tool service restart and all official status/transport branches still missing

No local-scoped test, regardless of count, is an official PASS.

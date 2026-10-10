# ZJJ-CORE-2.6-R2 — 39项正式语义符合性验收：独立执行证据报告

**注意：这是39项对应的局部执行证据，不是39项官方完整通过。**

- 按用例独立运行：39 项
- 具有通过的局部见证：39 项
- 实际运行关联测试：110 次
- 官方完整符合性通过：0 项
- 官方清单原件：NOT_INSTALLED
- PAY Schema：EXACT_ORIGINAL_SCHEMA_LOADED
- IND Schema：MISSING
- MED Schema：MISSING

| 官方用例 | 当前局部测试 | 测试数 | 尚缺的重要条件 |
|---|---|---:|---|
| CORE-01 | PARTIAL_WITNESSES_PASS | 2 | verified original normative records for all profiles；full current typed dependency graph；all Result and response bindings |
| CORE-02 | PARTIAL_WITNESSES_PASS | 3 | HTTP route and audience matrix across all profiles；all message types and side-effect assertions |
| CORE-03 | PARTIAL_WITNESSES_PASS | 2 | complete independent RequiredDeps closure for IND/MED；complete certified control and transitive issuer graph |
| CORE-04 | PARTIAL_WITNESSES_PASS | 2 | cyclic reference graph rejection at full depth；typed Record/Envelope recursive graph with limits |
| CORE-05 | PARTIAL_WITNESSES_PASS | 3 | W protected range insert/delete and ABA in same transaction；all three profile ranges and historical epochs |
| CORE-06 | PARTIAL_WITNESSES_PASS | 2 | authenticated temporarily unavailable service case, U/DEFER；independent missing-object F/REJECT signed Result and zero effects |
| CORE-07 | PARTIAL_WITNESSES_PASS | 3 | same subject different kid role collision full-envelope case；all three profile signature authority matrix |
| CORE-08 | PARTIAL_WITNESSES_PASS | 2 | client ambiguous communication outcome protocol semantics；complete W all-record transactional snapshot |
| CORE-09 | PARTIAL_WITNESSES_PASS | 2 | inject actual post-commit signer failure and key-revocation recovery；restore archived original signing key witness and immutable bytes |
| CORE-10 | PARTIAL_WITNESSES_PASS | 3 | validly re-signed different historical Core challenge；full archived credential chain identity and certificate witness |
| CORE-11 | PARTIAL_WITNESSES_PASS | 3 | nonce and proof side-effect trace from full multi-profile W；issue/request ID idempotency and all distinct action variants |
| CORE-12 | PARTIAL_WITNESSES_PASS | 2 | eight distinct candidates racing shared resource；multi-process capacity and same-intent concurrency for all profiles |
| CORE-13 | PARTIAL_WITNESSES_PASS | 3 | merge legacy and guarded dispatch implementations; legacy revocation gap exists；authoritative trusted-time interval crossing and deterministic cancellation |
| CORE-14 | PARTIAL_WITNESSES_PASS | 3 | transactionally prove HALTED without partial release for all corruptions；interleaved legitimate behavior revisions with nondecreasing count |
| CORE-15 | PARTIAL_WITNESSES_PASS | 3 | true concurrent cancel-versus-claim interleaving；tool no-late-effect callback contract after crash |
| CORE-16 | PARTIAL_WITNESSES_PASS | 3 | full cross-profile integrated final ledger；signatures and registered external ledger continuity |
| CORE-17 | PARTIAL_WITNESSES_PASS | 2 | real holder key migration and current STATUS challenge；signed Result and old COMMIT proof across expiry |
| CORE-18 | PARTIAL_WITNESSES_PASS | 2 | v2.5 persisted intent migration to v2.6；tombstones retained after settled/cancelled operations |
| CORE-19 | PARTIAL_WITNESSES_PASS | 7 | remote C controller identity service and trusted nonce issuance not implemented；original governance audit and role issuance lifecycle not integrated |
| CORE-20 | PARTIAL_WITNESSES_PASS | 2 | both issuer and executor multi-key same-subject cases；service rotation reissue Policy and all downstream receipts |
| PAY-01 | PARTIAL_WITNESSES_PASS | 3 | official full current issuer/source identity and RoleGrant graph；complete three traces in official transport wrapper |
| PAY-02 | PARTIAL_WITNESSES_PASS | 6 | original authenticated History publication audit and trusted cutoff origin；full official-case transcript with all negative variants |
| PAY-03 | PARTIAL_WITNESSES_PASS | 4 | full execution under C-authenticated case snapshot and real signer；same source row verified at W acceptance |
| PAY-04 | PARTIAL_WITNESSES_PASS | 3 | all three Boolean hard-false variations；complete signed Result and read-only resource ledger |
| PAY-05 | PARTIAL_WITNESSES_PASS | 3 | original v2.5 issuer credential publication chain and migration witness；all rejected source types and removed-original-sig cases |
| IND-01 | PARTIAL_WITNESSES_PASS | 3 | full original IND Schema and controller key PoP；every profile role scope/reader and full source lineage |
| IND-02 | PARTIAL_WITNESSES_PASS | 2 | all independent package-dimension mismatches under authoritative C publication；official IND structural Schema validation |
| IND-03 | PARTIAL_WITNESSES_PASS | 2 | separate source revisions and external evidence updates；full atomic W scene-after witness and authentic dispatch claim |
| IND-04 | PARTIAL_WITNESSES_PASS | 4 | controller privilege is an in-process lab assumption rather than authenticated C certificate；R2 FinalFact signer is lab-pinned rather than certified external TOOL_TRUST + independent ledger |
| MED-01 | PARTIAL_WITNESSES_PASS | 3 | two same-subject/different-kid medical approvers；full med read authorizer and fixed role scope |
| MED-02 | PARTIAL_WITNESSES_PASS | 4 | attempt re-register group after prior final；official MED Schema and verified unique encounter lifecycle |
| MED-03 | PARTIAL_WITNESSES_PASS | 2 | authorized temporarily unavailable E authority U path；F/U reason signed Result and W noneffects |
| MED-04 | PARTIAL_WITNESSES_PASS | 2 | auditor cannot expose patient detail; redaction fields test；full authenticated reader identities and revocation race |
| SC-01 | PARTIAL_WITNESSES_PASS | 2 | exact 8-slot full-capacity test and 32-operation cumulative behavior test；trusted lo/hi 300-second T/F/U semantics |
| SC-02 | PARTIAL_WITNESSES_PASS | 3 | cross-profile signed CORE envelopes and path；official structures and W noneffects for each direction |
| AUD-02A | PARTIAL_WITNESSES_PASS | 2 | integrated R2 final into IND/MED W；audited C ledger mapping and tool real authorization |
| AUD-02B | PARTIAL_WITNESSES_PASS | 2 | controller rollover evidence, verified registered ledger continuity；integrated all three profiles |
| AUD-02C | PARTIAL_WITNESSES_PASS | 3 | actual external tool ledger unavailable/rollback semantics；independent status and resource ownership across restart |
| AUD-02D | PARTIAL_WITNESSES_PASS | 3 | all profiles and actual tool trust lineage；full response and escrow log in HALTED |

## 关键边界

1. `CORE-19` 的 C 控制主体是本地可信实验夹具，尚无真实跨服务认证。
2. `IND-04` 的工具最终事实使用实验室固定钥，而非外部受控 TOOL_TRUST 与完整账连续性。
3. `CORE-13` 在旧 FinalW 领取逻辑存在已复现的撤销安全缺口；受控 GuardedFinalW 是局部补丁，尚未全链路接入。
4. 原仓库官方 Schema 与用例清单需要与本 ZIP 合并后验证固定 Git blob，单元测试通过不自动满足官方要求。

运行方式：`python -m research.conformance39.run39 --upstream-root .`

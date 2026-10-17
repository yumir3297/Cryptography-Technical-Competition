# Independent review and corrective checks

Read-only reviewer: review_formal_resolver. Reviewed application library, fixtures and source boundaries.

1. A valid short PACKAGE could cause the constructed Assessment to exceed its source window (EXPIRED). Fix: intersect Task/Policy/IDENTITY/PACKAGE/E windows. Targeted red/green evidence: review-red.log, review-green.log.
2. Time elapsed after CommonGuard verification could make first-freeze use a stale event. Fix: refresh W current approval/credential windows inside the same first-freeze transaction. Targeted red/green evidence: review-red.log, review-green.log.
3. C genesis UNIT/BEHAVIOR after W acceptance could produce unusable new approval material. Existing W denied execution. Fix: SceneAuthorizationAdapter(WState(state), ...) for new resolution; retain cached material and exact frozen op for recovery. Targeted evidence: current-state-red.log, current-state-green.log.

Final read-only confirmation: WState wiring correct; regression covers new stale request rejection without mapping, immutable cached materials and original committed recovery. All window fixes retained. No application signing/automatic approval entry found. No new important issue identified.

These are application material freshness/availability and persistence validation issues, not evidence that R2 signature domains, COMMIT or EXEC-0 require redesign. Review is bounded to this branch and these tests.

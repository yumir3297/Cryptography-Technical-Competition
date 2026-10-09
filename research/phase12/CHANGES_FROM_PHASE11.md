# Phase11 → Phase12 delta (research)

- **NEW** `research/phase12/authority.py`: strict PAY first settlement requires matching independent ledger fact and origin; explicitly C-clocked serialized CANCEL for all three Profile adapters.
- **NEW** `research/phase12/crash_worker.py`: abrupt process termination immediately after committed W claim.
- **NEW** `research/phase12/test_phase12.py`: original fact loss & restoration, forged current signer fact mismatch, wrong-origin same-ID ledger, both transition orders, parallel claim/cancel, restart no re-dispatch.
- **NEW** `research/phase12/run_phase12.py`: six signed per-profile official-case *facet* traces and old-PAY differential regression.
- **MODIFIED** `research/formal39/run_formal39.py`: optional hash-verified Phase12 evidence attachment for CORE-15/AUD-02C, explicit missing obligations and no PASS upgrade.
- **NOT MODIFIED**: Phase11 source or evidence, original official 39 case manifest, all original PAY/IND/MED Schema resources.
- No remote GitHub push, physical tool effects, distributed W deployment or external root CA is represented by these experiments.

"""AADP / onedoor native budget adapter.

Runs the official ``onedoor.guardrail.decision`` API against a temporary SQLite
store.  It is intentionally a thin adapter: caps, effect accounting, decisions
and audit rows are produced by onedoor 0.12.1 itself.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from onedoor.guardrail import policy_loader
from onedoor.guardrail.decision import PermittedIntent, decide_and_reserve, report_result
from onedoor.guardrail.executor import EngineConfig
from onedoor.guardrail.models import (
    ActionRequest,
    Bounds,
    Caps,
    EffectPolicy,
    Outcome,
    Policy,
    Source,
    Tier,
)
from onedoor.store.db import Database

NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
CONFIG = EngineConfig(
    approval_ttl_seconds=3600,
    connector_timeout_seconds=1.0,
    tz=ZoneInfo("UTC"),
)


class AadpBudgetSession:
    """AADP native shared budget with an optional static carve-out."""

    def __init__(self, *, capacity: int, optional_quota: int):
        self.folder = tempfile.TemporaryDirectory(prefix="aadp-")
        self.db = Database(str(Path(self.folder.name) / "budget.sqlite"))
        self.db.init()
        self.conn = self.db.connect()
        self.capacity = capacity
        self.optional_quota = optional_quota
        for name, quota in (("bench.req", capacity), ("bench.opt", optional_quota)):
            policy_loader.upsert(
                self.conn,
                Policy(
                    action_type=name,
                    tier=Tier.AUTO_CAPPED,
                    dry_run=False,
                    compensating_command="bench.restore",
                    caps=Caps(eur_day=Decimal(quota)),
                    bounds=Bounds(strict_params=False),
                    effects=["bench_value"],
                ),
            )
        policy_loader.upsert(
            self.conn,
            Policy(
                action_type="bench.restore",
                tier=Tier.AUTO_CAPPED,
                dry_run=False,
                compensating_command="bench.restore",
                caps=Caps(eur_day=Decimal(capacity)),
                bounds=Bounds(strict_params=False),
            ),
        )
        policy_loader.upsert_effect(
            self.conn,
            EffectPolicy(
                effect="bench_value",
                caps=Caps(eur_day=Decimal(capacity), eur_month=Decimal(capacity * 100)),
            ),
        )

    def decide(self, kind: str, *, leave_pending: bool = False) -> dict:
        action_type = "bench.req" if kind == "R" else "bench.opt"
        request = ActionRequest(
            request_id=uuid.uuid4(),
            action_type=action_type,
            params={},
            source=Source.LLM,
            rationale="external benchmark",
            cost_eur=Decimal(1),
            created_at=NOW,
        )
        result = decide_and_reserve(request, conn=self.conn, config=CONFIG, now=NOW)
        if isinstance(result, PermittedIntent):
            if not leave_pending:
                report_result(
                    result,
                    conn=self.conn,
                    outcome=Outcome.SUCCESS,
                    payload=None,
                    error=None,
                    now=NOW,
                )
            return {
                "accepted": True,
                "code": "",
                "decision": "permit",
                "pending": leave_pending,
            }
        return {
            "accepted": False,
            "code": str(result.decision.reason_code),
            "decision": str(result.decision.decision),
        }

    def close(self):
        self.conn.close()
        self.folder.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

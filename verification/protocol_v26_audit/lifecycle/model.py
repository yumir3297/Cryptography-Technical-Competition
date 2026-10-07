"""Small normative guard witness, not a complete v2.6 implementation."""
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class Final:
    kid: str = "K1"
    iat: int = 101
    exp: int = 1001
    effect_id: str = "effect-1"


def first_settlement(final: Final, now: int, current_kid: str) -> dict:
    # All omitted cryptographic, authority, scope and action/attempt bindings
    # are assumed T. The tool and C/X/W are honest. No final was saved by W.
    reasons = []
    if not (final.iat <= now < final.exp):
        reasons.append("EXPIRED" if now >= final.exp else "CLOCK_UNKNOWN")
    if final.kid != current_kid:
        reasons.append("CURRENT_TOOL_TRUST_KID_MISMATCH")
    admitted = not reasons
    return {
        "now": now,
        "current_tool_kid": current_kid,
        "admitted": admitted,
        "reasons": reasons,
        "operation_status": "SUCCEEDED" if admitted else "EFFECT_UNKNOWN",
        "reserved": 0 if admitted else 1,
        "spent": 1 if admitted else 0,
        "flight_occupied": not admitted,
        "call_count": 1,
        "effect_count": 1,
    }


def main() -> None:
    final = Final()
    cases = {
        "on_time_original_mapping": first_settlement(final, 102, "K1"),
        "first_receipt_after_final_expiry": first_settlement(final, 1002, "K1"),
        "first_receipt_after_trust_key_rotation": first_settlement(final, 200, "K2"),
    }
    assert cases["on_time_original_mapping"]["admitted"]
    for name in ("first_receipt_after_final_expiry", "first_receipt_after_trust_key_rotation"):
        row = cases[name]
        assert not row["admitted"] and row["reserved"] == 1 and row["flight_occupied"]
        assert row["call_count"] == row["effect_count"] == 1
    print(json.dumps({"scope": "simplified_guard_witness_only", "cases": cases}, indent=2))


if __name__ == "__main__":
    main()

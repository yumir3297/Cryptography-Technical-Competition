"""Independent GoalFloor oracle.

No module in this file imports ``competition``.  It is a small arithmetic/state
machine used by the referee to decide whether a trace preserves the necessary
resource lower bound and whether a rejection was legitimate.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FloorOracle:
    capacity: int
    required_costs: list[int]
    optional_costs: list[int]
    enforce: bool
    spent: int = 0
    reserved: int = 0
    status: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.status:
            self.status = {f"r{i}": "OPEN" for i in range(len(self.required_costs))}

    def remaining(self, *, exclude: str | None = None) -> int:
        return sum(self.required_costs[int(name[1:])]
                   for name, state in self.status.items()
                   if state == "OPEN" and name != exclude)

    def pending(self) -> bool:
        return any(state == "PENDING" for state in self.status.values())

    def blocked(self) -> bool:
        return any(state == "BLOCKED" for state in self.status.values())

    def local_checks(self, kind: str, index: int) -> tuple[bool, str]:
        obligation = f"r{index}" if kind == "R" else None
        if self.enforce:
            if self.pending():
                return False, "GOAL_PENDING_UNKNOWN"
            if self.blocked():
                return False, "GOAL_BLOCKED"
            if obligation and self.status[obligation] != "OPEN":
                return False, "GOAL_ALREADY_COMMITTED"
        cost = self.required_costs[index] if kind == "R" else self.optional_costs[index]
        remaining = self.remaining(exclude=obligation)
        if self.spent + self.reserved + cost + (remaining if self.enforce else 0) > self.capacity:
            return False, "GOAL_CAPACITY_FLOOR" if self.enforce else "RESOURCE_EXHAUSTED"
        return True, ""

    def floor_feasible_after(self, accepted: list[dict]) -> bool:
        """Recompute the invariant from the accepted trace alone.

        A floor violation exists when the accepted cost already committed plus
        the still-required obligations exceeds capacity.
        """
        spent = 0
        reserved = 0
        status = {f"r{i}": "OPEN" for i in range(len(self.required_costs))}
        for row in accepted:
            kind, index = row["kind"], row["index"]
            cost = self.required_costs[index] if kind == "R" else self.optional_costs[index]
            if row["outcome"] == "SUCCESS":
                spent += cost
                if kind == "R":
                    status[f"r{index}"] = "DONE"
            else:
                reserved += cost
                if kind == "R":
                    status[f"r{index}"] = "PENDING"
        remaining = sum(self.required_costs[int(name[1:])]
                        for name, state in status.items() if state == "OPEN")
        return spent + reserved + remaining <= self.capacity

    def legitimate_optional_before(self, index: int) -> bool:
        cost = self.optional_costs[index]
        return (not self.pending() and not self.blocked() and
                self.spent + self.reserved + cost + self.remaining() <= self.capacity)

    def observe_accept(self, kind: str, index: int, *, outcome: str = "SUCCESS",
                       enforce: bool | None = None):
        use_enforce = self.enforce if enforce is None else enforce
        cost = self.required_costs[index] if kind == "R" else self.optional_costs[index]
        if outcome == "SUCCESS":
            self.spent += cost
            if kind == "R":
                self.status[f"r{index}"] = "DONE"
        elif outcome == "PENDING":
            self.reserved += cost
            if kind == "R":
                self.status[f"r{index}"] = "PENDING"
        elif outcome == "BLOCKED":
            if kind == "R":
                self.status[f"r{index}"] = "BLOCKED"
        return use_enforce


def floor_margin(capacity: int, spent: int, reserved: int, remaining_required: int) -> int:
    return capacity - (spent + reserved + remaining_required)

"""Deterministic sequence generator shared by AADP and ZJJ-CORE runs."""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SequenceSpec:
    sequence_id: int
    capacity: int
    required: int
    optional: int
    order: list[str]
    unknown_at: int | None

    def as_dict(self):
        return asdict(self)


def make_specs(count: int, *, seed: int = 20261125) -> list[SequenceSpec]:
    rng = random.Random(seed)
    specs = []
    for sequence_id in range(count):
        required = rng.randint(2, 4)
        optional = rng.randint(0, 5)
        headroom = rng.choice([0, 0, 1, 1, 2, 3])
        capacity = required + headroom
        tokens = [f"R{i}" for i in range(required)] + [f"O{i}" for i in range(optional)]
        rng.shuffle(tokens)
        unknown_at = None
        if rng.random() < 0.22:
            candidates = [i for i, token in enumerate(tokens) if token.startswith("R")]
            if candidates:
                unknown_at = rng.choice(candidates)
        specs.append(SequenceSpec(sequence_id, capacity, required, optional, tokens, unknown_at))
    return specs


def costs(spec: SequenceSpec) -> tuple[list[int], list[int]]:
    return [1] * spec.required, [1] * spec.optional

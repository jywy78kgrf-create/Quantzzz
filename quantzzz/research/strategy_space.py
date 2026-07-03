"""Parameterized strategy space: specs, parameter bounds, and (de)serialization."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParamDef:
    name: str
    kind: str                 # "int" | "float" | "choice"
    low: float = 0.0
    high: float = 1.0
    choices: tuple = ()
    step: float = 1.0         # mutation step (int/float)

    def sample(self, rng: random.Random):
        if self.kind == "choice":
            return rng.choice(self.choices)
        if self.kind == "int":
            return rng.randint(int(self.low), int(self.high))
        return round(rng.uniform(self.low, self.high), 4)

    def clamp(self, value):
        if self.kind == "choice":
            return value if value in self.choices else self.choices[0]
        value = max(self.low, min(self.high, value))
        return int(round(value)) if self.kind == "int" else round(float(value), 4)

    def mutate(self, value, rng: random.Random, temperature: float = 1.0):
        if self.kind == "choice":
            return rng.choice(self.choices)
        span = (self.high - self.low) * 0.2 * temperature
        delta = rng.uniform(-span, span)
        delta = max(self.step, abs(delta)) * (1 if delta >= 0 else -1)
        return self.clamp(value + delta)


@dataclass
class ParamSpace:
    family: str
    desk: str
    params: list[ParamDef] = field(default_factory=list)

    def random_params(self, rng: random.Random) -> dict:
        return {p.name: p.sample(rng) for p in self.params}

    def clamp(self, params: dict) -> dict:
        return {p.name: p.clamp(params.get(p.name, p.sample(random.Random(0))))
                for p in self.params}


@dataclass(frozen=True)
class StrategySpec:
    family: str
    desk: str
    params: dict

    def spec_hash(self) -> str:
        blob = json.dumps(
            {"family": self.family, "desk": self.desk, "params": self.params},
            sort_keys=True,
        )
        return hashlib.sha1(blob.encode()).hexdigest()[:16]

    def to_json(self) -> str:
        return json.dumps(self.params, sort_keys=True)

    @classmethod
    def from_row(cls, family: str, desk: str, params_json: str) -> "StrategySpec":
        return cls(family=family, desk=desk, params=json.loads(params_json))

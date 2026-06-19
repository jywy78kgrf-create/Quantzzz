"""HeuristicJudge — a transparent, deterministic, deliberately WEAK baseline.

This is a stand-in for the semantic layer so the harness has something to
measure against the LLM. It encodes generic, mandate-agnostic intuitions about
off-objective procurement intent (prepayment, net-new spend, off-contract line
items, instruction-injection in free text). It is intentionally simple and
keyword-driven: it WILL miss subtle cases and it WILL occasionally over-flag.
That weakness is the point — it sets the floor the LLM judge has to beat.

It does not, and must not, read the eval dataset or learn from it.
"""

from __future__ import annotations

import re

from ..models import JudgeResult, Transaction
from .base import SemanticJudge

# Generic off-objective signals. These are NOT mandate-specific policy (that
# lives in the gate config); they are crude intent cues a human reviewer might
# eyeball in a memo. Weak on purpose.
_OFF_OBJECTIVE_CUES = [
    r"\bnet[\- ]?new\b",
    r"\bbrand[\- ]?new\b",
    r"\bnew (project|product|initiative|team|cluster|tool|platform|vendor)\b",
    r"\bpilot\b",
    r"\bproof[\- ]of[\- ]concept\b",
    r"\bpoc\b",
    r"\b(offsite|off-site|retreat|team building)\b",
    r"\b(swag|gift card|gift cards|gifts?)\b",
    r"\b(conference|sponsor(ship)?|event|booth)\b",
    r"\b(laptop|laptops|hardware|monitor|furniture|equipment)\b",
    r"\b(consult(ing|ant)|professional services|statement of work|sow)\b",
    r"\b(marketing|advertis|campaign)\b",
    r"\b(travel|flight|hotel|aspen|vegas)\b",
    r"\b(perk|perks|wellness|lunch|catering)\b",
    r"\b(prepay|prepaid|paid in advance|annual upfront|multi[\- ]year|36 months|24 months|12 months upfront)\b",
    r"\b(credits? (gifted|for a partner)|partner)\b",
    r"\boff[\- ]contract\b",
]

# Prompt-/instruction-injection patterns in untrusted free text. Hitting one of
# these is itself grounds to escalate: trusted procurement memos do not tell the
# reviewer how to rule.
_INJECTION_CUES = [
    r"ignore (the|all|previous|prior).{0,20}(mandate|instruction|rule|policy)",
    r"disregard.{0,20}(mandate|policy|rule)",
    r"\bpre[\- ]approved\b",
    r"\b(system|assistant|user)\s*:",
    r"classify (this )?as (allowed|approved|ok)",
    r"do not (escalate|flag|deny)",
    r"mark (this )?as (safe|approved|allowed)",
    r"this is (just )?a (routine )?renewal",  # protests-too-much: claims renewal in text
    r"override",
    r"trust me",
]


class HeuristicJudge(SemanticJudge):
    name = "heuristic_v1"

    def __init__(self) -> None:
        self._off = [re.compile(p, re.IGNORECASE) for p in _OFF_OBJECTIVE_CUES]
        self._inj = [re.compile(p, re.IGNORECASE) for p in _INJECTION_CUES]

    def evaluate(self, objective: str, transaction: Transaction) -> JudgeResult:
        text = f"{transaction.memo}\n{transaction.description}"

        inj_hits = [p.pattern for p in self._inj if p.search(text)]
        if inj_hits:
            return JudgeResult(
                flag=True,
                reason=(
                    "free-text field contains instruction-injection / reviewer-"
                    f"steering language ({inj_hits[0]!r}); treating as untrusted and "
                    "escalating"
                ),
                judge_name=self.name,
            )

        off_hits = [p.pattern for p in self._off if p.search(text)]
        if off_hits:
            return JudgeResult(
                flag=True,
                reason=(
                    "memo/description suggests spend that may run against the "
                    f"mandate's run-rate purpose (matched {len(off_hits)} cue(s), "
                    f"e.g. {off_hits[0]!r})"
                ),
                judge_name=self.name,
            )

        return JudgeResult(
            flag=False,
            reason="no off-objective cue detected in free-text fields",
            judge_name=self.name,
        )

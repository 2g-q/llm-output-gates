"""ゲートを安い順に回し、最初に止まった時点で以降を省く。

なぜ安い順か:
  正規表現のゲートは 0 円、LLM を呼ぶゲートは 1 回ごとに費用と待ち時間がかかる。
  先に安いほうで落とせるなら、高いほうを呼ぶ理由がない。
  実運用では「安い順と書いてあるのに実装がそうなっていない」ことが起きたので、
  順序はコードの1か所(sorted by cost)だけで決まるようにしてある。

出力:
  実行のたびに manifest(JSON)を残す。どのゲートが何回動いて何回止めたかを
  後から数えられないと、「効いているのか」を誰も確かめられない。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from gates.base import Context, Gate, Verdict


@dataclass
class RunResult:
    blocked: bool
    verdicts: list[Verdict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "gates": [v.as_dict() for v in self.verdicts],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=indent)


def run(body: str, ctx: Context, gates: Sequence[Gate], stop_on_block: bool = True) -> RunResult:
    verdicts: list[Verdict] = []
    blocked = False
    for gate in sorted(gates, key=lambda g: g.cost):
        verdict = gate.check(body, ctx)
        verdicts.append(verdict)
        if verdict.blocked:
            blocked = True
            if stop_on_block:
                # 残りは動かさない。ただし「動かさなかった」ことを理由つきで残す。
                for skipped in sorted(gates, key=lambda g: g.cost):
                    if skipped.name in {v.gate for v in verdicts}:
                        continue
                    verdicts.append(
                        Verdict(gate=skipped.name, skipped=f"{gate.name} で止まったため")
                    )
                break
    return RunResult(blocked=blocked, verdicts=verdicts)

"""ゲートの共通の型。

設計の要点:
  - ゲートは「通す/止める」だけでなく、止めた理由を必ず構造で返す。
    理由が文字列だけだと、後から集計できず「効いているのか」が測れない。
  - 警告(warn)と停止(block)を分ける。全部止めると運用が回らず、
    全部警告にすると誰も読まない。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Protocol


@dataclass(frozen=True)
class Finding:
    """1件の指摘。"""

    code: str            # 機械で集計するための短い識別子
    message: str         # 人が読む説明
    quote: str = ""      # 本文中の該当箇所
    level: str = "block"  # "block" | "warn"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Verdict:
    """1ゲートの判定結果。"""

    gate: str
    findings: list[Finding] = field(default_factory=list)
    skipped: str | None = None   # 実行しなかった理由(空文字でなく理由を必ず入れる)

    @property
    def blocked(self) -> bool:
        return any(f.level == "block" for f in self.findings)

    @property
    def warned(self) -> bool:
        return any(f.level == "warn" for f in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "blocked": self.blocked,
            "skipped": self.skipped,
            "findings": [f.as_dict() for f in self.findings],
        }


class Gate(Protocol):
    """ゲートの実装が満たす形。

    cost: 実行の重さ。ランナーはこの順(安い順)に回し、
          止まった時点で以降を省く。正規表現のゲートは 0、LLM を呼ぶものは 100。
    """

    name: str
    cost: int

    def check(self, body: str, ctx: "Context") -> Verdict: ...


@dataclass
class Context:
    """ゲートに渡す材料。

    evidence: 事実の裏づけ。ここに無い数値は「出どころが無い」と判定する。
    incoming: 相手から届いた文面。ここから問いを抽出して回答漏れを見る。
    """

    evidence: dict[str, Any] = field(default_factory=dict)
    incoming: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

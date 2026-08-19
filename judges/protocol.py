"""判定器が満たす形。実装を差し替えられるようにここだけを見る。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Decision:
    """1件の判定。

    supported: 参照文書に基づいているか
    reason:    そう判断した理由(人が読む)
    """

    supported: bool
    reason: str


class LLMClient(Protocol):
    """1件を判定して Decision を返すもの。

    ここを Protocol にしてあるのは、テストで本物を呼ばないため。
    本番実装は llm_judge.AnthropicJudgeClient。
    """

    def judge(self, claim: str, sources: str) -> Decision: ...

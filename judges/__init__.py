"""機械判定で灰色になったものだけを LLM に聞く層。

設計の要点:
  - 候補を作るのは機械。LLM に聞くのは「この1件は根拠があるか」の yes/no だけ。
    候補まで LLM に作らせると、同じ入力でも列挙が揺れて判定が再現しなくなる。
  - 同じ入力なら呼ばない(キャッシュ)。判定に金額と待ち時間がかかる以上、
    同じことを二度聞かないのは仕様のうち。
  - LLM が落ちても機械判定の結果は残す。判定できなかったことを
    「問題なし」と取り違えないよう、理由つきで残す。
"""

from .llm_judge import LLMGroundingJudge
from .protocol import Decision, LLMClient

__all__ = ["Decision", "LLMClient", "LLMGroundingJudge"]

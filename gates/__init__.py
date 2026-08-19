"""LLM の出力を人に渡す前に止める検査ゲート。

各ゲートは Gate を実装し、Verdict を返す。
LLM を呼ばない決定的な判定に寄せてある(同じ入力なら同じ結果になること、
そして 0 円で何度でも回せることを優先した)。
"""
from .base import Gate, Verdict, Finding

__all__ = ["Gate", "Verdict", "Finding"]

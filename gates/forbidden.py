"""外に出してはいけない語が混ざっていないかを見る。

なぜ作ったか:
  生成器に渡した指示や内部の用語が、そのまま出力の末尾に紛れ込むことがある。
  「システムプロンプト」「社内メモ」の類は、1度でも相手に届くと取り返しがつかない。
  相手に届く経路の直前で、語の単位で止める。
"""

from __future__ import annotations

from .base import Context, Finding, Verdict

DEFAULT_FORBIDDEN = (
    "system prompt",
    "システムプロンプト",
    "プロンプト注入",
    "prompt injection",
    "社内メモ",
    "内部資料",
    "TODO:",
    "FIXME",
    "とりあえず",
)


class ForbiddenTermGate:
    """禁止語・内部語の混入を止める。"""

    name = "forbidden_terms"
    cost = 0

    def __init__(self, terms: tuple[str, ...] = DEFAULT_FORBIDDEN) -> None:
        self.terms = terms

    def check(self, body: str, ctx: Context) -> Verdict:
        low = body.lower()
        findings = [
            Finding(
                code="forbidden_term",
                message=f"外に出せない語「{t}」が含まれています",
                quote=t,
            )
            for t in self.terms
            if t.lower() in low
        ]
        return Verdict(gate=self.name, findings=findings)

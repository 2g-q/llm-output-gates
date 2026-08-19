"""「完了しました」「全件」の類を、証拠なしに言わせない。

なぜ作ったか:
  部分だけ確認して「完了しました」と報告し、相手が現物を見て食い違いに気づく——
  これが一番信用を失う。文面の断定は強いほど確認の裏づけが要る、という非対称がある。
  そこで、完了・網羅の語が出たら証拠の提示を必須にした。
"""

from __future__ import annotations

import re

from .base import Context, Finding, Verdict

_COMPLETION = (
    "完了しました",
    "完了いたしました",
    "対応済みです",
    "反映済みです",
    "すべて",
    "全件",
    "全て",
    "漏れなく",
    "完璧",
    "問題ありません",
    "クリーンな状態",
    "一つも",
    "1件も",
)
# 「〜していません」など否定に続く場合は主張の向きが逆なので拾わない
_NEGATED = re.compile(r"(ありません|おりません|できていません|していません)")


class CompletionClaimGate:
    """完了・網羅の主張に証拠が付いているかを見る。"""

    name = "completion_claims"
    cost = 0

    def check(self, body: str, ctx: Context) -> Verdict:
        has_evidence = bool(ctx.evidence)
        findings: list[Finding] = []
        for raw in re.split(r"(?<=[。\n])", body):
            s = raw.strip()
            if not s:
                continue
            hit = next((w for w in _COMPLETION if w in s), None)
            if not hit:
                continue
            if _NEGATED.search(s):
                continue
            if has_evidence:
                # 証拠があるなら通すが、何を根拠に断定したかは記録に残す
                findings.append(
                    Finding(
                        code="completion_claim_backed",
                        message=f"完了・網羅の主張「{hit}」を証拠つきで通しました",
                        quote=s,
                        level="warn",
                    )
                )
            else:
                findings.append(
                    Finding(
                        code="completion_claim_unbacked",
                        message=f"「{hit}」と断定していますが、確認の記録がありません",
                        quote=s,
                    )
                )
        return Verdict(gate=self.name, findings=findings)

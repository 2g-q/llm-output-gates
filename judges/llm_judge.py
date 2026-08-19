"""機械で灰色になった文だけを LLM に確認させるゲート。

使いどころ:
  gates/grounding.py は語の重なりで見るので、言い換えられていると
  「根拠が見当たらない」と出ることがある。全部止めると運用が回らないので、
  そこだけを LLM に yes/no で聞いて、no のものだけ止める。

なぜ候補を LLM に作らせないか:
  同じ入力でも列挙が揺れ、判定が再現しなくなるため。候補は機械で固定し、
  LLM の役割は「この1件は根拠があるか」に限定する。
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence

from gates.base import Context, Finding, Verdict
from gates.grounding import GroundingGate, Source, _sources_from

from .protocol import Decision, LLMClient

MODEL = "claude-opus-5"

SYSTEM = """あなたは、ある文が参照文書に基づいているかだけを判定します。

判定の基準:
- 参照文書に書かれている内容から読み取れるなら supported = true
- 参照文書に無い事実・数値・断定が含まれるなら supported = false
- 言い回しが違うだけで内容が同じなら supported = true

文章の善し悪し、丁寧さ、有用性は判定しません。根拠の有無だけを見ます。"""

# 応答の形を固定する。自由記述にすると、後段で正規表現の解析が必要になり、
# その解析が新しい壊れ方を持ち込む。
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "supported": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["supported", "reason"],
    "additionalProperties": False,
}


class AnthropicJudgeClient:
    """Anthropic の Messages API で1件ずつ判定する。

    判定は yes/no と短い理由だけなので、effort は low・max_tokens も小さく取る。
    深く考えさせる仕事ではなく、同じ基準で速く数を捌く仕事。
    """

    def __init__(self, model: str = MODEL, api_key: str | None = None) -> None:
        import anthropic  # 判定を使うときだけ要る依存にする

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model
        self._cache: dict[str, Decision] = {}

    def judge(self, claim: str, sources: str) -> Decision:
        key = hashlib.sha256(f"{self.model}\x00{claim}\x00{sources}".encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM,
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": DECISION_SCHEMA},
                },
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"参照文書:\n{sources}\n\n"
                            f"判定する文:\n{claim}\n\n"
                            "この文は参照文書に基づいていますか。"
                        ),
                    }
                ],
            )
        except self._anthropic.RateLimitError as e:
            raise JudgeUnavailable(f"利用上限に達しました: {e}") from e
        except self._anthropic.APIStatusError as e:
            raise JudgeUnavailable(f"判定できませんでした({e.status_code}): {e.message}") from e
        except self._anthropic.APIConnectionError as e:
            raise JudgeUnavailable(f"判定先へつながりませんでした: {e}") from e

        # 安全側に倒す: 拒否されたら「判定できなかった」として扱い、
        # 「根拠あり」に読み替えない。
        if response.stop_reason == "refusal":
            raise JudgeUnavailable("判定が拒否されました")

        import json

        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text)
        decision = Decision(supported=bool(data["supported"]), reason=str(data["reason"]))
        self._cache[key] = decision
        return decision


class JudgeUnavailable(RuntimeError):
    """判定そのものができなかった。『根拠あり』とは別物として扱う。"""


class LLMGroundingJudge:
    """機械が灰色にした文だけを LLM に確認させる。

    cost を高くしてあるのは、ランナーが安い順に回すため。
    先に安いゲートで落ちるなら、ここは呼ばれない。
    """

    name = "grounding_judge"
    cost = 100

    def __init__(self, client: LLMClient, threshold: float = 0.5) -> None:
        self.client = client
        self._machine = GroundingGate(threshold=threshold)

    def check(self, body: str, ctx: Context) -> Verdict:
        if os.environ.get("LLM_GATES_OFFLINE"):
            return Verdict(gate=self.name, skipped="LLM_GATES_OFFLINE が設定されている")

        sources = _sources_from(ctx)
        if not sources:
            return Verdict(gate=self.name, skipped="参照文書が渡されていない")

        machine = self._machine.check(body, ctx)
        gray = [f for f in machine.findings if f.code == "ungrounded"]
        if not gray:
            return Verdict(gate=self.name, skipped="機械判定で灰色になった文が無い")

        joined = _join(sources)
        findings: list[Finding] = []
        for f in gray:
            try:
                decision = self.client.judge(f.quote, joined)
            except JudgeUnavailable as e:
                # 判定できなかったことを残す。黙って通すと
                # 「見た」と「見ていない」が同じ結果になる。
                findings.append(
                    Finding(
                        code="judge_unavailable",
                        message=f"確認できませんでした({e})。機械判定では根拠が見当たりません",
                        quote=f.quote,
                        level="warn",
                    )
                )
                continue
            if not decision.supported:
                findings.append(
                    Finding(
                        code="ungrounded_confirmed",
                        message=f"参照文書に基づいていません: {decision.reason}",
                        quote=f.quote,
                    )
                )
        return Verdict(gate=self.name, findings=findings)


def _join(sources: Sequence[Source]) -> str:
    return "\n\n".join(f"[{s.id}] {s.text}" for s in sources)

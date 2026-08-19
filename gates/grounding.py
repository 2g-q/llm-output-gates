"""RAGの回答が、渡した参照文書に基づいているかを文単位で見る。

なぜ作ったか:
  検索して答えさせる作りでは、参照文書に無いことを回答に混ぜる形の誤りが出る。
  文としては自然で、引用番号まで付いていることがあるので、読み返しでは落ちない。
  「その文の内容が参照文書のどこかにあるか」は機械で測れるので、測って落とす。

判定:
  文ごとに、内容語(漢字・カタカナ・英数字の塊)が参照文書とどれだけ重なるかを見る。
  閾値未満なら「根拠が見当たらない」として名指しする。
  引用番号([1] など)が実在しない参照を指していれば、それも止める。

なぜ埋め込みや含意モデルを使わないか:
  0円・決定的・説明可能を優先した。なぜ落ちたかを人に説明できることを、
  精度より上に置いている(説明できない検査は、やがて誰も見なくなる)。
  精度が要る場面は judges/ の LLM 判定を重ねる。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .base import Context, Finding, Verdict

# 内容語だけを見る。助詞や語尾が一致しても「根拠がある」ことにはならない。
_CONTENT_WORD = re.compile(r"[一-龠]{2,}|[ァ-ヴー]{2,}|[A-Za-z][A-Za-z0-9_.-]{2,}|\d+(?:\.\d+)?")
_CITATION = re.compile(r"\[(\d{1,3})\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[。\.!?！？\n])")

# 短い文は語が少なく、重なり率がぶれやすい。指摘の質を保つため対象から外す。
MIN_CONTENT_WORDS = 3
# 重なりがこの割合を下回ったら「根拠が見当たらない」とする。
DEFAULT_THRESHOLD = 0.5


@dataclass(frozen=True)
class Source:
    """参照文書の1件。id は本文中の引用番号と対応させる。"""

    id: str
    text: str


def content_words(text: str) -> list[str]:
    return _CONTENT_WORD.findall(text)


def sentences(text: str) -> Iterable[str]:
    for part in _SENTENCE_SPLIT.split(text):
        s = part.strip()
        if s:
            yield s


def _coverage(sentence: str, source_words: set[str]) -> tuple[float, list[str]]:
    """文の内容語が参照側にどれだけあるか。(割合, 見つからなかった語)"""
    words = content_words(sentence)
    if not words:
        return 1.0, []
    missing = [w for w in words if w not in source_words]
    return (len(words) - len(missing)) / len(words), missing


class GroundingGate:
    """回答の各文が参照文書に基づいているかを見る。"""

    name = "grounding"
    cost = 0

    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold

    def check(self, body: str, ctx: Context) -> Verdict:
        sources = _sources_from(ctx)
        if not sources:
            return Verdict(gate=self.name, skipped="参照文書が渡されていない")

        source_words: set[str] = set()
        for s in sources:
            source_words.update(content_words(s.text))
        known_ids = {s.id for s in sources}

        findings: list[Finding] = []
        for sentence in sentences(body):
            # 引用番号が実在しない参照を指していないか
            for num in _CITATION.findall(sentence):
                if num not in known_ids:
                    findings.append(
                        Finding(
                            code="unknown_citation",
                            message=f"引用[{num}]に対応する参照文書がありません",
                            quote=sentence,
                        )
                    )

            words = content_words(sentence)
            if len(words) < MIN_CONTENT_WORDS:
                continue
            ratio, missing = _coverage(sentence, source_words)
            if ratio < self.threshold:
                findings.append(
                    Finding(
                        code="ungrounded",
                        message=(
                            f"参照文書に見当たらない内容です"
                            f"(一致 {ratio:.0%}・見当たらない語: {'・'.join(missing[:4])})"
                        ),
                        quote=sentence,
                    )
                )
        return Verdict(gate=self.name, findings=findings)


def _sources_from(ctx: Context) -> Sequence[Source]:
    """ctx.extra["sources"] から参照文書を取り出す。

    渡し方は2通り認める(呼び出し側の都合に合わせるため)。
      - Source のリスト
      - {"id": ..., "text": ...} のリスト
    """
    raw = ctx.extra.get("sources") or []
    out: list[Source] = []
    for i, item in enumerate(raw, start=1):
        if isinstance(item, Source):
            out.append(item)
        elif isinstance(item, dict):
            out.append(Source(id=str(item.get("id", i)), text=str(item.get("text", ""))))
        else:
            out.append(Source(id=str(i), text=str(item)))
    return out

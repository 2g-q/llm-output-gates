"""出力に現れる数値のうち、根拠に無いものを名指しする。

なぜ作ったか:
  LLM に文面を書かせると、数値が最もらしく混ざる。「12件対応しました」「約40%改善」。
  文体は自然なので人のレビューをすり抜ける。数値だけは機械で照合できるので、
  照合できないものは出さない、という線を引いた。

範囲:
  「その数値の出どころが証拠の中にあるか」までを見る。証拠自体の正しさは見ない。
  証拠が誤っていれば、その誤りごと通る。ここを混同すると「検査したのに間違っていた」
  という失望につながるので、README にも同じ但し書きを書いてある。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .base import Context, Finding, Verdict

# 桁区切り・小数・全角に対応する。日付や時刻は別の意味なので拾わない。
_NUMBER_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\d.,])")
_FULLWIDTH = str.maketrans("０１２３４５６７８９．，％", "0123456789.,%")

# 数値として扱わない文脈。日付・時刻・電話番号・バージョン・箇条書きの番号。
_SKIP_CONTEXT = (
    re.compile(r"\d+\s*[年月日]"),
    re.compile(r"\d+\s*[:：]\s*\d+"),
    re.compile(r"^\s*\d+[.)]\s"),
    re.compile(r"v?\d+\.\d+\.\d+"),
)


def _normalize(raw: str) -> str:
    return raw.translate(_FULLWIDTH).replace(",", "")


def _evidence_numbers(evidence: Any) -> set[str]:
    """証拠のあらゆる階層から数値を集める。

    証拠は JSON でもテキストでも渡ってくる。構造を決め打ちすると、
    形が少し違うだけで「根拠なし」と誤判定するので、全部を文字列にして拾う。
    """
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple, set)):
            for v in node:
                walk(v)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            found.add(_normalize(str(node)))
        elif node is not None:
            for m in _NUMBER_RE.finditer(str(node).translate(_FULLWIDTH)):
                found.add(_normalize(m.group(1)))

    walk(evidence)
    return found


def _sentences(body: str) -> Iterable[str]:
    for part in re.split(r"(?<=[。\n])", body):
        s = part.strip()
        if s:
            yield s


class NumberClaimGate:
    """本文の数値が証拠に無ければ止める。"""

    name = "number_claims"
    cost = 0

    def __init__(self, declared: dict[str, str] | None = None) -> None:
        # declared: {"2000": "1日の読み取り上限として自分で決めた値"}
        # 逃げ道は用意するが、理由を必須にして記録に残す。黙って解除させない。
        self.declared = declared or {}

    def check(self, body: str, ctx: Context) -> Verdict:
        known = _evidence_numbers(ctx.evidence) | set(self.declared)
        findings: list[Finding] = []
        seen: set[str] = set()

        for sentence in _sentences(body):
            if any(rx.search(sentence) for rx in _SKIP_CONTEXT):
                continue
            for m in _NUMBER_RE.finditer(sentence.translate(_FULLWIDTH)):
                value = _normalize(m.group(1))
                if value in known or value in seen:
                    continue
                # 0 と 1 は「ありません」「1点だけ」のような言い回しで頻出し、
                # 証拠に無くても誤りとは限らない。ここを止めると誤爆で信用を失う。
                if value in {"0", "1"}:
                    continue
                seen.add(value)
                findings.append(
                    Finding(
                        code="unbacked_number",
                        message=f"「{value}」の出どころが証拠にありません",
                        quote=sentence,
                    )
                )
        return Verdict(gate=self.name, findings=findings)

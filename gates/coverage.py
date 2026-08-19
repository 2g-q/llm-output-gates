"""相手の問いを抽出し、答えていないものを名指しする。

なぜ作ったか:
  返信の不合格でいちばん多いのは、文体でも事実誤認でもなく「聞かれたことに答えていない」。
  相手の文面から問いを決定的に抜き出し、返信に対応する語があるかを見る。

なぜ LLM に問いを作らせないか:
  同じ入力でも抽出が揺れて、判定が再現しなくなる。候補集合は正規表現で固定し、
  LLM を併用する場合も「この問いに答えているか」の yes/no だけを聞く形にする。
"""
from __future__ import annotations

import re
from .base import Context, Finding, Verdict

_QUESTION_END = re.compile(r"(でしょうか|ですか|ますか|かどうか|いかがでしょう)[。\.？\?]?\s*$")
_REQUEST = re.compile(r"(いただけますと幸いです|いただけますでしょうか|お願いいたします|ご教示|ご確認ください)")
# 締めの定型は依頼ではない。ここを拾うと毎回ノイズが出て誰も見なくなる。
_CLOSING = re.compile(
    r"^(何卒|よろしくお願い|引き続き|ご検討のほど|お忙しいところ|ご確認のほどよろしく).{0,24}$"
)
# 「何件」「いくら」の類は、語ではなく数値で答える問い。
# 語の一致だけで見ると、数を答えていても「答えていない」と誤判定する。
_QUANTITY_ASK = re.compile(r"(何件|何名|何人|何回|何日|いくつ|いくら|どれくらい|どのくらい)")
_HAS_NUMBER = re.compile(r"[0-9０-９]")

_STOPWORDS = {
    "こちら", "そちら", "以下", "下記", "上記", "件", "内容", "ため", "こと", "もの",
    "場合", "とき", "ほう", "お願い", "確認", "対応", "ご連絡",
}


def extract_questions(incoming: str) -> list[str]:
    """相手の文面から、答えるべき文を取り出す。"""
    out: list[str] = []
    for raw in re.split(r"[\n。]", incoming):
        s = raw.strip()
        if not s or _CLOSING.match(s):
            continue
        if _QUESTION_END.search(s) or _REQUEST.search(s):
            out.append(s)
    return out


def _keywords(sentence: str) -> list[str]:
    """その問いを指す手がかりの語。漢字カタカナの塊を拾う。"""
    # ひらがなを混ぜて拾うと文がまるごと1語になり、本文と一致しなくなる。
    # 漢字の塊・カタカナの塊・英数字を別々に取る。
    words = re.findall(r"[一-龠]{2,}|[ァ-ヴー]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", sentence)
    return [w for w in words if w not in _STOPWORDS][:6]


class AnswerCoverageGate:
    """相手の問いに対応する語が返信に無ければ止める。"""

    name = "answer_coverage"
    cost = 0

    def check(self, body: str, ctx: Context) -> Verdict:
        questions = extract_questions(ctx.incoming)
        if not questions:
            return Verdict(gate=self.name, skipped="相手の文面に問い・依頼が見当たらない")

        findings: list[Finding] = []
        for q in questions:
            # 数を尋ねる問いは、本文に数値があれば答えたものとして扱う
            if _QUANTITY_ASK.search(q) and _HAS_NUMBER.search(body):
                continue
            keys = _keywords(q)
            if not keys:
                continue
            if not any(k in body for k in keys):
                findings.append(
                    Finding(
                        code="unanswered",
                        message=f"この問いに対応する語が返信にありません(候補: {'・'.join(keys[:3])})",
                        quote=q,
                    )
                )
        return Verdict(gate=self.name, findings=findings)

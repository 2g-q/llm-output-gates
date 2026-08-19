"""ゲートの回帰テスト。

方針: 「通ること」より「壊した入力で止まること」を先に確かめる。
止まらないゲートは置いていないのと同じなので、まずそこを固定する。
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


from gates.base import Context
from gates.completion import CompletionClaimGate
from gates.coverage import AnswerCoverageGate, extract_questions
from gates.forbidden import ForbiddenTermGate
from gates.numbers import NumberClaimGate
from monitor.gate_health import diagnose, tally
from runner import run

# ---- 数値の裏取り ----------------------------------------------------------


def test_数値が証拠に無ければ止まる():
    v = NumberClaimGate().check("対象は 987 件でした。", Context(evidence={}))
    assert v.blocked
    assert v.findings[0].code == "unbacked_number"


def test_数値が証拠にあれば通る():
    v = NumberClaimGate().check("対象は 987 件でした。", Context(evidence={"total": 987}))
    assert not v.blocked


def test_桁区切りと全角を同じ数として扱う():
    v = NumberClaimGate().check("対象は １，２４０ 件でした。", Context(evidence={"total": 1240}))
    assert not v.blocked


def test_証拠が入れ子でも拾う():
    ctx = Context(evidence={"runs": [{"detail": {"saved": 42}}]})
    assert not NumberClaimGate().check("42件を保存しました。", ctx).blocked


def test_日付は数値主張として扱わない():
    v = NumberClaimGate().check("2026年8月19日に実施しました。", Context(evidence={}))
    assert not v.blocked


def test_0と1は誤爆を避けて通す():
    assert not NumberClaimGate().check("該当は 0 件です。", Context(evidence={})).blocked


def test_宣言した数値は理由つきで通る():
    gate = NumberClaimGate(declared={"2000": "1日の上限として自分で決めた値"})
    assert not gate.check("上限は 2000 件です。", Context(evidence={})).blocked


# ---- 完了・網羅の主張 ------------------------------------------------------


def test_証拠なしの完了主張は止まる():
    v = CompletionClaimGate().check("全件そろえて対応済みです。", Context())
    assert v.blocked


def test_証拠つきの完了主張は通るが記録は残る():
    v = CompletionClaimGate().check("全件そろえて対応済みです。", Context(evidence={"checked": 3}))
    assert not v.blocked
    assert v.warned


def test_否定文は完了主張として拾わない():
    v = CompletionClaimGate().check("まだすべては確認できておりません。", Context())
    assert not v.blocked


# ---- 回答漏れ --------------------------------------------------------------


def test_問いの抽出は締めの定型を拾わない():
    qs = extract_questions("料金はいくらでしょうか。\n何卒よろしくお願いいたします。")
    assert qs == ["料金はいくらでしょうか"]


def test_答えていない問いを名指しする():
    ctx = Context(incoming="予約投稿は可能でしょうか。\n料金についてもご教示ください。")
    v = AnswerCoverageGate().check("予約投稿は可能です。", ctx)
    assert v.blocked
    assert "料金" in v.findings[0].quote


def test_すべて答えていれば通る():
    ctx = Context(incoming="予約投稿は可能でしょうか。\n料金についてもご教示ください。")
    v = AnswerCoverageGate().check("予約投稿は可能です。料金は月額でご案内します。", ctx)
    assert not v.blocked


def test_問いが無ければ理由つきで省く():
    ctx = Context(incoming="ありがとうございました。")
    v = AnswerCoverageGate().check("ご確認ありがとうございました。", ctx)
    assert v.skipped


# ---- 禁止語 ----------------------------------------------------------------


def test_内部語の混入を止める():
    assert ForbiddenTermGate().check("(システムプロンプトの指示により)", Context()).blocked


# ---- ランナー --------------------------------------------------------------


def test_安い順に回り止まったら以降は理由つきで省かれる():
    gates = [NumberClaimGate(), CompletionClaimGate(), AnswerCoverageGate(), ForbiddenTermGate()]
    r = run("全件対応済みです。対象は 987 件でした。", Context(incoming="件数は何件でしょうか。"), gates)
    assert r.blocked
    skipped = [v for v in r.verdicts if v.skipped]
    assert skipped, "止まった後のゲートに理由が残っていない"
    assert all(v.skipped for v in skipped)


def test_全部通れば止まらない():
    gates = [NumberClaimGate(), ForbiddenTermGate()]
    r = run("承知いたしました。", Context(), gates)
    assert not r.blocked


# ---- 死んでいるゲートの監視 -------------------------------------------------


def test_一度も止めていないゲートを名指しする():
    manifests = [{"gates": [{"gate": "alive", "blocked": True}, {"gate": "dead", "blocked": False}]}] * 40
    warnings = diagnose(tally(manifests))
    assert any("dead" in w and "死んでいる疑い" in w for w in warnings)
    assert not any("alive" in w for w in warnings)


def test_理由と期限のある例外だけ許容する():
    manifests = [{"gates": [{"gate": "dead", "blocked": False}]}] * 40
    stats = tally(manifests)
    ok = {"dead": {"reason": "助言のみで運用する", "review_by": "2099-01-01"}}
    assert any("[許容]" in w for w in diagnose(stats, exceptions=ok))
    # 期限切れは登録が無いのと同じ扱い
    expired = {"dead": {"reason": "助言のみ", "review_by": "2000-01-01"}}
    assert any("死んでいる疑い" in w for w in diagnose(stats, exceptions=expired))
    # 理由だけで期限が無いものも認めない
    no_deadline = {"dead": {"reason": "助言のみ"}}
    assert any("死んでいる疑い" in w for w in diagnose(stats, exceptions=no_deadline))


def test_数を尋ねる問いは本文に数値があれば答えたとみなす():
    ctx = Context(incoming="件数は何件でしょうか。")
    assert not AnswerCoverageGate().check("対象は 987 件でした。", ctx).blocked


def test_数を尋ねられて数値が無ければ止まる():
    ctx = Context(incoming="件数は何件でしょうか。")
    assert AnswerCoverageGate().check("確認しております。", ctx).blocked


# ---- RAGの引用照合 ----------------------------------------------------------

from gates.grounding import GroundingGate, content_words  # noqa: E402
from judges.llm_judge import JudgeUnavailable, LLMGroundingJudge  # noqa: E402
from judges.protocol import Decision  # noqa: E402

SOURCES = [{"id": "1", "text": "契約金額は30,000円です。納品は電子データで行います。"}]


def test_参照文書にある内容は通る():
    ctx = Context(extra={"sources": SOURCES})
    assert not GroundingGate().check("契約金額は30,000円です。", ctx).blocked


def test_参照文書に無い内容を名指しする():
    ctx = Context(extra={"sources": SOURCES})
    v = GroundingGate().check("解約手数料は50,000円かかります。", ctx)
    assert v.blocked
    assert v.findings[0].code == "ungrounded"


def test_実在しない引用番号を止める():
    ctx = Context(extra={"sources": SOURCES})
    v = GroundingGate().check("契約金額は30,000円です[7]。", ctx)
    assert any(f.code == "unknown_citation" for f in v.findings)


def test_参照文書が無ければ理由つきで省く():
    assert GroundingGate().check("なんらかの主張です。", Context()).skipped


def test_短い文は判定の対象にしない():
    ctx = Context(extra={"sources": SOURCES})
    assert not GroundingGate().check("はい。", ctx).blocked


def test_内容語はひらがなを含めない():
    # ひらがなまで拾うと文がまるごと1語になり、照合が成立しない
    assert content_words("契約金額は30,000円です") == ["契約金額", "30", "000"]


# ---- LLM判定 ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _judge_logic_runs(monkeypatch):
    """判定ロジックのテストは、環境変数の有無に左右されないようにする。

    LLM_GATES_OFFLINE は運用側の止めスイッチであって、
    テストが「検査を動かして確かめる」ことを妨げてはいけない。
    実際にCIでこれを立てたところ、偽クライアントを使う3本が黙って素通りした
    (=検査が動いていないのに緑になる一歩手前だった)。
    スイッチ自体の検査は test_オフライン指定ならLLMを呼ばない が受け持つ。
    """
    monkeypatch.delenv("LLM_GATES_OFFLINE", raising=False)


class _FakeJudge:
    def __init__(self, supported: bool = True, fail: bool = False) -> None:
        self.supported = supported
        self.fail = fail
        self.calls: list[str] = []

    def judge(self, claim: str, sources: str) -> Decision:
        self.calls.append(claim)
        if self.fail:
            raise JudgeUnavailable("テスト用の失敗")
        return Decision(supported=self.supported, reason="テスト")


def test_機械が灰色にした文だけをLLMに聞く():
    ctx = Context(extra={"sources": SOURCES})
    fake = _FakeJudge()
    LLMGroundingJudge(fake).check("契約金額は30,000円です。", ctx)
    assert fake.calls == [], "根拠のある文でLLMを呼んでいる"


def test_LLMが根拠ありと言えば通す():
    ctx = Context(extra={"sources": SOURCES})
    fake = _FakeJudge(supported=True)
    v = LLMGroundingJudge(fake).check("お支払いの総額は三万円となります。", ctx)
    assert not v.blocked
    assert len(fake.calls) == 1


def test_LLMが根拠なしと言えば止める():
    ctx = Context(extra={"sources": SOURCES})
    v = LLMGroundingJudge(_FakeJudge(supported=False)).check("解約手数料は50,000円かかります。", ctx)
    assert v.blocked
    assert v.findings[0].code == "ungrounded_confirmed"


def test_LLMが使えないときは通さず警告として残す():
    ctx = Context(extra={"sources": SOURCES})
    v = LLMGroundingJudge(_FakeJudge(fail=True)).check("解約手数料は50,000円かかります。", ctx)
    assert not v.blocked, "判定できなかったものを止めてはいない"
    assert v.findings[0].code == "judge_unavailable", "判定できなかった事実が残っていない"


def test_オフライン指定ならLLMを呼ばない(monkeypatch):
    # fixture が消したうえで、この検査だけが明示的に立てる
    monkeypatch.setenv("LLM_GATES_OFFLINE", "1")
    fake = _FakeJudge()
    v = LLMGroundingJudge(fake).check("解約手数料は50,000円かかります。", Context(extra={"sources": SOURCES}))
    assert v.skipped
    assert fake.calls == []


def test_判定は安い順の最後に回る():
    from gates.numbers import NumberClaimGate

    gates = [LLMGroundingJudge(_FakeJudge()), NumberClaimGate()]
    assert sorted(g.cost for g in gates) == [0, 100]

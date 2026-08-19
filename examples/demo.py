"""動かして挙動を見るためのサンプル。

  python examples/demo.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gates.base import Context
from gates.completion import CompletionClaimGate
from gates.coverage import AnswerCoverageGate
from gates.forbidden import ForbiddenTermGate
from gates.numbers import NumberClaimGate
from runner import run

GATES = [NumberClaimGate(), CompletionClaimGate(), AnswerCoverageGate(), ForbiddenTermGate()]

CASES = [
    (
        "止まる例: 根拠の無い数値と、確認していない完了主張",
        "全件そろえて対応済みです。対象は 987 件でした。",
        Context(evidence={}, incoming="件数は何件でしょうか。"),
    ),
    (
        "通る例: 数値に根拠があり、問いにも答えている",
        "対象は 987 件でした。うち未処理はありません。",
        Context(evidence={"total": 987}, incoming="件数は何件でしょうか。"),
    ),
    (
        "止まる例: 相手の問いが1つ落ちている",
        "予約投稿は可能です。",
        Context(evidence={}, incoming="予約投稿は可能でしょうか。\n料金についてもご教示ください。"),
    ),
]

for title, body, ctx in CASES:
    print("=" * 72)
    print(title)
    print("-" * 72)
    print(body)
    result = run(body, ctx, GATES)
    print(f"→ 止まったか: {result.blocked}")
    for verdict in result.verdicts:
        for f in verdict.findings:
            print(f"   [{verdict.gate}/{f.level}] {f.message}")
    print()

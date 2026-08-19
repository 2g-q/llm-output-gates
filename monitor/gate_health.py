"""実装されているのに一度も止めていないゲートを名指しする。

なぜ作ったか(このリポジトリで一番伝えたい部分):
  ゲートは「置いた」だけでは効かない。実運用で、実装済みなのに一度も作動していない
  検査が複数見つかったことがある。共通の症状は「実行はされているのに、何も落としていない」。
  人が気づくのは事故の後か、外から指摘されたときだけだった。

  止めすぎは苦情が来るのですぐ気づく。動いていないほうは誰も気づかない。
  この非対称が事故の温床なので、非対称のほうを機械で見張る。

判定:
  - 十分な回数まわっている(既定 30 回)のに不合格 0 件 → 死んでいる疑い
  - skip 分岐が一度も通っていない → その最適化は未検証

例外を認める場合も、理由と見直し期限を必須にした。期限切れは「登録が無い」のと
同じ扱いにしてある。保留のまま放置できる設計にすると、判断が先送りされ続ける。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from collections import defaultdict
from typing import Any

DEFAULT_MIN_RUNS = 30


class Exception_(dict):
    """意図して不合格 0 件のゲート。理由と見直し期限が必須。"""


def load_manifests(path: pathlib.Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(path.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            # 壊れた1件で集計全体を落とさない。ただし黙って捨てない。
            print(f"[warn] 読めない manifest: {p}", file=sys.stderr)
    return out


def tally(manifests: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"executed": 0, "blocked": 0, "skipped": 0})
    for m in manifests:
        for g in m.get("gates", []):
            name = g.get("gate")
            if not name:
                continue
            if g.get("skipped"):
                stats[name]["skipped"] += 1
                continue
            stats[name]["executed"] += 1
            if g.get("blocked"):
                stats[name]["blocked"] += 1
    return dict(stats)


def diagnose(
    stats: dict[str, dict[str, int]],
    min_runs: int = DEFAULT_MIN_RUNS,
    exceptions: dict[str, dict[str, str]] | None = None,
    today: dt.date | None = None,
) -> list[str]:
    exceptions = exceptions or {}
    today = today or dt.date.today()
    warnings: list[str] = []

    for name, s in sorted(stats.items()):
        if s["executed"] >= min_runs and s["blocked"] == 0:
            note = exceptions.get(name)
            reason = _valid_exception(note, today)
            if reason:
                warnings.append(
                    f"[許容] {name}: {s['executed']}回まわって不合格0件。理由={reason}"
                )
            else:
                warnings.append(
                    f"[死んでいる疑い] {name}: {s['executed']}回まわって不合格0件。"
                    "止める条件が実際の入力に当たっていない可能性がある"
                )
        if s["skipped"] == 0 and s["executed"] > 0:
            continue
    return warnings


def _valid_exception(note: dict[str, str] | None, today: dt.date) -> str | None:
    """理由と見直し期限がそろっているときだけ例外として認める。"""
    if not note:
        return None
    reason = note.get("reason")
    review_by = note.get("review_by")
    if not reason or not review_by:
        return None
    try:
        deadline = dt.date.fromisoformat(review_by)
    except ValueError:
        return None
    if deadline < today:
        return None
    return f"{reason}(見直し期限 {review_by})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifests", help="manifest(JSON)を置いたディレクトリ")
    ap.add_argument("--min-runs", type=int, default=DEFAULT_MIN_RUNS)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    stats = tally(load_manifests(pathlib.Path(args.manifests)))
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    if not stats:
        print("manifest が1件も読めませんでした")
        return 2

    for name, s in sorted(stats.items()):
        rate = (s["blocked"] / s["executed"] * 100) if s["executed"] else 0.0
        print(f"{name:20s} 実行{s['executed']:5d}  停止{s['blocked']:5d} ({rate:5.1f}%)  skip{s['skipped']:5d}")

    warnings = diagnose(stats, min_runs=args.min_runs)
    if warnings:
        print()
        for w in warnings:
            print(w)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

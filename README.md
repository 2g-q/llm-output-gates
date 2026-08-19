# llm-output-gates

[![CI](https://github.com/2g-q/llm-output-gates/actions/workflows/ci.yml/badge.svg)](https://github.com/2g-q/llm-output-gates/actions/workflows/ci.yml)

LLM が書いた文章を人に渡す前に、機械で止めるための検査ゲート。

[English](./README.en.md)

生成の品質を上げる道具ではない。**間違ったまま外に出ることを止める**道具です。

```python
from gates.base import Context
from gates.numbers import NumberClaimGate
from gates.completion import CompletionClaimGate
from gates.coverage import AnswerCoverageGate
from gates.forbidden import ForbiddenTermGate
from runner import run

result = run(
    body="全件そろえて対応済みです。対象は 987 件でした。",
    ctx=Context(evidence={}, incoming="件数は何件でしょうか。"),
    gates=[NumberClaimGate(), CompletionClaimGate(), AnswerCoverageGate(), ForbiddenTermGate()],
)
print(result.blocked)  # True
print(result.to_json())  # どのゲートが何を理由に止めたかが残る
```

## なぜ作ったか

LLM に業務の文面を書かせて実運用に載せると、失敗の形が偏ってきます。

- **数値が最もらしく混ざる** — 「12件対応しました」「約40%改善」。文体は自然なので、人のレビューをすり抜ける
- **確認していないのに完了と書く** — 部分だけ見て「全件そろえました」。相手が現物を見て食い違いに気づく形が、いちばん信用を失う
- **聞かれたことに答えていない** — 文面としては整っているのに、相手の問いが1つ落ちている
- **内部の指示が末尾に紛れ込む** — 1度でも届くと取り返しがつかない

いずれも「文章としては正しく見える」ため、読み返しでは落ちません。**機械で照合できるものは機械で照合する**、という切り分けでこれらを止めています。

## 収録しているもの

| ゲート | 何を止めるか |
|---|---|
| `gates/numbers.py` | 出力に現れる数値のうち、根拠に存在しないもの |
| `gates/completion.py` | 「完了しました」「全件」など、確認の記録が無い断定 |
| `gates/coverage.py` | 相手の問いのうち、返信で触れられていないもの |
| `gates/grounding.py` | **RAGの回答のうち、参照文書に基づいていない文**(文単位・引用番号の実在も見る) |
| `gates/forbidden.py` | 外に出せない語の混入 |
| `judges/llm_judge.py` | **機械が灰色にした文だけ**をLLMへ送り、yes/no で確かめる |
| `runner.py` | ゲートを安い順に回し、止まったら以降を省く |
| `monitor/gate_health.py` | **実装されているのに一度も止めていないゲートを名指しする** |

## 設計で効いた判断

**1. 判定は決定的にする。候補を LLM に作らせない**

回答漏れの検査は、当初 LLM に「答えるべき点」を列挙させていました。同じ入力でも列挙が揺れ、判定が再現しませんでした。いまは候補集合を正規表現で固定し、LLM を併用する場合も「この問いに答えているか」の yes/no だけを聞く形にしています。

**2. 機械で絞り、灰色だけをLLMに聞く**

`GroundingGate` は語の重なりで見るので、言い換えられていると閾値を割ります。全部止めると使えず、全部通すと意味がない。そこで**機械が灰色の文を選び、その文だけ**をLLMに yes/no で聞きます。費用が入力量に比例せず、LLMを呼ぶ理由が毎回機械の側にあります。

**3. ゲートは安い順に回す**

正規表現の検査は 0 円、LLM を呼ぶ検査は 1 回ごとに費用と待ち時間がかかります。先に安いほうで落とせるなら高いほうを呼ぶ理由がない。順序は `sorted(gates, key=cost)` の 1 か所だけで決まるようにしてあります。「安い順」と書いてあるのに実装がそうなっていない、という状態を作らないためです。

**4. 逃げ道は用意する。ただし理由を必須にして記録に残す**

自分で決めた閾値のように、証拠の中に存在しない数値もあります。`NumberClaimGate(declared={"2000": "1日の上限として自分で決めた値"})` で通せますが、理由が無いと通りません。黙って解除できる逃げ道は、いずれ全部そこを通ります。

**5. 「止めすぎ」より「動いていない」を見張る**

止めすぎればすぐ苦情が来ます。**動いていないほうは誰も気づきません**。この非対称が事故の温床なので、`monitor/gate_health.py` は「十分な回数まわっているのに一度も止めていないゲート」を名指しします。例外として認める場合も、理由と見直し期限の両方が要ります。期限切れは登録が無いのと同じ扱いです。保留のまま放置できる設計にすると、判断が先送りされ続けます。

**6. 「確認できなかった」を「問題なし」にしない**

LLM判定が使えないとき(上限・通信断・拒否)、その文を黙って通しません。`judge_unavailable` として記録します。「見て問題なかった」と「見られなかった」が同じ結果になるゲートは、嘘をついていることになります。

**7. 「語で答える問い」と「数で答える問い」を分ける**

回答漏れの検査を語の一致だけで見ると、「何件でしょうか」に「987 件でした」と答えていても漏れと判定します。数を尋ねる問いは、本文に数値があるかで見るようにしました。実際にサンプルを動かして誤爆が出たので直した箇所です。

**8. 誤爆を減らす線を実データで引く**

`0` と `1` は「該当はありません」「1点だけ」のような言い回しで頻出し、根拠が無くても誤りとは限りません。日付・時刻・箇条書きの番号も数値主張として扱いません。ここを止めると誤爆で信用を失い、やがて誰も警告を読まなくなります。

## この道具がやらないこと

- **証拠そのものの正しさは保証しません。** 見るのは「その数値の出どころが証拠の中にあるか」までです。証拠が誤っていれば、その誤りごと通ります
- 文章の良し悪しは判定しません
- 事実確認の代わりにはなりません。人が確認する範囲を狭めるための道具です

## テスト

```
python -m pytest -q
```

33 件。方針として、**「通ること」より「壊した入力で止まること」を先に固定**しています。止まらないゲートは置いていないのと同じだからです。

CI は Python 3.10〜3.13 で回し、`LLM_GATES_OFFLINE=1` を立てて**ネットワークを使わない**ようにしてあります。

## 動かす

機械判定は標準ライブラリだけで動きます。LLM判定を使うときだけ Anthropic SDK が要ります。Python 3.10 以上。

```
pip install -e .           # 機械判定だけ
pip install -e ".[judge]"  # LLM判定つき
```

```python
from judges.llm_judge import AnthropicJudgeClient, LLMGroundingJudge

judge = LLMGroundingJudge(AnthropicJudgeClient())  # ANTHROPIC_API_KEY を読む
```

`LLM_GATES_OFFLINE=1` を立てるとLLMの呼び出しを全て省きます。

```
python -m pytest -q
python monitor/gate_health.py <manifestを置いたディレクトリ>
```

## ライセンス

MIT

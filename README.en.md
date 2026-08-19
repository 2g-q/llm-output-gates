# llm-output-gates

Gates that stop LLM-written text before a human ever sees it.

This is not a tool for improving generation quality. It is a tool for **stopping wrong output from going out**.

```python
from gates.base import Context
from gates.numbers import NumberClaimGate
from gates.completion import CompletionClaimGate
from gates.coverage import AnswerCoverageGate
from gates.forbidden import ForbiddenTermGate
from runner import run

result = run(
    body="Everything is done. There were 987 records.",
    ctx=Context(evidence={}, incoming="How many records were there?"),
    gates=[NumberClaimGate(), CompletionClaimGate(), AnswerCoverageGate(), ForbiddenTermGate()],
)
print(result.blocked)  # True
print(result.to_json())  # which gate stopped it, and why
```

## Why this exists

Once you put LLM-written business text into production, the failures cluster:

- **Numbers appear, plausibly.** "Handled 12 cases." "About 40% faster." The prose reads naturally, so human review slides right past it
- **It claims completion it never verified.** Checked part of the data, reported "all records are in." The customer looks at the real thing and finds the gap — the single fastest way to lose trust
- **It doesn't answer what was asked.** The text is well-formed, but one of the questions is missing
- **Internal instructions leak into the tail.** Once that reaches a customer, you can't take it back

None of these are caught by re-reading, because the text *looks* correct. The split here is simple: **whatever a machine can check, a machine checks.**

## What's in it

| Gate | What it stops |
|---|---|
| `gates/numbers.py` | Numbers in the output with no source in the evidence |
| `gates/completion.py` | "Done", "all of them" — assertions with no record of verification |
| `gates/coverage.py` | Questions from the other party the reply never addresses |
| `gates/grounding.py` | **RAG answers not supported by the source documents** (per sentence, plus citation-ID checking) |
| `gates/forbidden.py` | Internal terms that must not go out |
| `judges/llm_judge.py` | **Sends only the machine-gray sentences to an LLM for a yes/no** |
| `runner.py` | Runs gates cheapest-first, stops on the first block |
| `monitor/gate_health.py` | **Names gates that are running but have never stopped anything** |

## Design decisions that mattered

**1. Keep judgments deterministic. Never let the LLM build the candidate set.**

The answer-coverage check originally asked an LLM to enumerate "points that need answering." The enumeration drifted between runs on identical input, so the verdict wasn't reproducible. Now the candidate set is fixed by regex, and when an LLM is involved it only answers yes/no for one candidate at a time.

**2. Machine first, LLM only for the gray area**

`GroundingGate` compares content words. Paraphrases can fall below the threshold. Blocking all of them makes the system unusable; passing all of them makes the gate pointless. So the machine picks the gray sentences and the LLM answers yes/no on just those — bounded cost, and every LLM call has a machine-made reason to exist.

**3. Run gates cheapest-first**

Regex gates cost nothing; an LLM call costs money and latency. If the cheap one can stop it, there is no reason to pay for the expensive one. The ordering lives in exactly one place (`sorted(gates, key=cost)`) — so the code can't drift from the comment above it.

**4. Provide escape hatches. Require a reason, and record it.**

Some numbers are thresholds you chose yourself and will never appear in evidence. `NumberClaimGate(declared={"2000": "daily read cap I set"})` lets them through — but not without a reason. An escape hatch that can be used silently eventually carries all the traffic.

**5. Watch for gates that aren't firing, not just gates that fire too much**

Over-blocking generates complaints immediately. **Under-firing generates nothing at all.** That asymmetry is where incidents come from, so `monitor/gate_health.py` names any gate that has run enough times and never stopped anything. Granting an exception requires both a reason and a review date — an expired exception counts as no exception. Without that, decisions get deferred forever.

**6. "Failed to check" is not "passed"**

When the LLM judge is unavailable (rate limit, network, refusal), the sentence is not silently passed. It's recorded as `judge_unavailable`. If "we looked and it was fine" and "we couldn't look" collapse into the same result, the gate is lying to you.

**7. Separate questions answered with words from questions answered with numbers**

Matching words alone, "how many records?" answered with "there were 987" reads as unanswered. Quantity questions are checked against the presence of a number instead. Found by running the samples and watching it misfire.

**8. Draw the false-positive line from real data**

`0` and `1` show up constantly in phrasings like "there were none" and "just one," where absent evidence doesn't imply an error. Dates, times, and list numbering aren't treated as numeric claims either. Block those and the false positives pile up, trust erodes, and eventually nobody reads the warnings at all.

## What this does not do

- **It does not vouch for the evidence.** It checks whether a number has a source in what you supplied. If the evidence itself is wrong, the error passes through with it
- It does not judge whether the writing is any good
- It is not a substitute for fact-checking. It narrows what a human has to check

## Tests

```
python -m pytest -q
```

33 tests. The policy is to pin **"it blocks on broken input"** before "it passes on good input" — a gate that never blocks is the same as no gate at all.

CI runs on Python 3.10–3.13 with `LLM_GATES_OFFLINE=1`, so nothing in the test suite touches the network.

## Install

Machine gates need only the standard library. The LLM judge needs the Anthropic SDK.

```
pip install -e .           # machine gates only
pip install -e ".[judge]"  # with the LLM judge
```

```python
from judges.llm_judge import AnthropicJudgeClient, LLMGroundingJudge

judge = LLMGroundingJudge(AnthropicJudgeClient())  # reads ANTHROPIC_API_KEY
```

Set `LLM_GATES_OFFLINE=1` to skip every LLM call.

## License

MIT

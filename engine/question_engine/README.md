# question_engine

Decide which question to ask next by testing which unknown fact would change the answer the most. Pure Python, no dependencies, and no knowledge of any domain: it was built for a benefits screener (Unclaimed) and is meant to be reused for any interview where the right questions matter (e.g. which documents a mortgage application needs).

## Idea

A form asks everything. A good caseworker asks only what changes the answer. Given the current state, a set of candidate questions and a calculator for your rules, the engine:

1. Tries each candidate at a low and a high value (e.g. income $0 vs $60,000; pregnant no vs yes), all variants in **one batched calculator call**.
2. Scores it: `(flip_weight × outcomes that flip yes/no + total value swing) / cost`.
3. Asks the best, or **stops** when no candidate flips any outcome and none moves a value by at least `stop_below`.

## API

```python
import question_engine as qe

class MyRules:
    def evaluate(self, state, changes):            # one call per decision
        return [outcomes({**state, **c}) for c in changes]   # [{outcome_id: (eligible, value)}]

decision = qe.decide(
    state,
    [qe.Candidate(key="income", low=0, high=60_000, cost=2),
     qe.Candidate(key="pregnant", low=False, high=True, cost=3)],
    MyRules(), flip_weight=1_000, stop_below=25)

decision.stop        # nothing left would change the answer enough
decision.ask         # the Candidate to ask next
decision.ranked      # every candidate with its flips, swing and score
```

`Candidate.together` lets you ask related questions in one breath (e.g. every kind of "other income", or "does anyone in the household have a disability?").

## Design notes

- **Flips dominate dollars.** Changing whether someone qualifies matters more than changing an amount; `flip_weight` sets the exchange rate.
- **Cost** is how burdensome or sensitive a question is (1 easy … 5 sensitive), so a sensitive question is asked only when it matters a lot.
- **Stopping** checks every candidate, not just the top one: a costly question can rank low and still flip an outcome.
- **Batching is the calculator's job.** Rules engines are usually vectorized; evaluating all variants together is ~100× faster than one by one.
- Answers the person declines are your state's concern: drop them from the candidates, and report outcomes that depend on them as conditional.

Tests: `engine/tests/test_question_engine.py` (with a fake calculator).

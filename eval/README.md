# eval

Every household is compared with its **full-information answer**: what the engine says when every question is answered. The headline metric is a false "you qualify" (target 0).

| File | What |
|---|---|
| `tier_a.yaml` | Tier A: handwritten CA and IL households, including every case a review broke |
| `tier_b.py` | Tier B: generated households (pairwise combinations; every program's income cutoff ±$1); only answers that can exist at that age |
| `simulate.py` | The oracle interview: the Question Engine asks, an oracle answers from the household's truth (declining what the case declines) |
| `run.py` | Runs Tiers A and B and writes `docs/scorecard.md` |
| `tier_c.py` | Tier C: a model plays each Tier A household in everyday words, talking with the simulator's Alexa through the real MCP server |
| `experiments.py` | Research E1 (question-selection policies) and E2 (results mid-interview, with and without tracking unknowns): oracle, free |
| `e3.py` | Research E3: our design against a model with the calculator as a tool and a model alone, in simulated conversations (Bedrock, budget-capped) |

Run from `engine/` (its environment) for the oracle tiers and experiments, from `simulator/` for anything that talks:

```bash
cd engine
uv run python ../eval/run.py a b                 # scorecard, Tiers A and B
uv run python ../eval/experiments.py e1 e2       # docs/research-results.md
uv run python ../eval/tier_c.py prepare          # cases for Tier C and E3
cd ../simulator                                  # engine + MCP server running; Bedrock credentials
uv run python ../eval/tier_c.py run
uv run python ../eval/e3.py --model us.amazon.nova-2-lite-v1:0 --budget 15
```

Raw results go to `eval/results/` (not committed). The plan and threats to validity: `docs/research-plan.md`.

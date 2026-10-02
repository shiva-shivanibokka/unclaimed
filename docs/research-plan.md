# Research plan: reliable interviewing agents

Working title: **Talk, Don't Decide: Separating Conversation from Decision in a Benefits-Screening Agent**

## Question
When an agent must interview a person and then make a high-stakes determination (here: which public benefits a household qualifies for), where should the decisions live? We test a split design: the language model only phrases questions and explains results; *which* question to ask next, *when* to stop, and *what* the person qualifies for are decided by code (a value-of-information policy over an exact rules engine, PolicyEngine-US), with every unknown or declined answer tracked so that it can't silently become a default.

The failure that matters is a **false "you qualify"**: telling a person they qualify when, given their full situation, they don't. It sends people to apply for help they won't get, and it is the error a fluent model is most likely to make with confidence.

## Contributions
1. **Design:** conversation/decision separation for interviewing agents: value-of-information question selection with batched what-if simulation, a stop rule, and explicit known/unknown/declined state that turns "unknown" into conditional results ("if ...") instead of defaults.
2. **Evaluation method:** reference answers from full information; oracle interviews over handwritten households (Tier A) and generated ones covering every eligibility cutoff ±$1 and pairwise combinations (Tier B); simulated conversations with a language model playing the person (Tier C).
3. **Evidence** from the experiments below.

## Experiments
| # | What | Conditions | Needs a model? |
|---|---|---|---|
| E1 | Question selection | value of information (ours) · every applicable question in a fixed order · fixed order with our stop rule · random order with our stop rule | No (oracle, Tiers A+B) |
| E2 | Silent defaults | results at each point of the interview with unknowns tracked (ours) vs unknowns left to the engine's defaults: false "you qualify" as a function of questions asked | No (oracle, Tiers A+B) |
| E3 | Where decisions live | (a) ours: model talks, tools decide · (b) model + the same calculator as a tool, but the model chooses questions and when to stop · (c) model alone, no tools | Yes (Bedrock): same simulated people for all three |
| E4 | Failure analysis | categories of errors in E3 transcripts (wrong rule, silent assumption, unit mistake, hallucinated program, ...) | Reads E3 transcripts |

Metrics: false "you qualify" (per household and per program), programs missed, amount error, questions asked, turns, latency, model cost.

## Threats to validity (stated in the paper)
- The reference is PolicyEngine-US, not agency decisions; we test separately against official figures (`engine/tests/test_official.py`) but agreement with the reference is not real-world accuracy.
- Simulated people are a model, not real people; their phrasing is plausible but not representative.
- Two states (CA, IL), the programs in `engine/unclaimed_engine/programs.py`, one point in time.
- Same model family for the agent and the simulated person can flatter or hurt results; E3 uses a different model for the person where possible.

## Artifacts
Code, households, and transcripts are in this repository (AGPL-3.0). Paper source: `paper/`.

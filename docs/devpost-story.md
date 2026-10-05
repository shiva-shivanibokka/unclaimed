
## Inspiration
Every year, billions of dollars in benefits go unclaimed. The IRS estimates that roughly 1 in 5 people eligible for the Earned Income Tax Credit never claim it, and food assistance, WIC and health-coverage programs have similar gaps. The people who qualify are often the busiest: a parent making dinner with two kids, a worker juggling shifts. The forms are long, the rules are confusing, and most people assume they don't qualify.

Alexa+ is already in the kitchen, where those conversations happen. I wanted a voice agent that works like a good caseworker: it asks a few smart questions, does the math exactly, and tells you what to do next.

## What it does
Unclaimed is a self-hosted MCP server for **Alexa+** that screens a household for benefits in **California and Illinois**:

1. **Asks only the questions that matter.** After a few essentials (ZIP code, who lives with you, pay, other income, housing), a *Question Engine* picks the next question by testing which unknown fact would change the result the most. After a few it shows results; programs that an unasked answer could still change say "maybe", and asking about one brings only the questions that settle it.
2. **Calculates exactly.** Eligibility and amounts come from [PolicyEngine-US](https://github.com/PolicyEngine/policyengine-us), an open-source rules engine that encodes federal and state tax and benefit law. The AI never does arithmetic and never decides eligibility.
3. **Hands off a plan.** The Echo Show shows the results as tiles, then a plan for each program you pick: where and how to apply, what to bring, what happens next and common mistakes, from the agencies' own pages (cited and dated), plus a QR code that opens the application on your phone.

Nothing about the household is stored.

## How I built it
- **Alexa+ → MCP server (TypeScript, Streamable HTTP, MCP 2025-11-25):** four tools with strict answer schemas (amount + frequency + before/after taxes). The server validates, converts units and reads answers back for confirmation. The Echo Show screen is an MCP App.
- **Our own Alexa+ simulator:** Alexa+ developer tools are partner-only, so I built a stand-in: an Echo Show-style web page where you talk with Alexa live: **Amazon Nova 2 Sonic** on **Amazon Bedrock** (speech to speech, run by a **Strands** BidiAgent) hears you and answers out loud, calling the MCP server the way Alexa+ does, and the page hosts the MCP App screen. Hands-free after one tap, and you can cut in while she talks. Both run on **AWS (ECS Express Mode)**, public and free to try, rate-limited.
- **Engine service (Python, FastAPI, on AWS):** the Question Engine and PolicyEngine, kept warm. Each turn, the Question Engine runs a batch of "what-if" simulations and scores each candidate question $q$:

$$\text{score}(q) = \frac{w \cdot \text{flips}(q) + \Delta\$(q)}{\text{cost}(q)}$$

where *flips* counts programs whose yes/no answer changes, $\Delta\$$ is the dollar swing and *cost* reflects how burdensome or sensitive the question is.
- **Dictionary:** every askable fact with its exact definition, friendly wording, units and rules for when it applies. A coverage test proves that every engine input is either asked, derived, assumed out loud, or out of scope.
- **Evaluation:** handwritten households, generated households (pairwise coverage + every program's cutoff ±$1), and simulated conversations where a second model on Amazon Bedrock plays the person, all compared with the answer you'd get if every question were answered. The headline metric is a false "you qualify": telling someone they qualify when they don't.

## Challenges
- **Silent defaults.** The rules engine assumes 0 for anything you don't provide, citizenship if you skip immigration status, and the *first county in the state* if you skip county (and county changes health-insurance subsidies). So the system tracks *known / unknown / declined* for every fact, maps ZIP → county itself, and says "if ..." instead of "you qualify" when an unknown could change the answer.
- **Units.** Pay, rent and benefits come in weekly, bi-weekly, monthly and yearly units, and take-home pay differs from gross. Every conversion happens in code, never in the language model.
- **Latency.** Alexa+ requires responses in under 500 ms, but a full calculation can take longer. The Question Engine precomputes likely answers while the person is still speaking, and the results as soon as the interview ends.
- **Testing my own work honestly.** After every stage, an independent reviewer tried to break it (wrong results, hidden defaults, security, over-engineering); every finding was verified, fixed or explicitly accepted, and recorded.

## What I learned
*(to be completed)*

## Accomplishments
*(fill from `docs/scorecard.md` on submission day: households tested, false "you qualify", programs missed, median questions asked)*

## What's next
More states and programs; real people instead of simulated ones; a research write-up comparing this design with letting the model decide; and publishing the Question Engine as its own open-source library for other interviews where the right questions matter, such as mortgage applications.

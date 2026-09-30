<!-- Devpost "About the project" draft. Updated as the build progresses. [NAME] = final product name. -->

## Inspiration
Every year, billions of dollars in benefits go unclaimed. The IRS estimates that roughly 1 in 5 people eligible for the Earned Income Tax Credit never claim it, and food assistance, WIC and health-coverage programs have similar gaps. The people who qualify are often the busiest: a parent making dinner with two kids, a worker juggling shifts. The forms are long, the rules are confusing, and most people assume they don't qualify.

Alexa+ is already in the kitchen, where those conversations happen. I wanted a voice agent that works like a good caseworker: it asks a few smart questions, does the math exactly, and tells you what to do next.

## What it does
[NAME] is a self-hosted MCP server for **Alexa+** that screens a household for benefits in **California and Illinois**:

1. **Asks only the questions that matter.** After five core questions (ZIP code, who lives with you, pay before taxes, other income, housing cost), a *Question Engine* decides the next question by testing which unknown fact would change the result the most. When nothing left would change the answer, it stops.
2. **Calculates exactly.** Eligibility and amounts come from [PolicyEngine-US](https://github.com/PolicyEngine/policyengine-us), an open-source rules engine that encodes federal and state tax and benefit law. The AI never does arithmetic and never decides eligibility.
3. **Hands off a plan.** The Echo Show displays each program as a card: why you likely qualify, where to apply, what to bring, what happens next and common mistakes, plus a QR code that opens the application on your phone.

Nothing about the household is stored.

## How I built it
- **Alexa+ → MCP server (TypeScript, Streamable HTTP, MCP 2025-11-25):** tools with strict answer schemas (amount + frequency + before/after taxes). The server validates, converts units and reads answers back for confirmation.
- **Engine service (Python, FastAPI, on AWS):** the Question Engine and PolicyEngine, kept warm. Each turn, the Question Engine runs a batch of "what-if" simulations and scores each candidate question $q$:

$$\text{score}(q) = \frac{w \cdot \text{flips}(q) + \Delta\$(q)}{\text{cost}(q)}$$

where *flips* counts programs whose yes/no answer changes, $\Delta\$$ is the dollar swing and *cost* reflects how burdensome or sensitive the question is.
- **Dictionary:** every askable fact with its exact definition, friendly wording, units and rules for when it applies. A coverage test proves that every engine input is either asked, derived, assumed out loud, or out of scope.
- **Evaluation:** thousands of generated households (pairwise coverage + every program cutoff ±$1) plus simulated conversations built with **Strands Agents on Amazon Bedrock**.

## Challenges
- **Silent defaults.** The rules engine assumes 0 for anything you don't provide, and assumes the *first county alphabetically* if you skip county. In testing, county alone doubled one household's health-insurance subsidy ($6,610 in Los Angeles vs $13,221 in Modoc). So the system tracks *known / unknown / declined* for every fact and maps ZIP → county itself.
- **Units.** Pay, rent and benefits come in weekly, bi-weekly, monthly and yearly units, and take-home pay differs from gross. Every conversion happens in code, never in the language model.
- **Latency.** Alexa+ requires responses in under 500 ms, but a full calculation can take longer. The Question Engine precomputes likely answers while the person is still speaking.

## What I learned
*(to be completed)*

## Accomplishments
*(scorecard to come: accuracy vs full-information answer, average questions asked, false "you qualify" rate)*

## What's next
More states, more programs, and reusing the Question Engine, which is published as its own open-source library, for other interviews where the right questions matter, such as mortgage applications.

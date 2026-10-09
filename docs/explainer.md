# Unclaimed, in plain words

For explaining the project out loud: in the demo video, to a judge, or to a recruiter.
Nothing here is new; it's the rest of `docs/` without the jargon. The numbers all come
from `docs/scorecard.md`, which the evaluation writes.

## 1. What it is, in one breath

You tell Alexa you want to check what benefits you can get. She asks about seven
questions out loud, then tells you which programs you likely qualify for, roughly how
much, and the first step to apply. The plan shows up on the screen with a code you scan
to carry it to your phone.

## 2. Why it needs to exist

Money that people are entitled to goes unclaimed. About one in five people who qualify
for the Earned Income Tax Credit never claim it (IRS), and other programs have gaps like
it. The usual reason isn't that people don't want the money: the screeners that exist ask
forty or fifty questions in a web form, so people start and give up.

So the problem isn't the arithmetic. **It's the interview.**

## 3. The one big idea: ask only what changes the answer

This is the part that is actually ours, and the part worth talking about.

Most of the forty questions don't matter for *you*. If you have no children, every
question about child care is wasted. If your income is far below a program's limit, your
savings balance won't change anything.

So after every answer, the Question Engine does this:

1. Lists the questions it *could* ask next.
2. For each one, runs the benefits calculator twice: once as if the answer were nothing,
   once as if it were a realistic high value.
3. Looks at what moved. Did any program flip between qualifying and not? Did the money
   change by a meaningful amount?
4. Scores each question by how much it moved things, divided by how annoying it is to ask.
5. Asks the winner. If nothing would move, it stops and gives results.

That's it. No hand-written decision tree, no "if state == CA" rules to maintain. It reads
which questions matter from the rules themselves, so it keeps working when the law changes.

**The result:** about seven questions instead of forty, and the same answer.

### What happens to the questions it never asked

This is the honest part. If a question was never asked, the programs it could have
flipped are shown as **"maybe"**, never as "you qualify". So the person hears:

> "You likely qualify for three programs. The biggest are CalFresh and the federal child
> tax credit, with their amounts. Two more are maybes: WIC and the utility discount. Want
> me to check those with a couple of quick questions?"

(The amounts are whatever the calculator returned for that household; the screen lists
every program, so she names at most two out loud.)

If they say yes, the same loop runs again on just those programs until nothing is in
doubt. If they say no, they still leave with the three solid ones.

## 4. The hard rule: the AI never decides anything

The language model phrases questions and explains results. That's all.

Every dollar amount and every eligibility decision comes from **PolicyEngine-US**, an
open-source model of US tax and benefit law, pinned to one version. The model is not
allowed to do arithmetic, and it is not allowed to say who qualifies for what.

**Why:** language models make things up. If this one invents a benefit amount, someone
budgets their rent around a number that isn't real. The way to get an AI near a decision
like that is to make sure it is never the thing deciding.

This is also the answer to "how do you stop it hallucinating?" We didn't make the model
more careful. We took the decision away from it.

## 5. The map

```
  Person speaks
       │
       ▼
  ┌─────────────────────────────────────────────┐
  │ THE DEVICE  (our Alexa+ simulator, a web    │
  │ page that looks like an Echo Show)          │
  │                                             │
  │ mic → 16 kHz audio ──────┐                  │
  │ Alexa's voice ◄──────────┤  over one        │
  │ screen cards ◄───────────┘  WebSocket       │
  └──────────────┬──────────────────────────────┘
                 │
                 ▼
  ┌─────────────────────────────────────────────┐
  │ ALEXA'S BRAIN  (Amazon Nova 2 Sonic, on     │
  │ AWS Bedrock, run by a Strands agent)        │
  │                                             │
  │ Hears audio and speaks audio directly:      │
  │ one model, no text-to-speech step.          │
  │ Decides which tool to call, never what      │
  │ anyone qualifies for.                       │
  └──────────────┬──────────────────────────────┘
                 │  calls one of five tools
                 ▼
  ┌─────────────────────────────────────────────┐
  │ THE MCP SERVER  (TypeScript)                │
  │                                             │
  │ start_screening · answer · get_results      │
  │ check_programs · get_plan                   │
  │                                             │
  │ Checks every answer against the schema,     │
  │ converts the person's units into the         │
  │ calculator's, reads answers back, and        │
  │ returns the screen to draw.                 │
  └──────────────┬──────────────────────────────┘
                 │
                 ▼
  ┌─────────────────────────────────────────────┐
  │ THE ENGINE  (Python)                        │
  │                                             │
  │ ① Question Engine: what to ask next, or stop│
  │ ② PolicyEngine-US: the actual calculation   │
  │ ③ Plan cards: how to apply, from the        │
  │    agency's own pages, with a date          │
  └─────────────────────────────────────────────┘
```

Two things travel back up on every turn: **what to say next**, and **the household draft**
(everything known so far). The draft lives in the message, not in a database.

## 6. The pieces, and why each one exists

| Piece | What it does | Why it exists |
|---|---|---|
| **The dictionary** (`dictionary/dictionary.yaml`) | One file holding every question: its wording, what units a person may answer in, which calculator input it feeds | One source of truth. The wording lives in exactly one place, so the voice, the screen and the tests can't drift apart |
| **The engine** (`engine/`) | Wraps PolicyEngine-US; holds the Question Engine | The calculation and the question choice are the two things that must be testable |
| **The MCP server** (`mcp-server/`) | The five tools Alexa calls | MCP (Model Context Protocol) is the standard Alexa+ uses for add-ons. Building to it means this could plug into the real Alexa+ |
| **The simulator** (`simulator/`) | Our own Alexa+ device in a browser: mic, voice, Echo Show–style screen | Amazon's Alexa+ developer tools are partner-only. We were refused, so we built the device too |
| **The plan cards** (`plans/`) | How to apply: where, what to bring, what happens next | A calculator that says "you qualify" and stops is useless. The point is the application |
| **The evaluation** (`eval/`) | Runs hundreds of households through the whole thing and scores it | Without this it's a demo, not a result |

## 7. The decisions, and why

| Decision | Why |
|---|---|
| **Code does all arithmetic and every eligibility decision; the AI only talks** | A wrong benefit amount hurts someone. Models invent numbers; calculators don't |
| **Ask only what changes the answer** | Long forms are why people give up. This is the project's actual contribution |
| **Never guess an unasked question — show it as "maybe"** | Overstating is the one unforgivable error here. The target is zero false "you qualify", and we measure it |
| **No database. Nothing about the person is stored** | It's income, disability and immigration status. The safest way to protect it is not to have it. The household draft rides inside each message |
| **No login** | Anyone can try it, including judges. Also nothing to store |
| **We built our own Alexa+ device** | Amazon's add-on tooling is allowlist-only and we were denied, and the hackathon FAQ confirmed participants don't get it. A self-hosted MCP server plus our own device is allowed by the rules |
| **Live speech-to-speech (Amazon Nova 2 Sonic), not text-to-speech** | The first version used browser speech plus Amazon Polly. It worked, but it felt robotic and slow and you had to tap for each turn. One model that hears and speaks is warmer, lets you interrupt, and answers in about two seconds |
| **Ask in the person's own units ($18 an hour, 30 hours a week) and convert in code** | Nobody knows their annual gross income. Asking for it is how forms lose people |
| **California and Illinois only** | Two states done properly, with real county data, beats fifty done loosely |
| **Nothing hard-coded. Rules, amounts and county names are read from their source** | A number typed into our code is a number that silently goes stale. The one exception: the tests' expected answers are official published figures typed in with citations, because a test that asks the engine for the answer can't catch the engine being wrong |
| **AGPL-3.0** | PolicyEngine-US is AGPL, so anything built on it must be |
| **An independent review after every stage** | A fresh reviewer with no stake tries to break the work before the next stage starts. Several real bugs were caught this way |

## 8. How we know it works

Three levels of testing, because each one catches something the others can't.

- **Tier A, 38 households written by hand.** Each one is a real situation (a single parent
  in Los Angeles on $32,000; a senior couple who own their home). An oracle answers every
  question truthfully from the household's facts, and the result is compared with what you
  get if you know everything.
- **Tier B, 437 households generated** across incomes, ages, family shapes and both states.
  Same comparison, at volume.
- **Tier C, live voice conversations.** A second AI plays the person, answering in everyday
  words, sometimes vaguely, sometimes off-topic. It talks to the real Alexa through the real
  microphone path and the real tools. This is the only test that catches the things that go
  wrong *in conversation*.

**The headline result:** across all 475 households in A and B, after the person checks their
"maybe" programs, the answer matches the full-information answer for every program, with
**zero** false "you qualify". The median interview is seven questions.

The voice tier is harder and the current numbers are in `docs/scorecard.md`. Reading those
transcripts is where the real bugs came from: Alexa arguing about a definition, inventing a
condition, reading a phone number as one long number. Those are fixed in the prompts and
the question wording.

## 9. The thirty-second version, out loud

> Billions in benefits go unclaimed, and the reason usually isn't eligibility, it's the
> fifty-question form. Unclaimed is an Alexa+ screener that asks only the questions that
> could change your answer: after each answer it runs the benefits calculator both ways
> on every question it could ask next, and asks the one that actually moves something. That
> gets you from fifty questions to about seven. The AI never decides anything, it only
> talks: every dollar and every yes-or-no comes from PolicyEngine, an open-source model of
> the actual law. Anything it didn't ask about is shown as a "maybe", never as "you
> qualify", and across 475 test households it never once told someone they qualified when
> they didn't. Then it hands you the first step to apply, with a code to carry it to your
> phone.

## 10. Questions you'll get, and honest answers

**"How is this different from an AI chatbot that knows benefits rules?"**
A chatbot guesses from what it absorbed in training, and it can't tell you why. Here the
rules are a pinned open-source model of the law, the question choice is measurable, and
every claim traces to a calculation. Also: a chatbot can't tell you which question to ask
next, because that needs running the numbers both ways.

**"What was the hardest part?"**
Not the calculation. It was getting a voice model to keep honest books: to record what the
person actually said under the right question. The worst bug we found had Alexa record one
person's gig income as both job wages *and* self-employment, doubling their income, which
quietly moved them out of Medicaid and into a tax credit they couldn't get. The fix was to
ask about both kinds of pay in the same breath so there's only one place for the answer to
go.

**"What would you do differently?"**
Read the conversation transcripts earlier. The aggregate score said one case out of ten
failed; the transcript said *why*, and showed four other problems the score couldn't see.

**"What's not done?"**
Two states, not fifty. A real Echo would need Amazon's add-on access, which we don't have.
And the "maybe" mechanism is honest but it puts work on the person: they have to say yes to
settling it.

## 11. Where things live

- `docs/architecture.md`: the same system, told technically
- `docs/scorecard.md`: every measured number
- `docs/stages.md`: what was built when, and what each review found
- `docs/friction-log.md`: where Amazon's tools got in the way
- `docs/demo-script.md`: the shot list for the video

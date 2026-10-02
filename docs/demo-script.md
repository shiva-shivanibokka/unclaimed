# Demo video script (under 3 minutes)

Strongest moment first: a real conversation, the result on the screen, the plan on the phone. Recorded in the live simulator (Chrome, voice on), screen capture with system audio. Numbers said on screen come from the live run, not this script.

| Time | Show | Say (voiceover, or let Alexa speak) |
|---|---|---|
| 0:00–0:10 | Simulator, mic button | "About one in five people who qualify for the Earned Income Tax Credit never claim it (IRS), and other programs have gaps like it. This is Unclaimed, on Alexa+." |
| 0:10–1:10 | A screening by voice: a Los Angeles parent of two, about $18 an hour for 30 hours, $1,450 rent, $400 child care | Let the conversation play. Point out: Alexa reads back "$18 an hour, 30 hours a week" (units converted in code); it asks about child care because that answer can change CalFresh |
| 1:10–1:35 | The results screen (tiles) | "[N] programs, about [total] a year. Every number comes from PolicyEngine, an open-source rules engine; the model never does arithmetic or decides eligibility." |
| 1:35–2:00 | "Help me apply for CalFresh" → plan screen, scan the QR code with a phone | "Where to apply, what to bring, what happens next, from the agency's own pages, dated and cited. One scan and the application is on their phone." |
| 2:00–2:30 | Diagram from `docs/architecture.md`; the scorecard | "The Question Engine asks only what could change the answer: it runs what-ifs and stops when nothing left would. Tested on hundreds of households against the full answer: zero false 'you qualify'." (number from `docs/scorecard.md` on the day) |
| 2:30–2:50 | A declined question → "if ..." on screen | "Decline a question and the result says 'if', instead of guessing. Nothing is stored." |
| 2:50–3:00 | Repo + live link | "Open source, AGPL, running on AWS with a Strands agent on Bedrock. Try it at the link." |

Before recording: deploy is current; warm the services with one screening; close other tabs; check the QR code scans from the screen.

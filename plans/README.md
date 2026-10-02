# Plan cards

What to do next for each program, per state: how to apply, what to bring, what happens after, what trips people up. One YAML card per **application**: programs applied for together (the federal EITC and Child Tax Credit on one tax return; Medi-Cal and Covered California on one application) share a card. Cards live in `plans/<STATE>/`; a card whose process is the same in every state lives in `plans/US/`, and a state card for the same program replaces it.

Ways to apply (an agency's site, phone line, office finder) are defined once in `plans/channels.yaml` and named by id in the cards, so a phone number or link is never typed twice.

**What a card never holds** (single source): program names, amounts, income limits or any eligibility rule the calculator checks. Those come from the engine (`/programs`, `/calculate`, whose `why` facts say why someone qualifies). A card holds the agency's process, cited to the agency's own pages and checked on a date. The one exception is `not_calculated`: a condition the agency applies that the calculator can't check (which utility serves the home). Results then say "if ..." for that program instead of "you qualify".

```yaml
# plans/channels.yaml
benefitscal:
  how: online                 # online | phone | in_person | mail | tax_return | automatic
  where: BenefitsCal          # the agency or site, as people know it
  url: https://benefitscal.com/   # where the application starts (or the page that explains how)
  phone: "1-877-847-3663"     # optional

# plans/CA/calfresh.yaml
programs: [snap]              # ids from the engine's /programs (a program not calculated: see `name`)
state: CA                     # or US for a card that applies in every state
what: One plain sentence on what the program gives (no amounts, no rules).
apply: [benefitscal, county_office]   # channel ids, most convenient first
bring:                        # documents to have ready (checklist)
  - Photo ID
next:                         # what happens after applying, in order
  - An interview by phone
watch_out:                    # common mistakes and things people don't know
  - Report changes in income
not_calculated:               # optional: agency conditions the calculator can't check
  - Your electric company is PG&E, SCE or SDG&E.
handoff: https://benefitscal.com/   # what the QR code opens on the person's phone
sources:                      # agency pages that back every line above
  - https://www.cdss.ca.gov/inforesources/calfresh
last_verified: 2026-10-01     # when every source was last read and the card matched
```

`engine/tests/test_plans.py` checks every card on load (fields, https, no amounts, the handoff, each program covered once per state) and fails when a card hasn't been verified within `plans.MAX_AGE_DAYS`: re-read its sources and update `last_verified`.

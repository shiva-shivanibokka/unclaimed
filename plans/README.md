# Plan cards

What to do next for each program, per state: how to apply, what to bring, what happens after, what trips people up. One YAML file per program per state: `plans/<STATE>/<program>.yaml`. A program whose process is the same in every state (a federal tax credit filed on the federal return) has one card in `plans/US/`; a state card for the same program replaces it.

**What a card never holds** (single source): program names, amounts, income limits or any eligibility rule. Those come from the engine (`/programs`, `/calculate`, whose `explain` facts say why someone qualifies). A card holds only the agency's process, cited to the agency's own pages and checked on a date.

```yaml
program: snap                 # id from the engine's /programs
state: CA                     # or US for a card that applies in every state
what: One plain sentence on what the program gives (no amounts, no rules).
apply:                        # ways to apply, most convenient first
  - how: online               # online | phone | in_person | mail | tax_return | automatic
    where: BenefitsCal        # the agency or site, as people know it
    url: https://benefitscal.com/   # the page where the application starts
    phone: "1-877-847-3663"   # optional
bring:                        # documents to have ready (checklist)
  - Photo ID
next:                         # what happens after applying, in order
  - An interview by phone
watch_out:                    # common mistakes and things people don't know
  - Report changes in income
handoff: https://benefitscal.com/   # what the QR code opens on the person's phone
sources:                      # agency pages that back every line above
  - https://www.cdss.ca.gov/calfresh
last_verified: 2026-10-01     # when every source was last read and the card matched
```

Rules checked by `engine/tests/test_plans.py`: the program exists and covers the state; every required field is present; URLs are https; `handoff` is one of the `apply` URLs or sources; no dollar amounts or percentages in the text; `last_verified` is a date. Whether each source still says what the card says is checked by reading it (record the date in `last_verified`).

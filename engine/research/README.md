# engine/research

Throwaway scripts from the Sept 30 planning session. They produced the numbers in `docs/architecture.md`. They were run against **policyengine-us 2.18.2** on Python 3.11 in a temporary sandbox, not on this machine.

| Script | What it shows |
|---|---|
| `household_basics.py` | Builds a CA/IL household (parent + kids) and prints EITC, CTC, SNAP, WIC, Medicaid, … at several incomes. Other scripts import its `hh()` helper. |
| `batching_axes.py` | Latency of single-program calcs; 25 income variants in one simulation via `axes` (~0.3 s) |
| `latency_by_program.py` | Warm latency per program; batching 8/16/32 households in one simulation |
| `county_effect.py` | County changes the ACA credit ($6,610 LA vs $13,221 Modoc) and the CalWORKs grant; default county = first in state |
| `trace_defaulted_inputs.py` | Tracing shows 283 inputs the engine read but we never provided |
| `followup_sensitivity.py` | What-if sensitivity of follow-up questions (child care, pregnancy, job insurance, savings, …): the core Question Engine idea |

Run from this folder after installing the engine (Python 3.11+):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "policyengine-us==2.18.2"
python household_basics.py
```

First import takes ~15 s (the engine loads parameters). Peak memory is ~1 GB.

"""Programs we screen for, mapped to PolicyEngine-US variables (policyengine-us 2.18.2).

`variable` is summed over the household. Monthly variables are calculated for the
screening month, yearly ones for the screening year. `per` is how we report the
amount to the person: tax credits per year, everything else per month.
"""

from dataclasses import dataclass
from typing import Literal

# The states Unclaimed serves. Defined only here; everything else imports it.
SUPPORTED_STATES: tuple[str, ...] = ("CA", "IL")


@dataclass(frozen=True)
class Program:
    id: str
    name: str
    variable: str
    per: Literal["month", "year"]
    states: tuple[str, ...] = SUPPORTED_STATES
    # Health coverage: the engine's value is the cost of coverage, not cash, so we
    # report who is eligible (from `eligibility`, a person-level bool) instead of dollars.
    eligibility: str | None = None


PROGRAMS: tuple[Program, ...] = (
    # Federal, both states
    Program("snap", "SNAP (CalFresh in California)", "snap", "month"),
    Program("wic", "WIC", "wic", "month"),
    Program("school_meals", "Free or reduced-price school meals", "free_school_meals", "month"),
    Program("lifeline", "Lifeline phone and internet discount", "lifeline", "month"),
    Program("ssi", "Supplemental Security Income (SSI)", "ssi", "month"),
    Program("eitc", "Federal Earned Income Tax Credit", "eitc", "year"),
    Program("ctc", "Federal Child Tax Credit", "ctc_value", "year"),
    Program("aca_ptc", "ACA health insurance premium tax credit", "aca_ptc", "month"),
    Program("medicaid", "Medicaid (Medi-Cal in California)", "medicaid", "month", eligibility="is_medicaid_eligible"),
    Program("chip", "CHIP (children's health insurance)", "chip", "month", eligibility="is_chip_eligible"),
    # California
    Program("ca_calworks", "CalWORKs cash aid", "ca_tanf", "month", ("CA",)),
    Program("ca_eitc", "California Earned Income Tax Credit (CalEITC)", "ca_eitc", "year", ("CA",)),
    Program("ca_yctc", "California Young Child Tax Credit", "ca_yctc", "year", ("CA",)),
    Program("ca_care", "CARE utility discount", "ca_care", "month", ("CA",)),
    Program("ca_fera", "FERA utility discount", "ca_fera", "month", ("CA",)),
    Program("ca_child_care", "California child care subsidy", "ca_child_care_subsidies", "month", ("CA",)),
    # Illinois
    Program("il_tanf", "Illinois TANF cash assistance", "il_tanf", "month", ("IL",)),
    Program("il_eitc", "Illinois Earned Income Tax Credit", "il_eitc", "year", ("IL",)),
    Program("il_ctc", "Illinois Child Tax Credit", "il_ctc", "year", ("IL",)),
    Program("il_liheap", "Illinois LIHEAP energy assistance", "il_liheap", "year", ("IL",)),
    Program("il_child_care", "Illinois Child Care Assistance Program (CCAP)", "il_ccap", "month", ("IL",)),
)

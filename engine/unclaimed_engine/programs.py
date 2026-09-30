"""Programs we screen for, mapped to PolicyEngine-US variables (version pinned in pyproject.toml).

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
    # Engine bool that fully decides eligibility (income tests included). Set it where the
    # amount depends on expenses we may not know: a $0 phone bill gives a $0 Lifeline
    # discount even when the household qualifies. Not for tax credits, SSI or the ACA
    # credit: their "eligible" flags skip the income phase-out, so eligible = amount > 0.
    eligibility: str | None = None
    # Health coverage: the engine's value is the cost of coverage, not cash, so we
    # report who is covered instead of dollars.
    coverage: bool = False
    # Engine variables whose values explain the result ("why you qualify / don't").
    # Labels and units come from PolicyEngine; the AI phrases them for the person.
    explain: tuple[str, ...] = ()
    # The program's name in a state where it goes by another name (CalFresh, Medi-Cal).
    state_names: tuple[tuple[str, str], ...] = ()

    def name_in(self, state: str) -> str:
        return dict(self.state_names).get(state, self.name)


PROGRAMS: tuple[Program, ...] = (
    # Federal, both states
    Program("snap", "SNAP food assistance", "snap", "month", state_names=(("CA", "CalFresh"),), eligibility="is_snap_eligible",
            explain=("meets_snap_gross_income_test", "meets_snap_net_income_test", "meets_snap_asset_test", "meets_snap_work_requirements", "snap_gross_test_income_fpg_ratio", "snap_max_allotment")),
    Program("wic", "WIC", "wic", "month", eligibility="is_wic_eligible",
            explain=("wic_category", "meets_wic_income_test", "wic_income_limit", "meets_wic_categorical_eligibility")),
    Program("school_meals", "Free or reduced-price school meals", "school_meal_net_subsidy", "month",
            explain=("school_meal_tier", "school_meal_fpg_ratio", "meets_school_meal_categorical_eligibility")),
    Program("lifeline", "Lifeline phone and internet discount", "lifeline", "month", eligibility="is_lifeline_eligible",
            explain=("is_lifeline_income_eligible",)),
    Program("ssi", "Supplemental Security Income (SSI)", "ssi", "month",
            explain=("is_ssi_eligible", "is_ssi_disabled", "meets_ssi_resource_test")),
    Program("eitc", "Federal Earned Income Tax Credit", "eitc", "year",
            explain=("eitc_eligible", "eitc_maximum", "eitc_phased_in", "eitc_phase_out_start", "eitc_agi_limit")),
    Program("ctc", "Federal Child Tax Credit", "ctc_value", "year",
            explain=("ctc_maximum", "ctc_phase_in", "ctc_refundable_maximum", "ctc_limiting_tax_liability")),
    Program("aca_ptc", "ACA health insurance premium tax credit", "aca_ptc", "month",
            explain=("aca_magi_fraction", "is_aca_ptc_eligible", "is_aca_eshi_eligible")),
    Program("medicaid", "Medicaid", "medicaid", "month", state_names=(("CA", "Medi-Cal"),), eligibility="is_medicaid_eligible", coverage=True,
            explain=("medicaid_category", "medicaid_income_level", "is_medicaid_immigration_status_eligible", "is_medicaid_ineligible_due_to_work_requirement")),
    Program("chip", "CHIP (children's health insurance)", "chip", "month", eligibility="is_chip_eligible", coverage=True,
            explain=("chip_category", "medicaid_income_level")),
    # California
    Program("ca_calworks", "CalWORKs cash aid", "ca_tanf", "month", ("CA",), eligibility="ca_tanf_eligible",
            explain=("ca_tanf_eligible", "ca_tanf_financial_eligible", "ca_tanf_income_limit", "ca_tanf_maximum_payment")),
    Program("ca_eitc", "California Earned Income Tax Credit (CalEITC)", "ca_eitc", "year", ("CA",),
            explain=("ca_eitc_eligible",)),
    Program("ca_yctc", "California Young Child Tax Credit", "ca_yctc", "year", ("CA",),
            explain=("ca_eitc_eligible",)),
    Program("ca_care", "CARE utility discount", "ca_care", "month", ("CA",), eligibility="ca_care_eligible",
            explain=("ca_care_income_eligible", "ca_care_categorically_eligible")),
    Program("ca_fera", "FERA utility discount", "ca_fera", "month", ("CA",), eligibility="ca_fera_eligible",
            explain=("ca_fera_eligible",)),
    Program("ca_child_care", "California child care subsidy", "ca_child_care_subsidies", "month", ("CA",),
            explain=("ca_child_care_income_eligible",)),
    # Illinois
    Program("il_tanf", "Illinois TANF cash assistance", "il_tanf", "month", ("IL",), eligibility="il_tanf_eligible",
            explain=("il_tanf_income_eligible", "il_tanf_non_financial_eligible", "il_tanf_countable_income_for_initial_eligibility", "il_tanf_payment_level_for_initial_eligibility")),
    Program("il_eitc", "Illinois Earned Income Tax Credit", "il_eitc", "year", ("IL",),
            explain=("eitc",)),
    Program("il_ctc", "Illinois Child Tax Credit", "il_ctc", "year", ("IL",),
            explain=("il_eitc",)),
    Program("il_liheap", "Illinois LIHEAP energy assistance", "il_liheap", "year", ("IL",), eligibility="il_liheap_eligible",
            explain=("il_liheap_income_eligible",)),
    Program("il_child_care", "Illinois Child Care Assistance Program (CCAP)", "il_ccap", "month", ("IL",), eligibility="il_ccap_eligible",
            explain=("il_ccap_income_eligible", "il_ccap_parent_meets_working_requirements")),
)

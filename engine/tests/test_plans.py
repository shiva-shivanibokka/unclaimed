"""Plan cards: complete, cited, and free of amounts and rules (those come from the engine)."""

import pytest

from unclaimed_engine import plans
from unclaimed_engine.programs import PROGRAMS

GOOD = """program: snap
state: CA
what: Money for food on a card.
apply:
  - {how: online, where: BenefitsCal, url: "https://benefitscal.com/"}
bring: [Photo ID]
next: [An interview]
watch_out: [Report changes]
handoff: https://benefitscal.com/
sources: ["https://www.cdss.ca.gov/calfresh"]
last_verified: 2026-10-01
"""


def write(tmp_path, text, state="CA", program="snap"):
    (tmp_path / state).mkdir(exist_ok=True)
    (tmp_path / state / f"{program}.yaml").write_text(text)
    return tmp_path


def test_every_program_has_a_card_in_every_state_it_covers():
    missing = [(s, p.id) for p in PROGRAMS for s in p.states if p.id not in plans.for_state(s)]
    assert not missing


def test_a_good_card_loads(tmp_path):
    assert plans.load.__wrapped__(write(tmp_path, GOOD))[("CA", "snap")]["handoff"] == "https://benefitscal.com/"


@pytest.mark.parametrize("change, problem", [
    (("what: Money for food on a card.", "what: Up to $975 a month for food."), "amounts"),
    (("watch_out: [Report changes]", "watch_out: [Only if under 130% of poverty]"), "amounts"),
    (("handoff: https://benefitscal.com/", "handoff: https://example.com/"), "handoff"),
    (('url: "https://benefitscal.com/"', 'url: "http://benefitscal.com/"'), "https"),
    (("how: online", "how: carrier_pigeon"), "how"),
    (("last_verified: 2026-10-01", "last_verified: recently"), "date"),
    (("bring: [Photo ID]\n", ""), "fields"),
    (("program: snap", "program: snap\nprogram: wic"), "duplicate"),
])
def test_bad_cards_are_refused(tmp_path, change, problem):
    with pytest.raises(ValueError, match=problem):
        plans.load.__wrapped__(write(tmp_path, GOOD.replace(*change)))


def test_card_must_sit_where_its_program_and_state_say(tmp_path):
    with pytest.raises(ValueError, match="place"):
        plans.load.__wrapped__(write(tmp_path, GOOD, state="IL"))


def test_a_program_the_engine_does_not_model_needs_its_own_name(tmp_path):
    text = GOOD.replace("program: snap", "program: liheap")
    with pytest.raises(ValueError, match="name"):
        plans.load.__wrapped__(write(tmp_path, text, program="liheap"))
    assert plans.load.__wrapped__(write(tmp_path, "name: Energy help\n" + text, program="liheap"))

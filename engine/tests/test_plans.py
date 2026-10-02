"""Plan cards: complete, cited, current, and free of amounts and rules (those come from the
engine)."""

import pytest

from unclaimed_engine import plans
from unclaimed_engine.programs import PROGRAMS

CHANNELS = """benefitscal:
  how: online
  where: BenefitsCal
  url: https://benefitscal.com/
  source: https://www.cdss.ca.gov/inforesources/calfresh
"""
CARD = """programs: [snap]
state: CA
what: Money for food on a card.
apply: [benefitscal]
bring: [Photo ID]
next: [An interview]
watch_out: [Report changes]
handoff: https://benefitscal.com/
sources: ["https://www.cdss.ca.gov/inforesources/calfresh"]
last_verified: 2026-10-01
"""


def write(tmp_path, card=CARD, name="calfresh", state="CA", channels=CHANNELS):
    (tmp_path / "channels.yaml").write_text(channels)
    (tmp_path / state).mkdir(exist_ok=True)
    (tmp_path / state / f"{name}.yaml").write_text(card)
    return tmp_path


def test_every_program_has_a_card_in_every_state_it_covers():
    missing = [(s, p.id) for p in PROGRAMS for s in p.states
               if not any(p.id in c["programs"] for c in plans.for_state(s).values())]
    assert not missing


def test_every_card_was_verified_recently():
    # Phone lines, links and steps change: re-read the sources and update last_verified.
    assert not plans.stale()


def test_a_good_card_loads_with_its_channels_spelled_out(tmp_path):
    plans.load.__wrapped__(write(tmp_path))
    channels, cards = plans.load.__wrapped__(tmp_path)
    assert cards[("CA", "calfresh")]["apply"] == ["benefitscal"] and channels["benefitscal"]["where"] == "BenefitsCal"


@pytest.mark.parametrize("change, problem", [
    (("what: Money for food on a card.", "what: Up to $975 a month for food."), "amounts"),
    (("watch_out: [Report changes]", "watch_out: [Only if under 130% of poverty]"), "amounts"),
    (("watch_out: [Report changes]", "watch_out: [Report changes]\nnot_calculated: [Under 50 percent of median]"), "amounts"),
    (("handoff: https://benefitscal.com/", "handoff: https://example.com/"), "handoff"),
    (("apply: [benefitscal]", "apply: [carrier_pigeon]"), "channels"),
    (("last_verified: 2026-10-01", "last_verified: recently"), "date"),
    (("bring: [Photo ID]\n", ""), "fields"),
    (("state: CA", "state: CA\nstate: IL"), "duplicate"),
    (("programs: [snap]", "programs: [ca_calworks, snap]\nname: Food and cash"), "names"),
])
def test_bad_cards_are_refused(tmp_path, change, problem):
    with pytest.raises(ValueError, match=problem):
        plans.load.__wrapped__(write(tmp_path, CARD.replace(*change)))


def test_bad_channels_are_refused(tmp_path):
    with pytest.raises(ValueError, match="https"):
        plans.load.__wrapped__(write(tmp_path, channels=CHANNELS.replace("https://benefitscal", "http://benefitscal")))


def test_a_program_gets_one_card_per_state(tmp_path):
    write(tmp_path)
    with pytest.raises(ValueError, match="already has a card"):
        plans.load.__wrapped__(write(tmp_path, name="calfresh_again"))


def test_card_must_sit_in_its_state_and_programs_must_be_there(tmp_path):
    with pytest.raises(ValueError, match="folder"):
        plans.load.__wrapped__(write(tmp_path, state="IL"))
    with pytest.raises(ValueError, match="isn't in CA"):
        plans.load.__wrapped__(write(tmp_path, CARD.replace("[snap]", "[il_tanf]")))


def test_a_program_the_engine_does_not_model_needs_its_own_card_and_name(tmp_path):
    card = CARD.replace("[snap]", "[liheap]")
    with pytest.raises(ValueError, match="name"):
        plans.load.__wrapped__(write(tmp_path, card, name="liheap"))
    assert plans.load.__wrapped__(write(tmp_path, "name: Energy help\n" + card, name="liheap"))

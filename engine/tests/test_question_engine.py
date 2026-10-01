"""The generic Question Engine (no rules engine involved: a fake calculator)."""

import question_engine as qe


class Fake:
    """Outcome 'cash' qualifies when income < 1000; its value is 1000 - income. 'bonus' is
    worth 10 * pets. Tracks how many times it's called."""

    def __init__(self):
        self.calls = 0

    def evaluate(self, state, changes):
        self.calls += 1
        out = []
        for change in changes:
            s = {**state, **change}
            out.append({"cash": (s["income"] < 1000, max(0, 1000 - s["income"])), "bonus": (True, 10 * s["pets"])})
        return out


STATE = {"income": 0, "pets": 0}


def test_flips_beat_dollars_and_cost_divides():
    income = qe.Candidate("income", 0, 2000, cost=1)
    pets = qe.Candidate("pets", 0, 50, cost=1)  # $500 swing, no flip
    d = qe.decide(STATE, [pets, income], Fake(), flip_weight=1000, stop_below=25)
    assert d.ask == income and d.ranked[0].flips == ("cash",)
    expensive = qe.Candidate("income", 0, 2000, cost=10)
    d = qe.decide(STATE, [pets, expensive], Fake(), flip_weight=1000, stop_below=25)
    assert d.ask == pets  # (1000 + 1000) / 10 = 200 < 500


def test_stops_when_nothing_flips_or_moves_enough():
    d = qe.decide(STATE, [qe.Candidate("pets", 0, 2)], Fake(), flip_weight=1000, stop_below=25)
    assert d.stop  # $20 swing, no flip


def test_a_costly_flip_still_prevents_stopping():
    d = qe.decide(STATE, [qe.Candidate("income", 0, 2000, cost=1000)], Fake(), flip_weight=1000, stop_below=25)
    assert not d.stop


def test_one_batched_call_per_decision():
    calc = Fake()
    qe.decide(STATE, [qe.Candidate("income", 0, 2000), qe.Candidate("pets", 0, 50)], calc, flip_weight=1000, stop_below=25)
    assert calc.calls == 1


def test_no_candidates_means_stop():
    assert qe.decide(STATE, [], Fake(), flip_weight=1000, stop_below=25).stop

from simulation.engine.deterministic import build_rng


def test_rng_is_repeatable_for_same_seed():
    first = build_rng(42).randint(1, 1000)
    second = build_rng(42).randint(1, 1000)
    assert first == second


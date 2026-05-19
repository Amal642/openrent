from simulation.policies.production_policy import ProductionPolicy


def test_policy_capability_flags_are_exposed():
    policy = ProductionPolicy()

    assert policy.allow_phone_request is True
    assert policy.allow_negotiation is False
    assert policy.max_followups >= 1


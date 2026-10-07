from scripts import persona_names


def _fleet(monkeypatch):
    monkeypatch.setattr(persona_names, "used_names", lambda: {
        "katherine": [(36, "tenant", True), (38, "tenant", True)],
        "george": [(34, "partner", True), (43, "partner", True)],
        "jack": [(39, "tenant", True)],
        "amy": [(39, "partner", True)],
    })


def test_clashes_are_names_on_more_than_one_account(monkeypatch):
    _fleet(monkeypatch)
    assert set(persona_names.name_clashes()) == {"katherine", "george"}


def test_clashes_can_be_limited_to_new_accounts(monkeypatch):
    _fleet(monkeypatch)
    assert set(persona_names.name_clashes([43, 39])) == {"george"}
    assert persona_names.name_clashes([39]) == {}


def test_suggestions_skip_every_used_name(monkeypatch):
    template = persona_names.PERSONA_TEMPLATES["high_earner_tech_couple"]
    taken = {template["names"]["primary"][0].lower(): [(1, "tenant", True)],
             template["names"]["partner"][0].lower(): [(2, "partner", False)]}
    monkeypatch.setattr(persona_names, "used_names", lambda: taken)

    primary, partner = persona_names.free_names("high_earner_tech_couple")

    assert template["names"]["primary"][0] not in primary
    assert template["names"]["partner"][0] not in partner
    assert len(primary) == len(template["names"]["primary"]) - 1

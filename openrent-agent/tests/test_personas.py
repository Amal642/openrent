from app.ai.personas import get_persona_template, materialize_persona


def test_single_income_persona_exposes_screening_and_boundary_metadata():
    template = get_persona_template("single_income_couple")
    persona = materialize_persona(template)

    assert persona["persona_type"] == "single_income_couple"
    assert persona["persona_partner_name"]
    assert persona["persona_partner_job"] in {
        "currently at home",
        "full-time parent",
        "homemaker",
    }
    assert "one applicant is working full-time" in persona["screening_posture"]
    assert "do not share the tenant mobile early" in persona["phone_boundary"]

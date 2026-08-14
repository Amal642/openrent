"""Guards persona internal consistency: every job a persona can be assigned must
plausibly earn the income its persona_type will claim to landlords.

Regression for the "Teaching Assistant claiming ~GBP4,700/month" failure, where a
low-wage job sat in a persona pool whose income band assumed a mid/high earner,
so the stated income contradicted the stated job and landlords caught it.
"""
import pytest

from app.ai.personas import (
    PERSONA_TEMPLATES,
    income_band_for,
    job_salary_band,
    JOB_SALARY_BANDS,
    NON_EARNING_ROLES,
)

# A job may top out slightly below the per-earner floor (London weighting,
# senior end of a role). Anything below this fraction is an implausible pairing.
TOLERANCE = 0.95


def _earner_floor(persona_type):
    """Minimum annual income a single earner of this type must be able to reach.

    Single-income types: the sole earner must reach the whole band floor.
    Dual-income types: each earner carries roughly half.
    """
    low, _high, dual = income_band_for(persona_type)
    return low / 2 if dual else low


@pytest.mark.parametrize("persona_type", sorted(PERSONA_TEMPLATES))
def test_primary_jobs_can_reach_income_floor(persona_type):
    floor = _earner_floor(persona_type)
    for job in PERSONA_TEMPLATES[persona_type]["jobs"]["primary"]:
        job_max = job_salary_band(job)[1]
        assert job_max >= floor * TOLERANCE, (
            f"{persona_type}: primary job {job!r} tops out at GBP{job_max:,} but the "
            f"persona will claim income implying ~GBP{floor:,.0f}/earner — implausible pairing."
        )


@pytest.mark.parametrize("persona_type", sorted(PERSONA_TEMPLATES))
def test_partner_jobs_consistent_with_band(persona_type):
    low, _high, dual = income_band_for(persona_type)
    for job in PERSONA_TEMPLATES[persona_type]["jobs"]["partner"]:
        if not dual:
            # A single-income couple's partner must be a non-earning role,
            # otherwise the "one earner" income framing is a lie.
            assert job in NON_EARNING_ROLES, (
                f"{persona_type}: single-income partner role {job!r} should be non-earning "
                f"(one of {sorted(NON_EARNING_ROLES)})."
            )
        else:
            job_max = job_salary_band(job)[1]
            assert job_max >= (low / 2) * TOLERANCE, (
                f"{persona_type}: partner job {job!r} tops out at GBP{job_max:,}, below the "
                f"~GBP{low / 2:,.0f}/earner this couple's income implies."
            )


def test_every_pool_job_has_an_explicit_salary_band():
    """No pool job may rely on the fallback band — keeps JOB_SALARY_BANDS complete."""
    missing = set()
    for tpl in PERSONA_TEMPLATES.values():
        for slot in ("primary", "partner"):
            for job in tpl["jobs"][slot]:
                if job in NON_EARNING_ROLES:
                    continue
                if job not in JOB_SALARY_BANDS:
                    missing.add(job)
    assert not missing, f"jobs missing from JOB_SALARY_BANDS: {sorted(missing)}"


def test_teaching_assistant_not_in_any_earner_pool():
    """Explicit regression: the specific job that triggered this work."""
    for persona_type, tpl in PERSONA_TEMPLATES.items():
        assert "Teaching Assistant" not in tpl["jobs"]["primary"], (
            f"{persona_type}: 'Teaching Assistant' is back in a primary earner pool."
        )

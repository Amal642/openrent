# New account batch — Oct 2026 (15 accounts) — v3

Outlook signup: https://signup.live.com — country **United Kingdom** for all.
Password: your own (do NOT write it in this file — it's in the repo tree).

v3: every account is a dual-income professional couple on one of the three
top income tiers, so the persona can credibly pass affordability on almost any
listing. Income comes from persona type (`INCOME_BANDS` in app/ai/personas.py):

- high_earner_tech_couple / high_earner_legal_finance_couple: £120k–145k combined
- engineer_consultant_couple: £95k–120k combined

All job titles are in `JOB_SALARY_BANDS`, so stated income never contradicts
the stated job. Types are mixed (6 / 5 / 4) so accounts don't share one skeleton.

## Created (accounts 1–5)

| # | Name | Email | DOB | Persona type | Persona job | Partner | Partner job |
|---|------|-------|-----|--------------|-------------|---------|-------------|
| 1 | Jack Turner | jturner_92@outlook.com | 12 Apr 1992 | high_earner_tech_couple | Management Consultant | Amy | Senior Product Manager |
| 2 | Rebecca Hughes | rebeccahughes.94@outlook.com | 03 Sep 1994 | high_earner_tech_couple | IT Consultant | Tom | Senior Software Engineer |
| 3 | Liam Walsh | lwalsh19901@outlook.com | 27 Jan 1990 | engineer_consultant_couple | Solutions Architect | Katie | Management Consultant |
| 4 | Sophie Clarke | sophie.clarke19931@outlook.com | 18 Jun 1993 | high_earner_legal_finance_couple | Financial Consultant | Oliver | Corporate Solicitor |
| 5 | Mark Robinson | markrobinson19881@outlook.com | 09 Nov 1988 | engineer_consultant_couple | Business Consultant | Lisa | Structural Engineer |

**In prod DB (2026-10-05):** 1 Jack = acct **39** (proxy 23), 2 Rebecca = acct **40**
(proxy 21), 3 Liam = acct **41** (proxy 19). Created INACTIVE with empty password,
mobile_number 07783129181 (shared line until per-account numbers). Rollback = delete 39-41.

## To create (accounts 6–15)

| # | First | Last | DOB | Username A | Username B | Persona type | Persona job | Partner | Partner job |
|---|-------|------|-----|-----------|-----------|--------------|-------------|---------|-------------|
| 6 | Hannah | Wood | 22 Mar 1995 | hannahwood95 | hannah.wood95 | high_earner_tech_couple | Data Scientist | George | Management Consultant |
| 7 | Ryan | Patel | 14 Jul 1991 | ryanpatel91 | rpatel1991 | high_earner_tech_couple | Solutions Architect | Nisha | Senior UX Lead |
| 8 | Gemma | Foster | 05 Dec 1992 | gemmafoster92 | gfoster92 | high_earner_legal_finance_couple | Management Consultant | Dan | Commercial Solicitor |
| 9 | Adam | Khan | 30 Aug 1989 | adamkhan89 | adam.khan1989 | high_earner_legal_finance_couple | Financial Consultant | Sana | Associate Solicitor |
| 10 | Lucy | Bennett | 11 Feb 1996 | lucybennett96 | lbennett1996 | high_earner_tech_couple | IT Consultant | Josh | Product Manager |
| 11 | Chris | Morgan | 17 Oct 1990 | chrismorgan90 | cmorgan.90 | engineer_consultant_couple | Management Consultant | Jade | Structural Engineer |
| 12 | Zara | Ali | 25 May 1993 | zaraali93 | zara.ali1993 | high_earner_legal_finance_couple | Legal Counsel | Imran | Management Consultant |
| 13 | Sam | Cooper | 08 Mar 1994 | samcooper94 | scooper1994 | high_earner_tech_couple | Business Consultant | Ellie | Senior Software Engineer |
| 14 | Kate | Mitchell | 19 Aug 1991 | katemitchell91 | kmitchell91 | engineer_consultant_couple | IT Consultant | Steve | Civil Engineer |
| 15 | Joe | Davies | 02 Jan 1989 | joedavies89 | joe.davies1989 | high_earner_legal_finance_couple | Management Consultant | Rachel | Commercial Solicitor |

## Fill in as you go (6–15)

| # | Email actually created | SIM / phone used | Created (date) | OpenRent verified? |
|---|------------------------|------------------|----------------|--------------------|
| 6 | | | | |
| 7 | | | | |
| 8 | | | | |
| 9 | | | | |
| 10 | | | | |
| 11 | | | | |
| 12 | | | | |
| 13 | | | | |
| 14 | | | | |
| 15 | | | | |

## Provisioning TODO (Claude)

- Surname consistency: `persona_surnames()` in app/ai/prompts.py picks a
  random pool surname, so if a landlord asks for full names the AI would say
  e.g. "Jack Whitfield" while the OpenRent profile says "Jack Turner". Must be
  fixed (store real surname per account) before these go live.
- Proxies (avoid Static Proxy 1/2/3/8), areas, search_profiles, persona fields.

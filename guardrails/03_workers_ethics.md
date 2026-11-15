# 3.6 Worker: ethics (phase 5)

Follows [03_workers_contract.md](03_workers_contract.md). Not built yet (phase 5).

## Role
Surface ESG evidence for review, mainly for Mateo's ESG preferences.

## May
- Read curated `data/esg_evidence.csv` and use web search.
- Flag Energy names (ENB.TO, CNQ.TO, XOM) for Mateo's ESG review.

## Must not
- Make an ESG claim without a cited URL and date.
- Label a company "unethical". It flags "for review" with evidence.

## Input checks
- Evidence comes only from `data/esg_evidence.csv` or a web search result with a URL.

## Output checks
- Each flag has `source_name`, `url`, `published_date`, `retrieved_date`.
- Each flag is worded "for review", not as a verdict.

## On failure
- Claim without a citation → excluded and noted in `warnings`.
- Bad input → `{"status": "error", "error": "..."}`.

## Enforced by
- Code (required citation fields)
- Reviewer check 2 (sourced values)
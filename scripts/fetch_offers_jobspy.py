# /// script
# requires-python = ">=3.10"
# dependencies = ["python-jobspy", "pandas"]
# ///
"""OPTIONAL second source -- LOCAL ONLY, on demand, never in GitHub Actions.

python-jobspy scrapes Indeed / ZipRecruiter, whose terms of service forbid
automated collection and redistribution. So this script:
  1. runs only on my laptop, by hand;
  2. uses Indeed and ZipRecruiter only (not LinkedIn, the platform that litigates,
     nor Google's results pages);
  3. writes to a git-ignored file; every offer it produces is marked
     publishable=False by merge_offer_sources.py and never reaches the public site.

python-jobspy needs Python >= 3.10 (macOS ships 3.9), so run it through uv:
    python3 -m pip install --user uv
    python3 -m uv run scripts/fetch_offers_jobspy.py            # France
    python3 -m uv run scripts/fetch_offers_jobspy.py canada     # Canada too
"""
import json
import os
import sys
import time

import pandas as pd
from jobspy import scrape_jobs

SITES = ["indeed", "zip_recruiter"]   # deliberately no linkedin / google
SEARCH_TERMS = ["stage data scientist", "stage machine learning", "stage intelligence artificielle"]
RESULTS_WANTED = 20
HOURS_OLD = 336   # 14 days: runs by hand, occasionally
COUNTRY = (sys.argv[1] if len(sys.argv) > 1 else "france").lower()
LOCATION = {"france": "France", "canada": "Canada"}.get(COUNTRY, COUNTRY.title())


def safe(row, key, default=None):
    # pandas NaN is truthy: `row.get(key) or default` would return NaN itself
    v = row.get(key)
    return v if pd.notna(v) else default


def main():
    frames = []
    for term in SEARCH_TERMS:
        print(f"Scraping {SITES} for {term!r} in {LOCATION}...")
        try:
            frames.append(scrape_jobs(site_name=SITES, search_term=term, location=LOCATION,
                                      results_wanted=RESULTS_WANTED, hours_old=HOURS_OLD,
                                      country_indeed=LOCATION))
        except Exception as e:   # one failed search must not lose the others
            print(f"  failed: {e}")
    if not frames:
        raise SystemExit("Nothing scraped.")
    jobs = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["id"])
    print(f"Found {len(jobs)} raw results")

    # jobspy normalizes job_type and tags French "Stage" postings as "internship"
    interns = jobs[jobs["job_type"].fillna("").astype(str).str.contains("internship", case=False)]
    print(f"{len(interns)} of those are tagged job_type=internship")

    offers = [{
        "id": f"jobspy_{safe(r, 'id')}",
        "source": safe(r, "site"),
        "title": safe(r, "title"),
        "company": safe(r, "company"),
        "location": safe(r, "location"),
        "description": safe(r, "description", ""),
        "url": safe(r, "job_url"),
        "date_posted": str(safe(r, "date_posted")) if safe(r, "date_posted") else None,
    } for _, r in interns.iterrows()]

    os.makedirs("data/offers", exist_ok=True)
    with open("data/offers/jobspy_offers.json", "w", encoding="utf-8") as f:
        json.dump({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "country": COUNTRY, "offers": offers}, f, indent=2, ensure_ascii=False)
    print(f"Wrote data/offers/jobspy_offers.json ({len(offers)} offers) -- gitignored, local only")


if __name__ == "__main__":
    main()

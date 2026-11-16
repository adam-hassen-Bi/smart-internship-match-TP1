"""Merge every source into one file -> data/offers/merged_offers.json (local only).

Inputs:
  data/offers/raw_offers.json     public job APIs (fetch_offers.py), already in the
                                  common schema, `publishable` set per source
  data/offers/jobspy_offers.json  OPTIONAL scraped Indeed/ZipRecruiter offers
                                  (fetch_offers_jobspy.py), always publishable=False

Checks every offer has the common fields, and removes an offer found on two
sources (same title + company), keeping the publishable copy when there is one, so
an offer is never hidden from the dashboard just because a scraper saw it too.
"""
import json
import os
import re

RAW_PATH = "data/offers/raw_offers.json"
JOBSPY_PATH = "data/offers/jobspy_offers.json"
MERGED_PATH = "data/offers/merged_offers.json"
FIELDS = ["id", "source", "title", "company", "location", "description", "url", "date_posted",
          "contract_type", "is_apprenticeship", "accessible_disability", "matched_search", "publishable"]


def load(path, required=True):
    if not os.path.exists(path):
        if required:
            raise SystemExit(f"{path} not found -- run scripts/fetch_offers.py first.")
        print(f"{path} not found -- skipping (fine if the optional jobspy step was not run).")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    api = load(RAW_PATH)
    api_offers = api["offers"]
    jobspy = load(JOBSPY_PATH, required=False)
    jobspy_offers = [{**o, "contract_type": "Internship", "is_apprenticeship": False, "accessible_disability": None,
                      "matched_search": None, "publishable": False} for o in (jobspy or {}).get("offers", [])]

    merged, by_key, n_dup = [], {}, 0
    for o in api_offers + jobspy_offers:
        o = {k: o.get(k) for k in FIELDS} | {k: v for k, v in o.items() if k not in FIELDS}
        key = (re.sub(r"\W+", "", (o["title"] or "").lower()), re.sub(r"\W+", "", (o["company"] or "").lower()))
        if key in by_key:
            n_dup += 1
            i = by_key[key]
            if o["publishable"] and not merged[i]["publishable"]:
                merged[i] = o
            continue
        by_key[key] = len(merged)
        merged.append(o)

    per_source = {}
    for o in merged:
        per_source[o["source"]] = per_source.get(o["source"], 0) + 1
    print(f"Merged {len(api_offers)} API offers + {len(jobspy_offers)} jobspy offers "
          f"-> {len(merged)} ({n_dup} duplicates removed)")
    print("  per source: " + ", ".join(f"{k} {v}" for k, v in sorted(per_source.items(), key=lambda kv: -kv[1])))
    print(f"  publishable: {sum(o['publishable'] for o in merged)} of {len(merged)}")

    os.makedirs("data/offers", exist_ok=True)
    with open(MERGED_PATH, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": api.get("fetched_at"), "offers": merged}, f, indent=2, ensure_ascii=False)
    print(f"Wrote {MERGED_PATH} -- gitignored, local only")


if __name__ == "__main__":
    main()

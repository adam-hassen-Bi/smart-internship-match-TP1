"""Score every structured offer against my profile -> two outputs.

  data/offers/matches_all_local.json  every source, git-ignored, for me only
  docs/data/matches.json              publishable sources only, committed -- without the
                                      offer text or quotes (title, company, link, skills, score)

THE KPI (my design, see score_offer) -- "level-weighted coverage, discounted when
the offer says too little to judge":

  required  = the offer's extracted skills, normalized (case, spelling, aliases),
              de-duplicated, soft skills removed
  matched   = my profile skills found in `required`
  gaps      = skills in `required` that I do not have
  coverage  = |matched| / |required|                  -- "how much of the offer do I cover?"
  weighted  = sum(level/5 for matched) / |required|   -- same, but a level-2 skill counts less than a level-5 one
  confidence= min(1, |required| / 3)                   -- an offer naming 1 skill tells me little
  score     = weighted x confidence                    -- used for the ranking

Why not plain coverage: an offer listing only "Python" would score 100 % and rank
above a detailed data-science offer where I cover 6 skills out of 8. Why weight by
level: claiming a match on a skill I rate 2/5 is weaker than on one I rate 5/5,
and draft_cv.py quotes the evidence of every matched skill.
"""
import csv
import json
import os
import time

from skills import NOT_A_SKILL, profile_index, skill_key

MIN_REQUIRED_FOR_FULL_CONFIDENCE = 3
PRIVATE_FIELDS = {"description", "responsibilities", "experience_required", "compensation_mentioned", "text_hash"}
HIGH_MATCH_SCORE = 0.4        # "worth applying" threshold, used by the dashboard and the monitor
SCORE_BINS = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]


def load_profile(path="data/profile/my_skills.csv"):
    profile = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            profile[row["skill"]] = {"level": int(row["level"]), "evidence": row["evidence"],
                                     "aliases": row.get("aliases", "")}
    return profile


_INDEX_CACHE = {}


def score_offer(profile, required_skills):
    key = id(profile)
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = profile_index(profile)
    idx = _INDEX_CACHE[key]

    # normalized, de-duplicated required skills; keep the first spelling seen for display
    required = {}
    for s in required_skills or []:
        k = skill_key(s)
        if k and k not in NOT_A_SKILL and k not in required:
            required[k] = str(s).strip()

    matched, gaps = [], []
    for k, shown in required.items():
        if k in idx:
            if idx[k] not in matched:       # two aliases of the same profile skill count once
                matched.append(idx[k])
        else:
            gaps.append(shown)

    n_req = len(matched) + len(gaps)
    if n_req == 0:
        return {"score": 0.0, "coverage": 0.0, "matched": [], "gaps": [], "n_required": 0,
                "weighted_coverage": 0.0, "confidence": 0.0, "scorable": False}
    coverage = len(matched) / n_req
    weighted = sum(profile[m]["level"] / 5 for m in matched) / n_req
    confidence = min(1.0, n_req / MIN_REQUIRED_FOR_FULL_CONFIDENCE)
    return {
        "score": round(weighted * confidence, 3),
        "coverage": round(coverage, 3),
        "matched": matched,                 # profile skill names: draft_cv.py looks their evidence up
        "gaps": gaps,
        "n_required": n_req,
        "weighted_coverage": round(weighted, 3),
        "confidence": round(confidence, 3),
        "scorable": True,
    }


def next_skill_to_learn(results, profile, assumed_level=3):
    """For each missing skill: how many offers would cross HIGH_MATCH_SCORE if I
    learned it (to level `assumed_level`)? A 'what to learn next' KPI that is about
    better targeting, not more applications."""
    gain = {}
    for r in results:
        if not r.get("scorable") or r["score"] >= HIGH_MATCH_SCORE:
            continue
        for g in set(r["gaps"]):
            weighted = r["weighted_coverage"] + (assumed_level / 5) / r["n_required"]
            if weighted * r["confidence"] >= HIGH_MATCH_SCORE:
                k = skill_key(g)
                gain.setdefault(k, {"skill": g, "offers_unlocked": 0})
                gain[k]["offers_unlocked"] += 1
    return sorted(gain.values(), key=lambda x: -x["offers_unlocked"])[:10]


def build_output(results, profile, meta=None):
    gap_counts, gap_names, matched_counts = {}, {}, {}
    for r in results:
        for g in r["gaps"]:
            k = skill_key(g)                 # count "Power BI" and "PowerBI" together
            gap_counts[k] = gap_counts.get(k, 0) + 1
            gap_names.setdefault(k, g)
        for s in r["matched"]:
            matched_counts[s] = matched_counts.get(s, 0) + 1
    top_gaps = sorted(gap_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top_matched = sorted(matched_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    n_with_comp = sum(1 for r in results if r.get("compensation_mentioned"))

    hist = [0] * (len(SCORE_BINS) - 1)
    for r in results:
        if r.get("scorable"):
            for i in range(len(hist)):
                if SCORE_BINS[i] <= r["score"] < SCORE_BINS[i + 1]:
                    hist[i] += 1
                    break
    per_source = {}
    for r in results:
        per_source[r["source"]] = per_source.get(r["source"], 0) + 1

    meta = meta or {}
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fetched_at": meta.get("fetched_at"),
        "kpi_definition": "score = (sum of level/5 over matched skills / number of required skills) x min(1, required/3)",
        "high_match_threshold": HIGH_MATCH_SCORE,
        "n_offers": len(results),
        "offers": results,
        "top_skill_gaps": [{"skill": gap_names[k], "count": c} for k, c in top_gaps],
        "top_matched_skills": [{"skill": s, "count": c, "level": profile[s]["level"]} for s, c in top_matched],
        "n_offers_with_compensation": n_with_comp,
        # additions for the dashboard
        "n_high_match": sum(1 for r in results if r["score"] >= HIGH_MATCH_SCORE),
        "n_unscorable": sum(1 for r in results if not r.get("scorable")),
        "n_extraction_errors": sum(1 for r in results if r.get("extraction_error")),
        "n_with_experience_stated": sum(1 for r in results if r.get("experience_required")),
        "per_source": per_source,
        "score_histogram": [{"from": SCORE_BINS[i], "to": min(1.0, SCORE_BINS[i + 1]), "offers": hist[i]} for i in range(len(hist))],
        "next_skill_to_learn": next_skill_to_learn(results, profile),
        "extraction": {k: meta.get(k) for k in ("model", "avg_seconds_per_offer", "n_extracted_this_run", "n_reused_from_cache")},
    }


def main():
    profile = load_profile()
    with open("data/offers/structured_offers.json", encoding="utf-8") as f:
        data = json.load(f)

    results = []
    for offer in data["offers"]:
        m = score_offer(profile, offer.get("required_skills", []))
        results.append({**offer, **m})

    results.sort(key=lambda r: r["score"], reverse=True)
    for r in results[:25]:
        print(f"  {r['score']:.3f}  {r['title']} @ {r['company']}  ({r['source']}, "
              f"coverage {r['coverage']:.0%} of {r['n_required']}, gaps: {r['gaps'][:5]})")
    if len(results) > 25:
        print(f"  ... {len(results) - 25} more")

    os.makedirs("data/offers", exist_ok=True)
    with open("data/offers/matches_all_local.json", "w", encoding="utf-8") as f:
        json.dump(build_output(results, profile, data), f, indent=2, ensure_ascii=False)
    print(f"Wrote data/offers/matches_all_local.json ({len(results)} offers) -- gitignored, local only")

    public_results = [r for r in results if r.get("publishable", False)]
    public = build_output(public_results, profile, data)
    # The boards allow showing their jobs with a link back, not copying their text:
    # the public file keeps facts (skills, score, link) and drops anything quoted or
    # paraphrased from the description. The counts above were computed before this.
    public["offers"] = [{k: v for k, v in r.items() if k not in PRIVATE_FIELDS} for r in public["offers"]]
    os.makedirs("docs/data", exist_ok=True)
    with open("docs/data/matches.json", "w", encoding="utf-8") as f:
        json.dump(public, f, indent=2, ensure_ascii=False)
    print(f"Wrote docs/data/matches.json ({len(public_results)} of {len(results)} offers -- publishable sources only)")


if __name__ == "__main__":
    main()

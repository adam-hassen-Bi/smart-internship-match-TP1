"""Acquisition: internship offers from several public job APIs, all free and keyless.

The France Travail API planned in the manual is blocked for our class, so the
pipeline collects from several other sources instead and normalizes them to one
schema right here (same fields as before: id, source, title, company, location,
description, url, date_posted, ...).

Sources (public JSON endpoints, no account, no key):
  the_muse   themuse.com/api/public/jobs      level=Internship, French cities + remote
  arbeitnow  arbeitnow.com/api/job-board-api  European board (mostly DE/FR/NL), paged
  remotive   remotive.com/api/remote-jobs     remote jobs, job_type "internship"
  jobicy     jobicy.com/api/v2/remote-jobs    remote jobs, geo filter
  remoteok   remoteok.com/api                 remote jobs, tag filter

Every source is optional: if one is down or changes its format, it is recorded as
failed in docs/data/source_health.json and the others still work. Each one is asked
once per run (weekly in Actions, or by hand), well inside the limits they publish.

What gets committed: ONLY docs/data/source_health.json (counts per source, no
offer text). The offers themselves (data/offers/raw_offers.json) stay local and
gitignored: several of these boards allow showing their jobs with a link back, but
not copying their content into another site, so the public dashboard only ever
shows title / company / link / my score (see `publishable` in SOURCES).

    python3 scripts/fetch_offers.py              # all sources
    python3 scripts/fetch_offers.py the_muse     # one source (debug)
"""
import html
import json
import os
import re
import sys
import time

import requests

RAW_PATH = "data/offers/raw_offers.json"
HEALTH_PATH = "docs/data/source_health.json"
HEADERS = {"User-Agent": "smart-internship-match/1.0 (ENSIM student project)",
           "Accept": "application/json"}

# An offer is kept if it is an internship AND looks like a computing / data job.
INTERN_RE = re.compile(r"\b(intern|interns|internship|stage|stagiaire|praktikum|praktikant|trainee|"
                       r"werkstudent|working student|alternance|alternant|apprenti|apprentice|pfe)\b", re.I)
TECH_RE = re.compile(r"\b(data|donn[ée]es|software|logiciel|d[ée]velopp|developer|engineer|ing[ée]nieur|"
                     r"informatique|python|java|machine learning|ml|ai|ia|artificial intelligence|"
                     r"intelligence artificielle|deep learning|nlp|devops|cloud|web|full[- ]?stack|"
                     r"back[- ]?end|front[- ]?end|bi|business intelligence|analytics|analyst|analyste|"
                     r"cyber|security|s[ée]curit[ée]|it|tech|backend|frontend|mobile|android|ios|"
                     r"computer|digital|num[ée]rique|qa|test|product)\b", re.I)
FRANCE_CITIES = ["Paris, France", "Lyon, France", "Toulouse, France", "Nantes, France", "Lille, France",
                 "Bordeaux, France", "Rennes, France", "Marseille, France", "Grenoble, France",
                 "Nice, France", "Le Mans, France", "Flexible / Remote"]


def clean_text(s):
    """HTML description -> plain text (the LLM gets text, not tags)."""
    s = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def get_json(url, params=None, retries=3, backoff=5):
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=(10, 40))
            if r.status_code == 429:
                raise requests.exceptions.HTTPError("429 rate limited")
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            last = e
            print(f"    attempt {attempt}/{retries} failed: {str(e)[:160]}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise RuntimeError(f"unreachable after {retries} attempts: {last}")


def is_tech_internship(title, extra=""):
    text = f"{title} {extra}"
    return bool(INTERN_RE.search(text)) and bool(TECH_RE.search(text))


def offer(source, sid, title, company, location, description, url, date_posted, contract_type=None,
          is_apprenticeship=None, matched_search=None):
    t = f"{title} {contract_type or ''}"
    return {
        "id": f"{source}_{sid}",
        "source": source,
        "title": (title or "").strip(),
        "company": (company or "").strip() or None,
        "location": (location or "").strip() or None,
        "description": clean_text(description),
        "url": url,
        "date_posted": date_posted,
        "contract_type": contract_type,
        "is_apprenticeship": bool(is_apprenticeship) if is_apprenticeship is not None
        else bool(re.search(r"\b(alternance|alternant|apprenti|apprentice|werkstudent)\b", t, re.I)),
        "accessible_disability": None,   # none of these sources states it -- unknown, not False
        "matched_search": matched_search,
        "publishable": SOURCES[source]["publishable"],
    }


# ------------------------------------------------------------------ sources
def fetch_the_muse():
    """level=Internship is a real filter here; one query per French city + remote."""
    out, n_raw = {}, 0
    for loc in FRANCE_CITIES:
        for page in range(0, 5):
            d = get_json("https://www.themuse.com/api/public/jobs",
                         {"level": "Internship", "location": loc, "page": page, "descending": "true"})
            res = d.get("results", [])
            n_raw += len(res)
            for j in res:
                cats = " ".join(c.get("name", "") for c in j.get("categories", []))
                if not TECH_RE.search(f"{j.get('name', '')} {cats}"):
                    continue
                out[j["id"]] = offer(
                    "the_muse", j["id"], j.get("name"), (j.get("company") or {}).get("name"),
                    "; ".join(l.get("name", "") for l in j.get("locations", [])),
                    j.get("contents"), (j.get("refs") or {}).get("landing_page"),
                    j.get("publication_date"), "Internship", matched_search=loc)
            if page + 1 >= d.get("page_count", 0):
                break
            time.sleep(0.5)
    return list(out.values()), n_raw


def fetch_arbeitnow(max_pages=10):
    out, n_raw = [], 0
    url, params = "https://www.arbeitnow.com/api/job-board-api", {"page": 1}
    for _ in range(max_pages):
        d = get_json(url, params)
        jobs = d.get("data", [])
        n_raw += len(jobs)
        for j in jobs:
            types = " ".join(j.get("job_types") or [])
            tags = " ".join(j.get("tags") or [])
            if not is_tech_internship(j.get("title", ""), f"{types} {tags}"):
                continue
            posted = j.get("created_at")
            out.append(offer(
                "arbeitnow", j.get("slug"), j.get("title"), j.get("company_name"),
                (j.get("location") or "") + (" (remote)" if j.get("remote") else ""),
                j.get("description"), j.get("url"),
                time.strftime("%Y-%m-%d", time.gmtime(posted)) if isinstance(posted, (int, float)) else posted,
                types or None))
        nxt = (d.get("links") or {}).get("next")
        if not nxt or not jobs:
            break
        url, params = nxt, None
        time.sleep(1)
    return out, n_raw


def fetch_remotive():
    out, n_raw = {}, 0
    for term in ["intern", "internship"]:
        d = get_json("https://remotive.com/api/remote-jobs", {"search": term})
        jobs = d.get("jobs", [])
        n_raw += len(jobs)
        for j in jobs:
            jt = j.get("job_type") or ""
            if not (jt.lower() == "internship" or INTERN_RE.search(j.get("title", ""))):
                continue
            if not TECH_RE.search(f"{j.get('title', '')} {j.get('category', '')} {' '.join(j.get('tags') or [])}"):
                continue
            out[j["id"]] = offer(
                "remotive", j["id"], j.get("title"), j.get("company_name"),
                (j.get("candidate_required_location") or "") + " (remote)", j.get("description"),
                j.get("url"), j.get("publication_date"), jt or None, matched_search=term)
    return list(out.values()), n_raw


def fetch_jobicy():
    out, n_raw = {}, 0
    for geo in ["france", "europe", "emea"]:
        d = get_json("https://jobicy.com/api/v2/remote-jobs", {"count": 100, "geo": geo})
        jobs = d.get("jobs", [])
        n_raw += len(jobs)
        for j in jobs:
            types = " ".join(j.get("jobType") or []) if isinstance(j.get("jobType"), list) else str(j.get("jobType") or "")
            extra = f"{types} {j.get('jobLevel', '')} {' '.join(j.get('jobIndustry') or [])}"
            if not is_tech_internship(j.get("jobTitle", ""), extra):
                continue
            out[j["id"]] = offer(
                "jobicy", j["id"], html.unescape(j.get("jobTitle") or ""), j.get("companyName"),
                (j.get("jobGeo") or "") + " (remote)", j.get("jobDescription") or j.get("jobExcerpt"),
                j.get("url"), j.get("pubDate"), types or None, matched_search=geo)
        time.sleep(1)
    return list(out.values()), n_raw


def fetch_remoteok():
    d = get_json("https://remoteok.com/api")
    jobs = [j for j in d if isinstance(j, dict) and j.get("id")]   # item 0 is their legal notice
    out = []
    for j in jobs:
        if not is_tech_internship(j.get("position", ""), " ".join(j.get("tags") or [])):
            continue
        out.append(offer(
            "remoteok", j["id"], j.get("position"), j.get("company"),
            (j.get("location") or "Worldwide") + " (remote)", j.get("description"),
            j.get("url"), j.get("date")))
    return out, len(jobs)


# publishable: may the public dashboard show title/company/link/score for this
# source? Decided from each source's published terms (README, "Sources and terms").
SOURCES = {
    "the_muse":  {"fn": fetch_the_muse,  "publishable": True,  "attribution": "The Muse",
                  "home": "https://www.themuse.com"},
    "arbeitnow": {"fn": fetch_arbeitnow, "publishable": True,  "attribution": "Arbeitnow",
                  "home": "https://www.arbeitnow.com"},
    "remotive":  {"fn": fetch_remotive,  "publishable": False, "attribution": "Remotive",
                  "home": "https://remotive.com"},
    "jobicy":    {"fn": fetch_jobicy,    "publishable": True,  "attribution": "Jobicy",
                  "home": "https://jobicy.com"},
    "remoteok":  {"fn": fetch_remoteok,  "publishable": True,  "attribution": "Remote OK",
                  "home": "https://remoteok.com"},
}


def main():
    only = sys.argv[1:] or list(SOURCES)
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    offers, health = [], {}
    for name in only:
        print(f"\n[{name}]")
        t0 = time.time()
        try:
            got, n_raw = SOURCES[name]["fn"]()
            health[name] = {"ok": True, "n_scanned": n_raw, "n_kept": len(got),
                            "seconds": round(time.time() - t0, 1)}
            print(f"  scanned {n_raw} jobs, kept {len(got)} tech internships ({time.time() - t0:.1f}s)")
            for o in got[:3]:
                print(f"    e.g. {o['title']} @ {o['company']} -- {o['location']}")
            offers += got
        except Exception as e:   # one broken source must not stop the others
            health[name] = {"ok": False, "error": str(e)[:300], "n_scanned": 0, "n_kept": 0}
            print(f"  FAILED: {e}")

    # same offer posted on two boards: keep the first one (title + company)
    seen, unique = set(), []
    for o in offers:
        key = (re.sub(r"\W+", "", o["title"].lower()), re.sub(r"\W+", "", (o["company"] or "").lower()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(o)
    print(f"\nTotal: {len(offers)} offers, {len(unique)} after removing cross-source duplicates")

    os.makedirs("data/offers", exist_ok=True)
    with open(RAW_PATH, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": fetched_at, "offers": unique}, f, indent=2, ensure_ascii=False)
    print(f"Wrote {RAW_PATH} -- gitignored, local only")

    os.makedirs("docs/data", exist_ok=True)
    with open(HEALTH_PATH, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": fetched_at,
                   "n_offers": len(unique), "n_duplicates_removed": len(offers) - len(unique),
                   "sources": {k: {**v, "publishable": SOURCES[k]["publishable"],
                                   "attribution": SOURCES[k]["attribution"], "home": SOURCES[k]["home"]}
                               for k, v in health.items()}},
                  f, indent=2, ensure_ascii=False)
    print(f"Wrote {HEALTH_PATH} (counts only)")
    if not any(h["ok"] for h in health.values()):
        sys.exit("Every source failed -- nothing fetched.")


if __name__ == "__main__":
    main()

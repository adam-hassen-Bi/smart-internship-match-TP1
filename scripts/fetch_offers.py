"""Fetch internship offers from the France Travail "Offres d'emploi v2" API.

Runs in GitHub Actions (weekly) with the credentials stored as repository secrets:
FRANCETRAVAIL_CLIENT_ID / FRANCETRAVAIL_CLIENT_SECRET. Never put them in the code.

France Travail data is official open government data, licensed for reuse, so
data/offers/raw_offers.json is committed.

Notes from the TD manual, kept because they are real findings:
- "stage" is NOT a contract type in this API (codes are CCE, CDD, CDI, DDI, DIN,
  FRA, LIB, MIS, REP, SAI, TTI, DDT): a French internship is governed by a school
  "convention de stage", not an employment contract. So we search by keyword
  (motsCles, full text over title + description) and only use a contract-type
  filter if a "stage" code ever appears in the referentiel.
- HTTP 206 is a normal paginated success, HTTP 204 means zero results: both are
  success, and 204 has no body to parse.

Change from the manual: several searches instead of one, matching my real target
roles (data science, ML, NLP, data / IT audit), merged and de-duplicated by offer
id. "stage informatique" alone mostly returns web-development internships.
"""
import json
import os
import time

import requests

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
REFERENTIEL_CONTRATS_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/referentiel/typesContrats"

CLIENT_ID = os.environ["FRANCETRAVAIL_CLIENT_ID"]
CLIENT_SECRET = os.environ["FRANCETRAVAIL_CLIENT_SECRET"]
SCOPE = "api_offresdemploiv2 o2dsoffre"

# One search per target role. Nationwide (no commune/distance filter).
KEYWORD_SEARCHES = [
    "stage data scientist",
    "stage machine learning",
    "stage intelligence artificielle",
    "stage data",
    "stage audit informatique",
    "stage informatique",
]
BASE_PARAMS = {
    "sort": "1",        # most recent first
    "range": "0-49",    # 50 per search; the API caps one request at 150
}
PAUSE_BETWEEN_SEARCHES_S = 1.0   # be a polite client of a public API


def get_access_token(retries=4, backoff=5):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials", "client_id": CLIENT_ID,
                      "client_secret": CLIENT_SECRET, "scope": SCOPE},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=(10, 20),
            )
            resp.raise_for_status()
            return resp.json()["access_token"]
        except requests.exceptions.RequestException as e:
            last_error = e
            print(f"  token request attempt {attempt}/{retries} failed: {e}")
            if getattr(e, "response", None) is not None:
                print(f"  response body: {e.response.text[:500]}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise RuntimeError(f"Could not obtain access token after {retries} attempts") from last_error


def try_resolve_contract_type_code(token, label_substring="stage"):
    """Best effort: return a contract-type code whose label contains 'stage', or None."""
    try:
        resp = requests.get(REFERENTIEL_CONTRATS_URL, headers={"Authorization": f"Bearer {token}"}, timeout=(10, 20))
        resp.raise_for_status()
        all_types = resp.json()
        print("Available contract types:", ", ".join(t.get("code", "?") for t in all_types))
        for t in all_types:
            if label_substring.lower() in t.get("libelle", "").lower():
                print(f"Resolved '{label_substring}' -> code '{t['code']}' ({t['libelle']})")
                return t["code"]
        print(f"No contract type matches '{label_substring}' -- keyword search only (expected).")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Could not fetch contract-type referentiel ({e}) -- keyword search only.")
        return None


def search_offers(token, params, retries=4, backoff=5):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(SEARCH_URL, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=(10, 30))
            if resp.status_code == 204:
                return []
            if resp.status_code not in (200, 206):
                print(f"  HTTP {resp.status_code}: {resp.text[:300]!r}")
                resp.raise_for_status()
            return resp.json().get("resultats", [])
        except requests.exceptions.RequestException as e:
            last_error = e
            print(f"  search attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise RuntimeError(f"Could not search offers after {retries} attempts") from last_error


def main():
    print("Requesting access token...")
    token = get_access_token()
    code = try_resolve_contract_type_code(token, "stage")

    by_id, per_search = {}, {}
    for kw in KEYWORD_SEARCHES:
        params = {**BASE_PARAMS, "motsCles": kw}
        if code:
            params["typeContrat"] = code
        offers = search_offers(token, params)
        new = 0
        for o in offers:
            if o["id"] not in by_id:
                o["_matched_search"] = kw
                by_id[o["id"]] = o
                new += 1
        per_search[kw] = {"returned": len(offers), "new": new}
        print(f"  {kw!r}: {len(offers)} offers, {new} new")
        time.sleep(PAUSE_BETWEEN_SEARCHES_S)

    offers = list(by_id.values())
    print(f"Found {len(offers)} distinct offers")
    os.makedirs("data/offers", exist_ok=True)
    with open("data/offers/raw_offers.json", "w", encoding="utf-8") as f:
        json.dump({
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "search_params": {**BASE_PARAMS, "motsCles": KEYWORD_SEARCHES},
            "per_search": per_search,
            "offers": offers,
        }, f, indent=2, ensure_ascii=False)
    print("Wrote data/offers/raw_offers.json")
    if offers:
        print("First offer preview:", json.dumps(offers[0], ensure_ascii=False, indent=2)[:800])


if __name__ == "__main__":
    main()

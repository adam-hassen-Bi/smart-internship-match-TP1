"""Normalize every source to one common schema -> data/offers/merged_offers.json (local only).

Each offer carries a `publishable` flag: True for France Travail (official open
data), False for anything scraped. match_offers.py uses it to keep scraped content
off the public dashboard automatically.
"""
import json
import os

RAW_FT_PATH = "data/offers/raw_offers.json"
JOBSPY_PATH = "data/offers/jobspy_offers.json"
MERGED_PATH = "data/offers/merged_offers.json"
FT_OFFER_URL = "https://candidat.francetravail.fr/offres/recherche/detail/{id}"


def normalize_france_travail(raw_offers):
    normalized = []
    for o in raw_offers:
        origine = o.get("origineOffre") or {}
        normalized.append({
            "id": f"ft_{o['id']}",
            "source": "france_travail",
            "title": o.get("intitule"),
            "company": (o.get("entreprise") or {}).get("nom"),
            "location": (o.get("lieuTravail") or {}).get("libelle"),
            "description": o.get("description", "") or "",
            # France Travail fields: origineOffre.urlOrigine, dateCreation. When the
            # original URL is missing, the public offer page is built from the id.
            "url": origine.get("urlOrigine") or FT_OFFER_URL.format(id=o["id"]),
            "date_posted": o.get("dateCreation"),
            "contract_type": o.get("typeContrat"),
            "is_apprenticeship": bool(o.get("alternance", False)),
            "accessible_disability": bool(o.get("accessibleTH", False)),
            "matched_search": o.get("_matched_search"),
            "publishable": True,   # official open government data
        })
    return normalized


def load_jobspy():
    if not os.path.exists(JOBSPY_PATH):
        print(f"{JOBSPY_PATH} not found -- skipping (fine if the optional jobspy step was not run).")
        return []
    with open(JOBSPY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return [{**o, "contract_type": None, "is_apprenticeship": False, "accessible_disability": False,
             "matched_search": None, "publishable": False} for o in data["offers"]]


def main():
    with open(RAW_FT_PATH, encoding="utf-8") as f:
        ft_raw = json.load(f)
    ft_offers = normalize_france_travail(ft_raw["offers"])
    jobspy_offers = load_jobspy()
    merged = ft_offers + jobspy_offers
    print(f"Merged {len(ft_offers)} France Travail + {len(jobspy_offers)} jobspy = {len(merged)} total")
    os.makedirs("data/offers", exist_ok=True)
    with open(MERGED_PATH, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": ft_raw.get("fetched_at"), "offers": merged}, f, indent=2, ensure_ascii=False)
    print(f"Wrote {MERGED_PATH} -- gitignored, local only")


if __name__ == "__main__":
    main()

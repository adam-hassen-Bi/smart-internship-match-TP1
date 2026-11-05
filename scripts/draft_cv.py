"""Draft the opening paragraph of a cover letter for my best few matches (LOCAL ONLY).

Grounded: the prompt only contains the offer's missions, the skills I matched and
the evidence I wrote myself in my_skills.csv. Output goes to output/cv_drafts/,
git-ignored. Every draft is read and edited by me before use -- the model can
still invent an experience, and catching that is part of the project.

    python3 scripts/draft_cv.py          # top 3
    python3 scripts/draft_cv.py 5        # top 5
"""
import csv
import json
import os
import sys
import time

import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3:8b"
TOP_N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
MIN_COVERAGE = 0.3

PROMPT_TEMPLATE = """Tu es un(e) assistant(e) de redaction. Redige UNIQUEMENT le paragraphe
d'accroche (3-4 phrases) d'une lettre de motivation en francais, pour l'offre suivante, en
mettant en avant UNIQUEMENT les competences du candidat qui correspondent reellement a l'offre
(n'invente aucune competence ou experience non listee ci-dessous).

Contexte du candidat : eleve ingenieur en 5e annee (double diplome ESPRIT, specialite Data
Science, et ENSIM, specialite Interaction Personnes-Systemes), cherche un stage de fin
d'etudes de 6 mois a partir de mars 2027.

Offre: {title} chez {company}
Missions: {responsibilities}
Competences requises correspondantes chez le candidat: {matched_skills}
Preuves concretes du candidat: {evidence}

N'invente aucune experience professionnelle non mentionnee ci-dessus. Style: direct, concret,
pas de formules creuses. Reponds uniquement par le paragraphe.
"""


def load_profile(path="data/profile/my_skills.csv"):
    with open(path, encoding="utf-8") as f:
        return {row["skill"]: row["evidence"] for row in csv.DictReader(f)}


def call_ollama(prompt, retries=3, backoff=5):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                OLLAMA_URL, proxies={"http": None, "https": None},
                json={"model": MODEL, "prompt": prompt, "stream": False, "think": False},
                timeout=(10, 180),
            )
            resp.raise_for_status()
            return resp.json()["response"].strip()
        except Exception as e:
            last_error = e
            print(f"  Ollama attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(backoff)
    raise RuntimeError(f"Ollama unreachable after {retries} attempts") from last_error


def main():
    profile = load_profile()
    # every source, including scraped offers: a private draft is personal use;
    # only publishing a scraped listing is restricted, and that is handled upstream
    with open("data/offers/matches_all_local.json", encoding="utf-8") as f:
        data = json.load(f)

    candidates = [o for o in data["offers"] if o["coverage"] >= MIN_COVERAGE][:TOP_N]
    print(f"Drafting opening paragraphs for {len(candidates)} of {data['n_offers']} offers "
          f"(coverage >= {MIN_COVERAGE:.0%}, top {TOP_N})")
    os.makedirs("output/cv_drafts", exist_ok=True)
    for offer in candidates:
        evidence = {s: profile[s] for s in offer["matched"] if s in profile}
        prompt = PROMPT_TEMPLATE.format(
            title=offer["title"], company=offer["company"] or "cette entreprise",
            responsibilities=", ".join(offer["responsibilities"]) or "non precisees",
            matched_skills=", ".join(offer["matched"]),
            evidence=json.dumps(evidence, ensure_ascii=False),
        )
        print(f"  Drafting for: {offer['title']} @ {offer['company']}...")
        t0 = time.time()
        paragraph = call_ollama(prompt)
        out_path = f"output/cv_drafts/offer_{offer['id']}.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"Offer: {offer['title']} @ {offer['company']}\n{offer.get('url') or ''}\n"
                    f"Score {offer['score']:.2f} -- matched: {', '.join(offer['matched'])}\n\n{paragraph}\n\n"
                    f"--- CHECK BEFORE USE: every claim above must appear in this evidence ---\n"
                    f"{json.dumps(evidence, ensure_ascii=False, indent=2)}\n")
        print(f"    -> {out_path} ({time.time() - t0:.0f}s)")
    print("\nReminder: output/cv_drafts/ is gitignored -- review and edit every draft yourself.")


if __name__ == "__main__":
    main()

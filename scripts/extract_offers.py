"""Structure each offer's free text with a LOCAL LLM (Ollama) -> structured_offers.json.

Runs on my laptop, not in GitHub Actions (no GPU there), and I am present when the
AI output appears. The model is only asked for what the API does not already give
in structured fields: skills, missions, experience requirement, compensation.

Changes from the manual's version:
- "think": False -- qwen3 otherwise runs a hidden reasoning pass before every
  answer; in TD3 that turned a 2 s call into 16 s and made long prompts time out.
- Incremental: an offer already structured in a previous run (same id, same
  description) is reused instead of sent to the model again, so the weekly run
  only pays for new offers.
- A failed extraction no longer crashes the whole run: the offer is kept with
  extraction_error=True and counted as a pipeline-health KPI.

    python3 scripts/extract_offers.py          # all offers
    python3 scripts/extract_offers.py --redo   # ignore the cache
"""
import hashlib
import json
import os
import sys
import time

import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3:8b"
MAX_CHARS = 6000   # most descriptions are shorter; guards against very long career pages
OUT_PATH = "data/offers/structured_offers.json"

PROMPT_TEMPLATE = """Extract ONLY these things from this job/internship description text
(it may be in French or English).
Return ONLY valid JSON with keys:
- required_skills: array of concrete named tools/technologies/hard skills mentioned (e.g. "Python", "Power BI") -- do not include generic soft skills or the job title
- responsibilities: array of the actual tasks/missions described
- experience_required: a short string quoting the explicit experience requirement stated in the text (e.g. "2 years", "no experience required", "Bac+5", "enrolled in a Master's program"), or null if the text does not explicitly state one. Do NOT infer this from the job title, from words like "Senior"/"Lead" in the title, or from general seniority tone -- only from an actual requirement sentence in the text.
- compensation_mentioned: a short verbatim quote of any salary/compensation/gratification FIGURE explicitly stated in the text (e.g. "75-90k EUR package", "600 euros/mois"), or null if no concrete number is stated anywhere in the text. Read the ENTIRE text, including the end, before concluding there is none.

Do not extract title, company, or location -- those come from elsewhere and are not in this text.
No explanation, just the JSON object.

TEXT:
{text}
"""


def call_ollama(prompt, retries=3, backoff=5):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                OLLAMA_URL,
                proxies={"http": None, "https": None},
                json={"model": MODEL, "prompt": prompt, "format": "json", "stream": False, "think": False},
                timeout=(10, 120),
            )
            resp.raise_for_status()
            return json.loads(resp.json()["response"])
        except Exception as e:
            last_error = e
            print(f"    Ollama attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(backoff)
    raise RuntimeError(f"Ollama unreachable or bad output after {retries} attempts") from last_error


def text_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def as_list(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def main():
    redo = "--redo" in sys.argv
    with open("data/offers/merged_offers.json", encoding="utf-8") as f:
        merged = json.load(f)

    cache = {}
    if os.path.exists(OUT_PATH) and not redo:
        with open(OUT_PATH, encoding="utf-8") as f:
            for o in json.load(f).get("offers", []):
                if not o.get("extraction_error"):
                    cache[(o["id"], o.get("text_hash"))] = o

    structured, n_new, n_cached, n_err, t_total = [], 0, 0, 0, 0.0
    offers = merged["offers"]
    for i, offer in enumerate(offers, 1):
        text = (offer.get("description") or "")[:MAX_CHARS]
        h = text_hash(text)
        base = {k: offer.get(k) for k in ("id", "source", "title", "company", "location", "url",
                                          "date_posted", "contract_type", "matched_search")}
        base.update({
            "is_apprenticeship": offer.get("is_apprenticeship", False),
            "accessible_disability": offer.get("accessible_disability", False),
            "publishable": offer.get("publishable", False),
            "text_hash": h,
        })
        if (offer["id"], h) in cache:
            structured.append({**cache[(offer["id"], h)], **base})
            n_cached += 1
            continue

        print(f"[{i}/{len(offers)}] {offer['id']} ({offer['source']}): {offer.get('title')}")
        t0 = time.time()
        try:
            ex = call_ollama(PROMPT_TEMPLATE.format(text=text)) if text.strip() else {}
            err = False
        except RuntimeError as e:
            print(f"    -> kept with extraction_error ({e})")
            ex, err = {}, True
            n_err += 1
        t_total += time.time() - t0
        n_new += 1
        structured.append({
            **base,
            "required_skills": as_list(ex.get("required_skills")),
            "responsibilities": as_list(ex.get("responsibilities")),
            "experience_required": ex.get("experience_required") or None,
            "compensation_mentioned": ex.get("compensation_mentioned") or None,
            "extraction_error": err,
        })
        print(f"    {time.time() - t0:.1f}s  skills: {structured[-1]['required_skills']}")

    os.makedirs("data/offers", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "fetched_at": merged.get("fetched_at"),
            "model": MODEL,
            "n_extracted_this_run": n_new,
            "n_reused_from_cache": n_cached,
            "n_extraction_errors": n_err,
            "avg_seconds_per_offer": round(t_total / n_new, 1) if n_new else None,
            "offers": structured,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {OUT_PATH}: {len(structured)} offers ({n_new} extracted, {n_cached} reused, "
          f"{n_err} errors) -- gitignored, local only")


if __name__ == "__main__":
    main()

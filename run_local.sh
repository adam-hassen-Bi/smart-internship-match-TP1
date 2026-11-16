#!/bin/bash
# Local half of the pipeline, on my Mac (needs Ollama running with qwen3:8b).
#   ./run_local.sh             fetch the offers, merge, extract, match, monitor
#   ./run_local.sh --jobspy    also scrape Indeed/ZipRecruiter first (local only, never published)
#   ./run_local.sh --drafts    also draft cover-letter openings for the top 3 (local only)
set -e
cd "$(dirname "$0")"

curl -s --noproxy '*' http://127.0.0.1:11434/api/version >/dev/null \
  || { echo "Ollama is not running -- open the Ollama app first."; exit 1; }
python3 -m pip install --user -q requests 2>/dev/null

git pull -q --rebase || echo "(git pull failed -- continuing with the local copy)"

# The offers are not in the repo (the job boards allow a link back, not a copy), so
# they are fetched here, on my machine, from the same public APIs as the weekly Action.
echo "== 1. Fetch offers from the public job APIs =="
python3 scripts/fetch_offers.py

if [[ " $* " == *" --jobspy "* ]]; then
  echo; echo "== 1b. Optional scraped source (local only) =="
  python3 -m pip install --user -q uv 2>/dev/null
  python3 -m uv run scripts/fetch_offers_jobspy.py || echo "(jobspy failed -- continuing with the API sources only)"
fi

echo; echo "== 2. Merge sources ==";            python3 scripts/merge_offer_sources.py
echo; echo "== 3. Extract with the local LLM =="; python3 -W ignore scripts/extract_offers.py
echo; echo "== 4. Match against my profile ==";  python3 scripts/match_offers.py
echo; echo "== 5. Outcomes and monitoring ==";   python3 scripts/monitor.py

if [[ " $* " == *" --drafts "* ]]; then
  echo; echo "== 6. Cover-letter drafts (local only) =="; python3 -W ignore scripts/draft_cv.py
fi

echo; echo "== Publishable files to commit (nothing else should appear) =="
git status --short docs/data/
echo "Then: git add docs/data/ && git commit -m \"Update matches\" && git push"

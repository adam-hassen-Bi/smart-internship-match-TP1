# Smart Internship Match

**Project 1 · Business Intelligence** — a personal decision-support system for my
end-of-studies internship search (6 months from March 2027, data science / ML / NLP /
IT audit): collect real offers, structure them, match them against my skills, help me
act, and track what happens.

### [Open the dashboard](https://adam-hassen-bi.github.io/smart-internship-match-TP1/dashboard.html)

https://adam-hassen-bi.github.io/smart-internship-match-TP1/dashboard.html ·
[raw data sanity check](https://adam-hassen-bi.github.io/smart-internship-match-TP1/)

AI is used only where it adds something — structuring free-text offers and drafting
a first cover-letter paragraph — and never to decide or to record what I did. The
application tracker is a plain table I fill in myself; the dashboard ranks, I decide.

---

## Pipeline

```mermaid
flowchart LR
    subgraph Cloud["GitHub Actions — every Monday"]
        A[Public job APIs<br/>Arbeitnow · Jobicy · Remotive · Remote OK<br/>+ company career sites] -->|fetch_offers.py| H[(source_health.json<br/>counts only)]
    end
    subgraph Laptop["My Mac — ./run_local.sh"]
        A -->|fetch_offers.py<br/>same APIs| B[(raw_offers.json<br/>local only)]
        J[Indeed / ZipRecruiter<br/>optional, jobspy] -.->|local only| M
        B --> M[merge_offer_sources.py<br/>one schema, duplicates, publishable flag]
        M --> E[extract_offers.py<br/>Ollama qwen3:8b]
        E --> S[match_offers.py<br/>MY match KPI]
        P[my_skills.csv] --> S
        S --> D[draft_cv.py<br/>grounded drafts]
        T[applications.csv<br/>my tracker] --> O[monitor.py<br/>outcomes + 4 checks]
        S --> O
    end
    S -->|publishable only| W[docs/data/matches.json]
    O -->|aggregates only| W2[docs/data/outcomes.json<br/>monitoring_log.json]
    W --> X[dashboard.html]
    W2 --> X
    H --> X
```

| Stage | Script | Runs | Output | In git? |
|---|---|---|---|---|
| Acquisition | `fetch_offers.py` | GitHub Actions weekly + laptop | `raw_offers.json` / `docs/data/source_health.json` | offers **no** / counts yes |
| Optional 2nd source | `fetch_offers_jobspy.py` | laptop, by hand | `jobspy_offers.json` | **no** — scraped |
| Structuring | `merge_offer_sources.py` → `extract_offers.py` | laptop (Ollama) | `structured_offers.json` | **no** |
| KPI | `match_offers.py` | laptop | `matches_all_local.json` / `docs/data/matches.json` | local / **publishable only** |
| Action | `draft_cv.py` | laptop | `output/cv_drafts/` | **no** |
| Monitoring | `monitor.py` | laptop | `docs/data/outcomes.json`, `monitoring_log.json` | aggregates only |

## Sources (France Travail replaced)

The manual's France Travail API is **blocked for our class**, so the offers come from
several other sources instead — all free, no account, no key, one call per source per
run. `fetch_offers.py` normalizes all of them to the same schema the rest of the
pipeline already used, so nothing after it had to change.

| Source | What it is | Filter | First run (16 Nov 2026): scanned → kept | On the public page |
|---|---|---|---|---|
| [Arbeitnow](https://www.arbeitnow.com) | European job board API (FR / DE / NL) | internship words in title or job type + tech title | 2,514 → 78 | yes, with link back |
| Company career sites | official job-board APIs (Greenhouse, Lever, Ashby, SmartRecruiters) of 22 companies hiring engineering interns in France — Datadog, Dataiku, Mirakl, Ekimetrics, Malt, Alan, Ledger, Ubisoft, Devoteam… | internship + tech title + located in France / remote | 1,015 → 20 | yes, with link to the company |
| [Jobicy](https://jobicy.com) | remote jobs API | geo France / Europe / EMEA | 300 → 1 | yes, with link back |
| [Remotive](https://remotive.com) | remote jobs API | `job_type = internship` | 32 → 0 | **no** — its terms forbid reposting |
| [Remote OK](https://remoteok.com) | remote jobs API | internship + tech title | 97 → 0 | yes, with link back |
| Indeed / ZipRecruiter (optional) | scraped with jobspy, on my laptop only | `job_type = internship` | — | **no** — scraped |

**95 offers** after removing 4 cross-source duplicates. Tried and dropped: The Muse's
public API (404 on every query) and 43 company slugs with no public board.

Two honest findings for the report: remote-job APIs carry almost **no internships**
(1 out of 429 jobs) — the useful sources are the European board and the companies'
own career sites. And a source that keeps 0 is still checked every week: the
dashboard's *Sources* table shows it, so a silent drop is visible.

**What is committed**: only per-source counts (`docs/data/source_health.json`) and the
scored public offers without their text. The offer descriptions stay on my laptop:
these boards allow showing a job with a link back, not copying its content.

## My match KPI (`score_offer`)

```
required   = extracted skills, normalized (case, spelling, FR/EN aliases), de-duplicated, soft skills removed
matched    = my profile skills found in required        gaps = required skills I don't have
coverage   = |matched| / |required|
score      = ( Σ level/5 over matched ) / |required|  ×  min(1, |required| / 3)
```

- **Normalization before matching**: the LLM returns `Python` in one offer and
  `python` in the next, `apprentissage automatique` instead of `Machine learning`. An
  exact string match would silently miss those; `skills.py` + the `aliases` column of
  `my_skills.csv` map every variant to one key.
- **Weighted by my level**: a match on a skill I rate 2/5 is worth less than on one I
  rate 5/5 — and `draft_cv.py` quotes the evidence of every matched skill, so it must
  be a skill I can back up.
- **Confidence discount**: an offer that names only "Python" would otherwise score
  100 % and rank above a detailed data-science offer where I cover 6 skills out of 8.
- **Threshold**: score ≥ 0.4 = "worth applying".

Extra KPI that is *not* "more applications, faster": **next skill to learn** — for
each missing skill, how many offers would cross the threshold if I reached level 3 in
it. It differs from the plain "most frequent gap" ranking, and it is the one to act on.

## Dashboard — KPIs in the three required categories

| Category | KPIs | Chart and why |
|---|---|---|
| **Search effectiveness** | offers worth applying to, match-score distribution, most frequent gaps, next skill to learn, strengths × level | ranked table (I act on exact titles and links), histogram (a distribution), ranked bars (comparison) |
| **Outcome** | applications sent, status split, response rate, positive rate, median days to answer, applications per week | one stacked status bar (parts of a whole at a glance), weekly bars (rhythm, gaps) |
| **Pipeline health** | offers per source (up / down, scanned, kept, published or not), extraction errors, offers with no skill found, error rate from my own re-reading, experience / compensation stated, monitoring runs | small exact-figure tables |

## Monitoring (`monitor.py`)

Four checks, run after every local update and logged in `docs/data/monitoring_log.json`
(the dashboard lists every run):

1. **Stale** — application sent more than 10 days ago with no answer → follow up.
2. **Freshness** — fetch older than 8 days, or one source down → the workflow stopped or a job API changed.
3. **New match** — no new high-match offer since the previous check → widen keywords or region.
4. **Backlog** — high-match offers I have not applied to → review them.

## Privacy decisions

- Repository public (needed for GitHub Pages). My skills profile is public — it is what
  my CV already says.
- **My applications stay local**: `data/tracker/applications.csv` (company, title,
  dates, outcome) is git-ignored; only counts reach `outcomes.json`.
- Offers from Remotive and from jobspy are marked `publishable: false` and never reach
  `docs/data/matches.json`; the published offers keep title, company, link, skills and
  score only — no description, no quote. Cover-letter drafts stay in `output/cv_drafts/`.
- No credentials at all: every source is keyless.

## Run it

Once — Ollama with `qwen3:8b`, and
`cp data/tracker/applications.template.csv data/tracker/applications.csv`.

Every week:

```bash
./run_local.sh                 # fetch the offers, merge, extract, match, monitor
./run_local.sh --jobspy        # + Indeed / ZipRecruiter (local only)
./run_local.sh --drafts        # + cover-letter openings for the top 3 (local only)
git add docs/data/ && git commit -m "Update matches" && git push
python3 serve.py               # dashboard on http://localhost:8000/dashboard.html
```

To log a check of the model's output, add a line to `data/quality/critique_log.csv`
(`date, offer_id, field, skills_checked, errors, error_type, note`).

## Repository layout

```
.github/workflows/fetch_offers.yml   weekly check of every source (counts only)
data/profile/my_skills.csv           my skills: level 1-5, evidence, aliases
data/offers/raw_offers.json          fetched offers (local, git-ignored)
data/tracker/applications.template.csv   columns of my (local) tracker
data/quality/critique_log.csv        my manual checks of the LLM extraction
scripts/                             fetch, jobspy, merge, extract, skills, match, draft, monitor
docs/dashboard.html                  decision dashboard
docs/index.html                      raw-data sanity check
docs/data/                           matches.json, outcomes.json, monitoring_log.json, source_health.json
run_local.sh · serve.py
```

## Known limits

- Skill levels are self-assessed; a match means "the offer names a skill I list", not
  "I meet its level".
- Internships are detected from words in the title or the source's job type (stage,
  stagiaire, intern, Praktikum, alternance…) and tech from the title: a few non-IT
  offers get through (e.g. an energy-project internship matched "développement"); the
  match score ranks them at the bottom.
- Fewer offers than France Travail would give, and skewed towards larger companies
  (those with a public careers API) and towards Paris.
- Compensation is rarely stated in internship offers: reported as a count, not charted.

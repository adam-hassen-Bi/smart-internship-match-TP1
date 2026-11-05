"""Skill-name normalization, shared by match_offers.py and the quality report.

The LLM extracts skills offer by offer, so one real skill comes back in several
spellings ("Computer vision" / "computer vision", "PowerBI" / "Power BI",
"apprentissage automatique" / "Machine learning"). An exact string match would
silently miss real matches every time that happens, so every comparison goes
through skill_key(): lower-case, trimmed, and mapped through an alias table.

Two alias sources:
- ALIASES below, general variants (French / English, abbreviations);
- the `aliases` column of data/profile/my_skills.csv, for my own skills.
"""
import re

ALIASES = {
    "python 3": "python", "python3": "python",
    "powerbi": "power bi", "microsoft power bi": "power bi", "power-bi": "power bi",
    "ms excel": "excel", "microsoft excel": "excel",
    "amazon web services": "aws", "microsoft azure": "azure",
    "google cloud": "gcp", "google cloud platform": "gcp",
    "scikit learn": "scikit-learn", "sklearn": "scikit-learn",
    "pyspark": "spark", "apache spark": "spark", "apache airflow": "airflow", "apache kafka": "kafka",
    "k8s": "kubernetes", "postgres": "postgresql",
    "vision par ordinateur": "computer vision",
    "ci/cd": "ci/cd", "ci cd": "ci/cd", "cicd": "ci/cd",
}

# Not hard skills: the prompt asks the model not to return them, but it sometimes does.
NOT_A_SKILL = {
    "communication", "teamwork", "travail en équipe", "esprit d'équipe", "autonomie", "autonomy",
    "rigueur", "curiosité", "curiosity", "leadership", "organisation", "adaptabilité",
    "anglais", "english", "français", "french", "esprit d'analyse", "esprit de synthèse",
    "stage", "stagiaire", "internship", "informatique",
}


def skill_key(raw):
    k = re.sub(r"\s+", " ", str(raw)).strip().lower().strip(".,;:")
    return ALIASES.get(k, k)


def profile_index(profile):
    """Map every comparison key (skill name + its aliases) to the profile skill name."""
    idx = {}
    for name, info in profile.items():
        idx[skill_key(name)] = name
        for a in (info.get("aliases") or "").split("|"):
            if a.strip():
                idx[skill_key(a)] = name
    return idx

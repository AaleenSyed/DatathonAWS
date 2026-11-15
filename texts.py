"""User-facing fixed text in each supported answer language (en, fr = Canadian French).

The LLM-written answer follows prompts/lang_<code>.txt; these strings are added by code around it.
"""

LANGUAGES = ("en", "fr")

TEXT = {
    "en": {
        "disclaimer": "_Educational simulation for a fictional persona ({name}). Not personalized financial advice._",
        "incomplete": "> **Note:** the analysis is incomplete (see trace).",
        "reviewer_note": "> **Reviewer note:** {reasons}",
        "no_answer": "Sorry, the answer could not be written this time. The analysis is saved in the trace.",
    },
    "fr": {
        "disclaimer": "_Simulation éducative pour un profil fictif ({name}). Ne constitue pas un conseil financier "
                      "personnalisé._",
        "incomplete": "> **Note :** l’analyse est incomplète (voir la trace).",
        "reviewer_note": "> **Note du réviseur :** {reasons}",
        "no_answer": "Désolé, la réponse n’a pas pu être rédigée cette fois-ci. L’analyse est enregistrée dans la trace.",
    },
}


def lang_or_default(lang) -> str:
    """Return a supported language code; anything else falls back to English."""
    code = str(lang or "en").strip().lower()[:2]
    return code if code in LANGUAGES else "en"


def text(lang: str, key: str, **kwargs) -> str:
    return TEXT[lang_or_default(lang)][key].format(**kwargs)

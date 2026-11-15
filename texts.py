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
        "guardrail_block": "Sorry, I can't help with that request. AlphaForge AI is an educational simulation for "
                           "fictional investor personas ({name} here): it explains sectors and risks for the "
                           "persona's profile, but it does not give personal financial, tax or legal advice, place "
                           "trades, or handle personal information. Try asking what fits {name}'s profile.",
    },
    "fr": {
        "disclaimer": "_Simulation éducative pour un profil fictif ({name}). Ne constitue pas un conseil financier "
                      "personnalisé._",
        "incomplete": "> **Note :** l’analyse est incomplète (voir la trace).",
        "reviewer_note": "> **Note du réviseur :** {reasons}",
        "no_answer": "Désolé, la réponse n’a pas pu être rédigée cette fois-ci. L’analyse est enregistrée dans la trace.",
        "guardrail_block": "Désolé, je ne peux pas répondre à cette demande. AlphaForge AI est une simulation "
                           "éducative pour des profils d’investisseurs fictifs (ici {name}) : elle explique les "
                           "secteurs et les risques selon le profil, mais ne donne pas de conseils financiers, "
                           "fiscaux ou juridiques personnels, ne passe pas d’ordres et ne traite pas de "
                           "renseignements personnels. Demandez plutôt ce qui convient au profil de {name}.",
    },
}


def lang_or_default(lang) -> str:
    """Return a supported language code; anything else falls back to English."""
    code = str(lang or "en").strip().lower()[:2]
    return code if code in LANGUAGES else "en"


def text(lang: str, key: str, **kwargs) -> str:
    return TEXT[lang_or_default(lang)][key].format(**kwargs)

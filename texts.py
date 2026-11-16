"""User-facing fixed text in each supported answer language (en, fr = Canadian French).

The LLM-written answer follows prompts/lang_<code>.txt; these strings are added by code around it.
"""

LANGUAGES = ("en", "fr")

TEXT = {
    "en": {
        "disclaimer": "_Educational simulation for a fictional persona ({name}). Not personalized financial advice._",
        "chat_offer": "_General explanation only, with no figures from the data. Want me to run the analysis for {name}'s profile? Just say yes._",
        "incomplete": "> **Note:** the analysis is incomplete (see trace).",
        "reviewer_note": "> **Reviewer note:** {reasons}",
        "no_answer": "Sorry, the answer could not be written this time. The analysis is saved in the trace.",
        "guardrail_block": "Sorry, I can't help with that request. AlphaForge AI is an educational simulation for "
                           "fictional investor personas ({name} here): it explains sectors and risks for the "
                           "persona's profile, but it does not give personal financial, tax or legal advice, place "
                           "trades, or handle personal information. Try asking what fits {name}'s profile.",
        "chat_hello": (
            "Hello! I'm AlphaForge AI, an educational simulation. I'm answering for the fictional profile {name}. Ask me which sector fits {name}'s profile, or about a stock, for example: “Is tech too risky for me?”",
            "Hi there! This chat looks at sectors and risks for {name}, a fictional investor profile (simulation only, not personal advice). What would you like to explore? For example: “Where should I look for growth?”",
            "Hello again! Ready when you are: ask about a sector, a stock or a risk and I'll check it against {name}'s profile, with data and sources. Simulation only.",
        ),
        "chat_thanks": (
            "You're welcome! Ask another question about {name}'s profile whenever you like.",
            "Glad it helped. Remember, this is an educational simulation for the fictional profile {name}, not personal advice. Come back any time.",
            "Any time! To go further, ask about another sector or a specific stock for {name}.",
        ),
        "chat_about": (
            "I'm AlphaForge AI, an educational simulation. Here is how I work:\n\n- **Fictional profiles.** You chat as a fictional investor profile (here {name}), with its own risk tolerance, horizon and limits.\n- **Data-backed sector recommendations.** For each investing question I analyze public market data (prices, exchange rates, economic indicators), recommend a sector that fits {name}'s profile, and flag conflicts with the profile's limits.\n- **Sources and trace.** Every number comes with its source and period, and the trace shows each step: who did what, with which data.\n- **Simulation only.** No real transactions, and nothing here is personal financial advice.\n\nTry: “Which industry gives balanced growth for me?”",
            "Good question. AlphaForge AI is an educational simulation: it does not place trades and does not give personal financial advice. You pick a fictional investor profile (here {name}), then I answer investing questions for that profile. For each question I recommend a sector backed by data (risk numbers such as volatility and worst drop, example assets, market context), check it against {name}'s limits, and say so when a request conflicts with the profile. Each number carries its source and period, and the full trace of the analysis comes with every answer. Ask me, for example: “Is tech too risky for me?”",
        ),
        "chat_off_topic": (
            "That's outside what I can help with. I'm an educational simulation about investing: sectors, risks and how they fit the fictional profile {name}. Try a question like “Where should I look for growth?”",
            "I can't help with that one. I only cover investing questions for the fictional profile {name}: sectors, stocks in my data, risk and fit with the profile. Simulation only, not personal advice.",
            "Sorry, that's not something I cover. Ask me about a sector, a stock or a risk for {name}'s profile and I'll answer with data and sources.",
        ),
    },
    "fr": {
        "chat_offer": "_Explication générale seulement, sans chiffres tirés des données. Voulez-vous que je lance l’analyse pour le profil de {name}? Répondez oui._",
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
        "chat_hello": (
            "Bonjour! Je suis AlphaForge AI, une simulation éducative. Je réponds pour le profil fictif {name}. Demandez-moi quel secteur convient au profil de {name}, ou posez une question sur un titre, par exemple : « La techno est-elle trop risquée pour moi? »",
            "Bonjour à vous! Ce clavardage examine les secteurs et les risques pour {name}, un profil d’investisseur fictif (simulation seulement, pas un conseil personnel). Que voulez-vous explorer? Par exemple : « Où chercher de la croissance? »",
            "Rebonjour! Je suis prêt : posez une question sur un secteur, un titre ou un risque, et je la vérifierai par rapport au profil de {name}, avec données et sources. Simulation seulement.",
        ),
        "chat_thanks": (
            "Avec plaisir! Posez une autre question sur le profil de {name} quand vous voulez.",
            "Content que ce soit utile. Rappel : il s’agit d’une simulation éducative pour le profil fictif {name}, pas d’un conseil personnel. Revenez quand vous voulez.",
            "De rien! Pour aller plus loin, demandez-moi un autre secteur ou un titre précis pour {name}.",
        ),
        "chat_about": (
            "Je suis AlphaForge AI, une simulation éducative. Voici comment je fonctionne :\n\n- **Profils fictifs.** Vous clavardez au nom d’un profil d’investisseur fictif (ici {name}), avec sa tolérance au risque, son horizon et ses limites.\n- **Recommandations de secteurs appuyées sur des données.** Pour chaque question d’investissement, j’analyse des données de marché publiques (prix, taux de change, indicateurs économiques), je recommande un secteur qui convient au profil de {name} et je signale les conflits avec les limites du profil.\n- **Sources et trace.** Chaque chiffre est accompagné de sa source et de sa période, et la trace montre chaque étape : qui a fait quoi, avec quelles données.\n- **Simulation seulement.** Aucune transaction réelle, et rien ici ne constitue un conseil financier personnalisé.\n\nEssayez : « Quelle industrie offre une croissance équilibrée pour moi? »",
            "Bonne question. AlphaForge AI est une simulation éducative : elle ne passe aucun ordre et ne donne pas de conseil financier personnalisé. Vous choisissez un profil d’investisseur fictif (ici {name}), puis je réponds aux questions d’investissement pour ce profil. Pour chaque question, je recommande un secteur en m’appuyant sur des données (mesures de risque comme la volatilité et la pire baisse, exemples d’actifs, contexte de marché), je le compare aux limites de {name} et je le dis quand une demande entre en conflit avec le profil. Chaque chiffre indique sa source et sa période, et la trace complète de l’analyse accompagne chaque réponse. Demandez-moi, par exemple : « La techno est-elle trop risquée pour moi? »",
        ),
        "chat_off_topic": (
            "Cela sort de ce que je peux faire. Je suis une simulation éducative sur l’investissement : les secteurs, les risques et leur adéquation avec le profil fictif {name}. Essayez une question comme « Où chercher de la croissance? »",
            "Je ne peux pas vous aider là-dessus. Je traite seulement les questions d’investissement pour le profil fictif {name} : secteurs, titres de mes données, risque et adéquation avec le profil. Simulation seulement, pas un conseil personnel.",
            "Désolé, ce sujet n’est pas couvert. Posez-moi une question sur un secteur, un titre ou un risque pour le profil de {name} et je répondrai avec données et sources.",
        ),
    },
}


def lang_or_default(lang) -> str:
    """Return a supported language code; anything else falls back to English."""
    code = str(lang or "en").strip().lower()[:2]
    return code if code in LANGUAGES else "en"


def text(lang: str, key: str, **kwargs) -> str:
    return TEXT[lang_or_default(lang)][key].format(**kwargs)


def text_variant(lang: str, key: str, turn: int, **kwargs) -> str:
    """Fixed reply with several wordings (tuple in TEXT), rotated by turn number so it does not repeat."""
    options = TEXT[lang_or_default(lang)][key]
    return options[(turn - 1) % len(options)].format(**kwargs)

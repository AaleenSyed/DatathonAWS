# AlphaForge AI — PolyFinances Datathon 2026

*English version: [one-pager.en.md](one-pager.en.md)*

**Un chatbot agentique qui explique ses conclusions financières, chiffres et sources à l'appui.**

> Simulation éducative pour des personas fictifs. Pas un conseil financier personnalisé. Aucune transaction réelle.

## Le problème
Les outils d'IA financière donnent souvent des réponses convaincantes mais invérifiables : des chiffres
inventés, aucun lien avec le profil de l'investisseur, et un « oui » facile à une demande risquée.

## Notre solution
L'utilisateur choisit le persona qui lui ressemble (ou bâtit son propre profil fictif en 7 questions) puis
pose ses questions en langage simple, en français ou en anglais :

| Persona | Profil | Ce que le système doit faire |
|---|---|---|
| **Amira**, 26 ans | Risque élevé, 15 ans et + | Croissance tech/IA, mais diversification imposée (crypto ≤ 15 %) |
| **Mateo**, 41 ans | Risque modéré, 8–12 ans | Croissance équilibrée, critères ESG, Énergie signalée pour examen |
| **Robert**, 59 ans | Risque faible–modéré, 3–5 ans | Contester « NVDA avec une grosse part de mes économies », chiffres à l'appui |

Chaque réponse recommande **un secteur précis** (ex. Biens de consommation de base + Obligations), avec
les chiffres de risque, des exemples d'actifs, le lien avec l'horizon et la tolérance au risque du persona,
ce qui pourrait mal tourner, et les conflits avec le profil.

## Comment ça marche
1. **Bedrock Guardrail** filtre la question (conseil personnel réel, transactions, PII, injection de prompt).
2. **Le routeur d'intention** (règles, puis Claude Haiku 4.5) décide si le message demande une analyse. Les
   salutations, les questions sur l'assistant, les questions de concept (« que veut dire volatilité? ») et les
   messages hors sujet reçoivent une réponse courte et naturelle en environ 1,5 s, sans chiffres. Les questions
   d'investissement et les suivis continuent.
3. **Le patron** (Claude Haiku 4.5 sur Bedrock, agent Strands) choisit les outils à appeler et planifie.
4. **Les travailleurs** (Python déterministe, *aucun LLM*) calculent tout : rendement, volatilité, perte
   maximale, test de stress 2022, cycle économique (FRED), conformité aux limites du persona.
5. **Le réviseur** vérifie le travail ; en cas d'échec, il renvoie la tâche avec les raisons (max. 2 essais).
6. **Le présentateur** (Claude Sonnet 4.6, en continu) rédige la réponse à partir des seuls résultats des
   travailleurs ; chaque chiffre doit apparaître dans l'étape citée.
7. **Guardrail en sortie**, puis la **trace complète** est sauvegardée dans Amazon S3.

## Ce qui nous distingue
- **Les LLM ne calculent jamais.** Les chiffres viennent de code testé (535 tests) ; l'IA raisonne et explique.
- **Explicabilité vérifiable.** Chaque affirmation est étiquetée `fait` (source + étape), `hypothèse` ou
  `scénario`, et s'ouvre sur l'étape de la trace qui l'a produite.
- **Il sait dire non.** Une demande en conflit avec le profil est contestée, avec les limites en chiffres.
- **Il sait aussi converser.** « Bonjour », « En quoi pouvez-vous m'aider? » ou « C'est quoi un FNB? » reçoivent
  une vraie réponse, pas un rapport de 20 secondes. Test réel : 29/29 messages bien routés (EN/FR), aucune
  question d'investissement manquée.
- **Rapide.** Réponse de conversation en environ 1,5 s ; analyse : premier texte en 4–6 s, réponse complète en
  13–17 s.

## AWS au cœur de la solution
Amazon Bedrock (Converse + ConverseStream, Claude Haiku 4.5 et Sonnet 4.6) · Bedrock Guardrails
(ApplyGuardrail, entrée et sortie) · Amazon S3 (données et traces d'exécution).
Région `us-east-1`. Détails : [architecture-aws.fr.md](architecture-aws.fr.md).

## Valeur d'affaires
Pour une banque, un courtier ou une plateforme d'éducation financière : un assistant qui **montre son
raisonnement**, respecte le profil du client et laisse une piste d'audit complète — ce qu'exigent les
conseillers, les équipes de conformité et les régulateurs.

**Limites :** données 2021–2026 du jeu de départ (biais du survivant), pas encore de nouvelles ni de données
ESG externes, limites des personas = hypothèses de l'équipe.

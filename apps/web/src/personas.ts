import type { PersonaId } from "@alphaforge/api-client";

export const PERSONAS: { id: PersonaId; name: string; blurb: string }[] = [
  { id: "amira", name: "Amira, 26 ans", blurb: "Ingénieure logiciel. Risque élevé, horizon de plus de 15 ans, s’intéresse à l’IA et aux cryptomonnaies." },
  { id: "mateo", name: "Mateo, 41 ans", blurb: "Gestionnaire des opérations. Risque modéré, horizon de 8 à 12 ans, forte préférence ESG." },
  { id: "robert", name: "Robert, 59 ans", blurb: "Professionnel de la santé. Risque faible à modéré, horizon de 3 à 5 ans, préservation du capital." },
];

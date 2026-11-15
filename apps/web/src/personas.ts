import type { PersonaId } from "@alphaforge/api-client";

// Names and ages for routing and headers before GET /personas answers (or if it fails).
// Descriptions are translated in i18n.tsx (`persona.<id>`); limits come from GET /personas.
export const PERSONAS: { id: PersonaId; name: string; age: number }[] = [
  { id: "amira", name: "Amira", age: 26 },
  { id: "mateo", name: "Mateo", age: 41 },
  { id: "robert", name: "Robert", age: 59 },
];

/** A profile built with the questionnaire (POST /profiles): "custom-" + 8 lowercase letters/digits. */
export function isCustomId(id: string | undefined): id is string {
  return /^custom-[a-z0-9]{8}$/.test(id ?? "");
}

export function personaById(id: string | undefined) {
  return PERSONAS.find((p) => p.id === id?.toLowerCase());
}

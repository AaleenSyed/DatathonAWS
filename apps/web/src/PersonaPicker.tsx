import type { PersonaId } from "@alphaforge/api-client";
import { AppBar } from "./AppBar";
import { PERSONAS } from "./personas";

export function PersonaPicker({ onPick }: { onPick: (id: PersonaId) => void }) {
  return (
    <div className="page">
      <AppBar />
      <main className="picker">
        <p className="eyebrow">Étape 1 de 2</p>
        <h1>Qui investit aujourd’hui?</h1>
        <p className="lead">
          Choisissez le profil d’investisseur fictif qui vous ressemble, puis posez vos questions sur les marchés et les
          portefeuilles en langage clair.
        </p>
        <div className="cards">
          {PERSONAS.map((p) => (
            <button key={p.id} className="card" onClick={() => onPick(p.id)}>
              <span className="avatar" aria-hidden="true">
                {p.name[0]}
              </span>
              <strong>{p.name}</strong>
              <span className="card-blurb">{p.blurb}</span>
              <span className="card-cta">
                Commencer <span aria-hidden="true">→</span>
              </span>
            </button>
          ))}
        </div>
        <p className="disclaimer">Simulation éducative. Ne constitue pas un conseil financier personnalisé.</p>
      </main>
    </div>
  );
}

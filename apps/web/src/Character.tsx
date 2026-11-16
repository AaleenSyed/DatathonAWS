import { useId, type ReactNode } from "react";
import type { PersonaId } from "@alphaforge/api-client";

// Illustrated, animated characters for the three built-in personas, drawn here as SVG (original artwork).
// Idle: breathing, a slow head tilt and blinking. Talking (`talking`): the mouth opens and closes and one
// hand comes up in a small gesture. All motion is CSS (styles.css, "Characters"), so the global
// prefers-reduced-motion rule leaves a still character.

interface Look {
  skin: string;
  skinShade: string;
  hair: string;
  top: string;
  topShade: string;
  collar: string;
  bg: [string, string];
  /** Drawn behind the head (long hair). */
  back?: ReactNode;
  /** Drawn over the head (hair, glasses, beard). */
  front: ReactNode;
}

const LOOKS: Record<PersonaId, Look> = {
  // Robert, 59: grey hair at the sides, round glasses, short grey beard, navy jacket.
  robert: {
    skin: "#e7b893",
    skinShade: "#cf9b76",
    hair: "#c7ccd4",
    top: "#2c3d63",
    topShade: "#22304f",
    collar: "#d6e3f5",
    bg: ["#3a2d66", "#1a1430"],
    front: (
      <>
        <path d="M40 48c-1-12 6-21 20-21s21 9 20 21c-2-6-4-9-6-10-4 3-24 3-28 0-2 1-4 4-6 10z" fill="#c7ccd4" />
        <path d="M41 63c2 13 10 20 19 20s17-7 19-20c-3 6-9 9-19 9s-16-3-19-9z" fill="#c7ccd4" opacity=".92" />
        <g fill="none" stroke="#dfe6f2" strokeWidth="1.6">
          <circle cx="52" cy="53" r="5.6" />
          <circle cx="68" cy="53" r="5.6" />
          <path d="M57.6 53h4.8M46.4 52l-5-1.5M73.6 52l5-1.5" />
        </g>
      </>
    ),
  },
  // Amira, 26: long dark wavy hair, small gold earrings, teal jacket over a white top.
  amira: {
    skin: "#b98159",
    skinShade: "#9f6a45",
    hair: "#2a1d19",
    top: "#1f7672",
    topShade: "#185d5a",
    collar: "#eef1f4",
    bg: ["#45306e", "#1e1534"],
    back: <path d="M36 54c-4-20 8-31 24-31s28 11 24 31c3 12 4 26-2 34H38c-6-8-5-22-2-34z" fill="#2a1d19" />,
    front: (
      <>
        <path d="M39 52c-1-15 8-24 21-24 14 0 23 9 21 24-5-9-13-14-21-15-3 5-12 10-21 15z" fill="#2a1d19" />
        <circle cx="39.6" cy="62" r="1.8" fill="none" stroke="#e2b74f" strokeWidth="1.3" />
        <circle cx="80.4" cy="62" r="1.8" fill="none" stroke="#e2b74f" strokeWidth="1.3" />
      </>
    ),
  },
  // Mateo, 41: short black hair, stubble, green sweater with a shirt collar.
  mateo: {
    skin: "#9a6847",
    skinShade: "#83553a",
    hair: "#1c1815",
    top: "#3c6a4a",
    topShade: "#30573c",
    collar: "#e4e8ee",
    bg: ["#3d2c5c", "#1b1429"],
    front: (
      <>
        <path d="M39 50c-2-15 7-24 21-24 15 0 23 9 21 22-3-5-6-8-9-9-6 4-19 5-28 2-2 2-4 5-5 9z" fill="#1c1815" />
        <path d="M42 64c3 11 10 18 18 18s15-7 18-18c-4 5-10 8-18 8s-14-3-18-8z" fill="#1c1815" opacity=".35" />
      </>
    ),
  },
};

export function Character({
  persona,
  talking = false,
  size = 56,
  className = "",
}: {
  persona: PersonaId;
  talking?: boolean;
  size?: number;
  className?: string;
}) {
  const uid = useId().replace(/:/g, "");
  const look = LOOKS[persona];
  if (!look) return null;
  const clip = `cc-${uid}`;
  const grad = `cg-${uid}`;
  return (
    <span
      className={`character character-${persona}${talking ? " talking" : ""} ${className}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 120 120" width={size} height={size}>
        <defs>
          <clipPath id={clip}>
            <circle cx="60" cy="60" r="58" />
          </clipPath>
          <radialGradient id={grad} cx="50%" cy="35%" r="70%">
            <stop offset="0" stopColor={look.bg[0]} />
            <stop offset="1" stopColor={look.bg[1]} />
          </radialGradient>
        </defs>
        <g clipPath={`url(#${clip})`}>
          <rect width="120" height="120" fill={`url(#${grad})`} />
          <g className="c-body">
            {look.back}
            {/* torso and collar */}
            <path d="M18 122c2-20 16-32 42-32s40 12 42 32z" fill={look.top} />
            <path d="M60 90c-8 0-14 1-19 4l19 14 19-14c-5-3-11-4-19-4z" fill={look.collar} />
            <path d="M41 94l8 18M79 94l-8 18" stroke={look.topShade} strokeWidth="3" strokeLinecap="round" />
            {/* neck */}
            <path d="M53 76h14v14c-3 3-11 3-14 0z" fill={look.skinShade} />
            <g className="c-head">
              {/* ears and face */}
              <ellipse cx="40.5" cy="56" rx="3.6" ry="5.4" fill={look.skinShade} />
              <ellipse cx="79.5" cy="56" rx="3.6" ry="5.4" fill={look.skinShade} />
              <ellipse cx="60" cy="54" rx="20" ry="24" fill={look.skin} />
              {/* brows */}
              <path className="c-brows" d="M47.5 45.5q4.5-2.4 9 0M63.5 45.5q4.5-2.4 9 0" fill="none"
                stroke={look.hair === "#c7ccd4" ? "#9aa1ab" : look.hair} strokeWidth="1.9" strokeLinecap="round" />
              {/* eyes (blink by scaling Y) */}
              <g className="c-eyes">
                <ellipse cx="52" cy="53" rx="2.3" ry="2.6" fill="#1b1b22" />
                <ellipse cx="68" cy="53" rx="2.3" ry="2.6" fill="#1b1b22" />
                <circle cx="52.8" cy="52.2" r=".7" fill="#fff" />
                <circle cx="68.8" cy="52.2" r=".7" fill="#fff" />
              </g>
              {/* nose */}
              <path d="M60 55.5c-1 3-2 5.5-.6 6.3" fill="none" stroke={look.skinShade} strokeWidth="1.6" strokeLinecap="round" />
              {/* cheeks */}
              <circle cx="48" cy="62" r="3.2" fill="#e0726b" opacity=".18" />
              <circle cx="72" cy="62" r="3.2" fill="#e0726b" opacity=".18" />
              {look.front}
              {/* mouth: closed smile, or an open mouth that moves while talking */}
              <path className="c-mouth-closed" d="M54.5 67q5.5 3.6 11 0" fill="none" stroke="#6b2c33" strokeWidth="1.8"
                strokeLinecap="round" />
              <g className="c-mouth-open">
                <ellipse cx="60" cy="68" rx="4.6" ry="3.2" fill="#5b222b" />
                <ellipse cx="60" cy="69.6" rx="2.6" ry="1.2" fill="#c9636b" />
              </g>
            </g>
          </g>
          {/* hand for the talking gesture (hidden below the frame when idle) */}
          <g className="c-hand">
            <path d="M86 120v-17c0-2.4 3.6-2.4 3.6 0v-6c0-2.4 3.6-2.4 3.6 0v-1.5c0-2.4 3.6-2.4 3.6 0v2c0-2.4 3.6-2.4 3.6 0v12
              l2.4-4c1.4-2.2 4.4-.8 3.4 1.6L101 120z" fill={look.skin} stroke={look.skinShade} strokeWidth="1" />
            <rect x="84" y="114" width="22" height="10" rx="2" fill={look.top} />
          </g>
        </g>
        <circle cx="60" cy="60" r="58.5" fill="none" stroke="rgb(255 255 255 / 14%)" strokeWidth="1.5" />
      </svg>
    </span>
  );
}

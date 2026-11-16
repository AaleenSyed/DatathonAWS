import { useEffect, useRef, useState } from "react";

// Fixed background: three layers of stars that drift slowly at different speeds (parallax), twinkle, and an
// occasional shooting star. Canvas 2D, capped at 30 frames per second, paused while the tab is hidden.
// With prefers-reduced-motion the same field is drawn once and never animated. Dark theme only: the canvas is
// transparent and sits over the page's own purple background and glow; in the light theme nothing is drawn.

const FPS = 30;
const FRAME_MS = 1000 / FPS;
// Per layer: share of the stars, radius range (CSS px), peak opacity, drift speed (px per second).
const LAYERS = [
  { share: 0.62, r: [0.35, 0.8], alpha: 0.55, speed: 1.2 },
  { share: 0.28, r: [0.6, 1.1], alpha: 0.75, speed: 2.6 },
  { share: 0.1, r: [0.9, 1.5], alpha: 0.9, speed: 4.5 },
] as const;
// Mostly white, a few lavender stars (the dark theme's --link and --primary).
const TINTS = ["255,255,255", "255,255,255", "236,228,250", "201,184,242", "185,163,234"];
const TRAIL = "201,184,242"; // shooting-star trail, lavender

interface Star {
  x: number;
  y: number;
  r: number;
  alpha: number;
  layer: number;
  tint: string;
  phase: number; // twinkle phase
  rate: number; // twinkle speed (radians per second)
}

interface Meteor {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number; // seconds left
  total: number;
}

function rand(min: number, max: number) {
  return min + Math.random() * (max - min);
}

function makeStars(w: number, h: number): Star[] {
  // About one star per 4,500 px², at most 420.
  const count = Math.min(420, Math.round((w * h) / 4500));
  const stars: Star[] = [];
  LAYERS.forEach((layer, i) => {
    const n = Math.round(count * layer.share);
    for (let k = 0; k < n; k++) {
      stars.push({
        x: Math.random() * w,
        y: Math.random() * h,
        r: rand(layer.r[0], layer.r[1]),
        alpha: layer.alpha * rand(0.45, 1),
        layer: i,
        tint: TINTS[Math.floor(Math.random() * TINTS.length)],
        phase: Math.random() * Math.PI * 2,
        rate: rand(0.4, 1.6),
      });
    }
  });
  return stars;
}

const isDark = () => document.documentElement.dataset.theme === "dark";

/** True while <html data-theme="dark">; follows the theme switch. */
function useDarkTheme() {
  const [dark, setDark] = useState(isDark);
  useEffect(() => {
    const obs = new MutationObserver(() => setDark(isDark()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    setDark(isDark());
    return () => obs.disconnect();
  }, []);
  return dark;
}

export function Starfield() {
  const dark = useDarkTheme();
  return dark ? <StarCanvas /> : null;
}

function StarCanvas() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let w = 0;
    let h = 0;
    let stars: Star[] = [];
    let meteor: Meteor | null = null;
    let nextMeteor = rand(4, 9); // seconds until the first shooting star
    let raf = 0;
    let last = 0;
    let acc = 0;
    let time = 0;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas!.width = Math.round(w * dpr);
      canvas!.height = Math.round(h * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      stars = makeStars(w, h);
    }

    function draw(animated: boolean) {
      ctx!.clearRect(0, 0, w, h);
      for (const s of stars) {
        const twinkle = animated ? 0.72 + 0.28 * Math.sin(s.phase + time * s.rate) : 0.86;
        ctx!.fillStyle = `rgba(${s.tint},${(s.alpha * twinkle).toFixed(3)})`;
        ctx!.beginPath();
        ctx!.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx!.fill();
      }
      if (meteor) {
        const k = meteor.life / meteor.total; // 1 -> 0
        const tail = 110;
        const len = Math.hypot(meteor.vx, meteor.vy);
        const tx = meteor.x - (meteor.vx / len) * tail;
        const ty = meteor.y - (meteor.vy / len) * tail;
        const g = ctx!.createLinearGradient(meteor.x, meteor.y, tx, ty);
        g.addColorStop(0, `rgba(${TRAIL},${(0.75 * Math.min(1, k * 2)).toFixed(3)})`);
        g.addColorStop(1, `rgba(${TRAIL},0)`);
        ctx!.strokeStyle = g;
        ctx!.lineWidth = 1.2;
        ctx!.lineCap = "round";
        ctx!.beginPath();
        ctx!.moveTo(meteor.x, meteor.y);
        ctx!.lineTo(tx, ty);
        ctx!.stroke();
      }
    }

    function step(dt: number) {
      time += dt;
      for (const s of stars) {
        // Slow drift to the left; nearer layers move faster.
        s.x -= LAYERS[s.layer].speed * dt;
        if (s.x < -2) {
          s.x = w + 2;
          s.y = Math.random() * h;
        }
      }
      if (meteor) {
        meteor.x += meteor.vx * dt;
        meteor.y += meteor.vy * dt;
        meteor.life -= dt;
        if (meteor.life <= 0) meteor = null;
      } else {
        nextMeteor -= dt;
        if (nextMeteor <= 0) {
          const angle = rand(0.35, 0.6); // radians below horizontal, moving left to right and down
          const speed = rand(520, 760);
          const total = rand(0.7, 1.1);
          meteor = {
            x: rand(w * 0.05, w * 0.7),
            y: rand(0, h * 0.4),
            vx: Math.cos(angle) * speed,
            vy: Math.sin(angle) * speed,
            life: total,
            total,
          };
          nextMeteor = rand(7, 16);
        }
      }
    }

    function frame(now: number) {
      raf = requestAnimationFrame(frame);
      if (!last) last = now;
      acc += now - last;
      last = now;
      if (acc < FRAME_MS) return; // cap the frame rate
      const dt = Math.min(acc, 100) / 1000; // after a long gap, do not jump
      acc = 0;
      step(dt);
      draw(true);
    }

    function start() {
      cancelAnimationFrame(raf);
      raf = 0;
      if (motion.matches) {
        meteor = null;
        draw(false);
        return;
      }
      if (document.hidden) return;
      last = 0;
      acc = 0;
      raf = requestAnimationFrame(frame);
    }

    function onVisibility() {
      if (document.hidden) {
        cancelAnimationFrame(raf);
        raf = 0;
      } else start();
    }

    function onResize() {
      resize();
      if (motion.matches || document.hidden) draw(false);
    }

    resize();
    start();
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);
    motion.addEventListener("change", start);
    return () => {
      cancelAnimationFrame(raf);
      raf = 0;
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
      motion.removeEventListener("change", start);
    };
  }, []);

  return <canvas ref={ref} className="starfield" aria-hidden="true" />;
}

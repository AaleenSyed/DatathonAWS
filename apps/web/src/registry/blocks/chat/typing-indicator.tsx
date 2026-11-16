import { cn } from "@/lib/utils";

/**
 * Three pulsing dots while the assistant is working, with a text equivalent for screen readers (`label`).
 * With `prefers-reduced-motion` the dots stop moving and stay visible.
 */
export function TypingIndicator({ label = "Typing", className }: { label?: string; className?: string }) {
  return (
    <div
      role="status"
      className={cn("inline-flex w-fit items-center gap-1.5 rounded-full bg-[var(--surface-2)] px-3.5 py-3", className)}
    >
      <span className="sr-only">{label}</span>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          aria-hidden="true"
          className="size-2 rounded-full bg-[var(--muted)] motion-safe:animate-typing"
          style={{ animationDelay: `${i * 0.16}s` }}
        />
      ))}
    </div>
  );
}

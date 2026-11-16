import { cn } from "@/lib/utils";

// Button styles in the shadcn/ui shape (variant + size). No Preflight, so every variant sets its own border
// and background. Focus uses the app-wide 3px outline from styles.css.
const BASE =
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-full border " +
  "font-medium leading-none transition-[background-color,border-color,color,transform] duration-150 " +
  "active:scale-[.97] disabled:pointer-events-none disabled:opacity-50 " +
  "[@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:min-w-11";

const VARIANTS = {
  default: "border-transparent bg-primary text-primary-foreground hover:bg-[var(--primary-hover)]",
  outline: "border-input bg-transparent text-foreground hover:border-primary hover:bg-accent",
  secondary: "border-transparent bg-secondary text-secondary-foreground hover:bg-accent",
  ghost: "border-transparent bg-transparent text-muted-foreground hover:bg-accent hover:text-foreground",
} as const;

// Targets: 44px by default (WCAG 2.5.8 asks 24px, 44px is the touch aim). The compact sizes grow to 44px on touch
// screens through the `pointer: coarse` rule in BASE.
const SIZES = {
  lg: "h-12 px-7 text-base",
  default: "h-11 px-5 text-[0.95rem]",
  sm: "h-9 px-4 text-sm",
  xs: "h-8 px-3 text-sm",
  icon: "size-11 p-0",
  "icon-sm": "size-8 p-0",
} as const;

export function buttonVariants({
  variant = "default",
  size = "default",
  className,
}: { variant?: keyof typeof VARIANTS; size?: keyof typeof SIZES; className?: string } = {}) {
  return cn(BASE, VARIANTS[variant], SIZES[size], className);
}

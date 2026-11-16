import { forwardRef, type HTMLAttributes, type ReactNode, type Ref } from "react";
import { cn } from "@/lib/utils";

export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessageProps extends Omit<HTMLAttributes<HTMLElement>, "content" | "role"> {
  /** user = right-aligned grape bubble, assistant = left-aligned celadon bubble with avatar, system = centered note. */
  role: ChatRole;
  /** Message text (plain text, line breaks kept). Use `children` for rich content instead. */
  content?: string;
  children?: ReactNode;
  /** Assistant avatar (left of the message). */
  avatar?: ReactNode;
  /** Visible author label above assistant messages. */
  name?: ReactNode;
  /** Read by screen readers before the message: "You said:" / "Robert said:". Sender is never colour-only. */
  srLabel?: string;
  /** Extra controls next to the author label (e.g. a version switcher). */
  meta?: ReactNode;
  /** Buttons under the message (edit, regenerate…): always visible on touch, on hover / focus elsewhere. */
  actions?: ReactNode;
  /** Keep the actions visible without hover (e.g. on the latest message). */
  actionsVisible?: boolean;
  /** System only: an error note. */
  variant?: "default" | "destructive";
  /** Classes for the bubble itself (`className` styles the outer row). */
  bubbleClassName?: string;
}

// Hover-only actions are still reachable by keyboard: they show on focus-within, and always on touch screens.
const ACTIONS =
  "flex min-h-8 flex-wrap items-center gap-1 transition-opacity duration-150 " +
  "[@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 " +
  "[@media(hover:hover)]:group-focus-within:opacity-100";
const ACTIONS_SHOWN = "flex min-h-8 flex-wrap items-center gap-1";

export const ChatMessage = forwardRef<HTMLElement, ChatMessageProps>(function ChatMessage(
  {
    role, content, children, avatar, name, srLabel, meta, actions, actionsVisible, variant = "default",
    className, bubbleClassName, ...rest
  },
  ref,
) {
  const body = children ?? <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{content}</p>;
  const actionRow = actions && <div className={actionsVisible ? ACTIONS_SHOWN : ACTIONS}>{actions}</div>;
  const said = srLabel && <span className="sr-only">{srLabel} </span>;

  if (role === "system") {
    const destructive = variant === "destructive";
    return (
      <div
        ref={ref as Ref<HTMLDivElement>}
        role={destructive ? "alert" : "note"}
        className={cn(
          "max-w-full self-center text-center text-sm leading-relaxed [overflow-wrap:anywhere]",
          destructive
            ? "rounded-xl border border-destructive bg-[var(--conflict-soft)] px-4 py-3 text-[var(--conflict-ink)]"
            : "rounded-full border border-border bg-card px-4 py-1.5 text-muted-foreground",
          className,
        )}
        {...rest}
      >
        {body}
      </div>
    );
  }

  if (role === "user") {
    return (
      <article
        ref={ref}
        className={cn(
          "group relative flex max-w-[min(88%,34rem)] scroll-mt-4 flex-col items-end gap-1.5 self-end",
          className,
        )}
        {...rest}
      >
        {meta && <div className="flex items-center gap-2 text-sm text-muted-foreground">{meta}</div>}
        <div
          className={cn(
            "rounded-2xl rounded-br-md bg-[var(--bubble-user)] px-4 py-3 text-base leading-normal",
            "text-[var(--on-bubble-user)] shadow-sm",
            bubbleClassName,
          )}
        >
          {said}
          {body}
        </div>
        {actionRow}
      </article>
    );
  }

  return (
    <article
      ref={ref}
      className={cn("group flex w-full min-w-0 scroll-mt-4 gap-2.5 self-start sm:gap-3", className)}
      {...rest}
    >
      {avatar && <div className="mt-0.5 hidden shrink-0 sm:block">{avatar}</div>}
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        {(name || meta) && (
          <div className="flex min-h-8 flex-wrap items-center gap-x-3 gap-y-1">
            {/* The visible name is hidden from screen readers: the "X said:" label in the bubble replaces it. */}
            {name && (
              <span aria-hidden={srLabel ? "true" : undefined} className="text-sm font-semibold text-foreground">
                {name}
              </span>
            )}
            {meta}
          </div>
        )}
        <div
          className={cn(
            "persona-bubble min-w-0 rounded-2xl rounded-tl-md border border-[var(--bubble-ai-line)]",
            "bg-[var(--bubble-ai)] px-3 py-3 text-base leading-normal text-[var(--bubble-ai-ink)] shadow-sm sm:px-5 sm:py-4",
            bubbleClassName,
          )}
        >
          {said}
          {body}
        </div>
        {actionRow}
      </div>
    </article>
  );
});

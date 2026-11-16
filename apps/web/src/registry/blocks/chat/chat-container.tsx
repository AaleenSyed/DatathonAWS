import { Children, forwardRef, isValidElement, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { ChatInput } from "./chat-input";

export interface ChatContainerProps extends HTMLAttributes<HTMLDivElement> {
  /** Classes for the message column inside the scroll area (width, gap, padding). */
  contentClassName?: string;
  /** An answer is being written: screen readers wait until it is complete before reading it. */
  busy?: boolean;
  /** Accessible name of the message list. */
  logLabel?: string;
}

/**
 * Full-height chat: messages scroll in a `role="log"` region (polite live updates), a <ChatInput> child stays
 * docked under them. The message column is 720px wide at most and centered.
 * Usage (chat-ui skill): <ChatContainer>{messages}{typing && <TypingIndicator />}<ChatInput … /></ChatContainer>
 * The ref points at the scroll area.
 */
export const ChatContainer = forwardRef<HTMLDivElement, ChatContainerProps>(function ChatContainer(
  { children, className, contentClassName, busy, logLabel, ...rest },
  ref,
) {
  const body: ReactNode[] = [];
  const dock: ReactNode[] = [];
  for (const child of Children.toArray(children)) {
    (isValidElement(child) && child.type === ChatInput ? dock : body).push(child);
  }
  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", className)} {...rest}>
      {/* relative: absolutely positioned children (e.g. sr-only labels) stay inside the scroll area. */}
      <div
        ref={ref}
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        aria-busy={busy || undefined}
        aria-label={logLabel}
        tabIndex={0}
        className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain"
      >
        <div
          className={cn(
            "mx-auto flex min-h-full w-full max-w-[calc(var(--col)+2.5rem)] flex-col gap-5 px-3 py-5 sm:gap-6 sm:px-5 sm:py-6",
            contentClassName,
          )}
        >
          {body}
        </div>
      </div>
      {dock}
    </div>
  );
});

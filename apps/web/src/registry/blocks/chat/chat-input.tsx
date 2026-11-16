import {
  useId, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode,
} from "react";
import { cn } from "@/lib/utils";

export interface ChatInputProps {
  /** Called with the trimmed text. Return false to keep the text in the field (e.g. the send failed). */
  onSubmit: (message: string) => boolean | void;
  placeholder?: string;
  /** Disables the field and the send button (e.g. not connected). */
  disabled?: boolean;
  /** An answer is being written: the field stays usable, the send button becomes a stop button. */
  isGenerating?: boolean;
  onStop?: () => void;
  sendLabel?: string;
  stopLabel?: string;
  /** Label of the field (read by screen readers, not shown). */
  label: string;
  /** Shown above the field (e.g. suggested questions). */
  children?: ReactNode;
  /** Small text under the field (e.g. a disclaimer). */
  hint?: ReactNode;
  className?: string;
}

const MAX_HEIGHT = 200; // px; the field grows with its text up to this, then scrolls

/** Message bar: Enter sends, Shift+Enter adds a line. Docked under the messages by <ChatContainer>. */
export function ChatInput({
  onSubmit,
  placeholder = "Type a message...",
  disabled = false,
  isGenerating = false,
  onStop,
  sendLabel = "Send",
  stopLabel = "Stop",
  label,
  children,
  hint,
  className,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const field = useRef<HTMLTextAreaElement>(null);
  const id = useId();
  const canSend = !disabled && !isGenerating && value.trim().length > 0;

  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!canSend) return;
    if (onSubmit(value.trim()) !== false) setValue("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className={cn("shrink-0 bg-background px-3 pb-3 pt-2 sm:px-5", className)}>
      <div className="mx-auto flex w-full max-w-[var(--col)] flex-col gap-2">
        {children}
        <form
          onSubmit={submit}
          aria-label={label}
          className={cn(
            "flex items-end gap-2 rounded-[1.75rem] border border-input bg-card py-1.5 pl-5 pr-1.5 shadow-sm",
            "transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-2 focus-within:ring-ring",
            disabled && "opacity-70",
          )}
        >
          <label htmlFor={id} className="sr-only">
            {label}
          </label>
          <textarea
            id={id}
            ref={field}
            rows={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            enterKeyHint="send"
            className={cn(
              "max-h-[200px] min-h-11 flex-1 resize-none self-center border-0 bg-transparent py-2.5 text-base leading-6",
              "text-foreground placeholder:text-muted-foreground focus-visible:outline-none disabled:cursor-not-allowed",
            )}
          />
          {isGenerating ? (
            <button
              type="button"
              onClick={onStop}
              aria-label={stopLabel}
              title={stopLabel}
              className={cn(
                "grid size-11 shrink-0 cursor-pointer place-items-center rounded-full border border-input bg-transparent",
                "text-foreground transition-colors hover:bg-accent active:scale-95",
              )}
            >
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                <rect x="5" y="5" width="14" height="14" rx="2.5" fill="currentColor" />
              </svg>
            </button>
          ) : (
            <button
              type="submit"
              disabled={!canSend}
              aria-label={sendLabel}
              title={sendLabel}
              className={cn(
                "grid size-11 shrink-0 cursor-pointer place-items-center rounded-full border-0 bg-primary",
                "text-primary-foreground transition-[background-color,transform] hover:bg-[var(--primary-hover)] active:scale-95",
                "disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100",
              )}
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.2"
                strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />
              </svg>
            </button>
          )}
        </form>
        {hint && <p className="px-2 text-center text-xs leading-snug text-muted-foreground">{hint}</p>}
      </div>
    </div>
  );
}

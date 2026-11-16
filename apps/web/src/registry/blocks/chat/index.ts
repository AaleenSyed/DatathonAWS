// Chat building blocks following the chat-ui skill (ui.inference.sh "chat" registry API):
// ChatContainer, ChatMessage (user / assistant / system), ChatInput, TypingIndicator.
// Written locally because the registry URL (https://ui.inference.sh/r/chat.json) no longer resolves.
export { ChatContainer, type ChatContainerProps } from "./chat-container";
export { ChatMessage, type ChatMessageProps, type ChatRole } from "./chat-message";
export { ChatInput, type ChatInputProps } from "./chat-input";
export { TypingIndicator } from "./typing-indicator";

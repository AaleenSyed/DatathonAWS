import type { components } from "./generated/schema.js";

type S = components["schemas"];

export type User = S["User"];
export type PersonaId = S["PersonaId"];
export type Conversation = S["Conversation"];
export type Message = S["Message"];
export type MessageStatus = S["MessageStatus"];
export type ToolCall = S["ToolCall"];
export type Claim = S["Claim"];
export type GovernanceResult = S["GovernanceResult"];
export type ExplainerPayload = S["ExplainerPayload"];
export type ApiError = S["Error"];

export type WsClientMessage = S["WsClientMessage"];
export type WsServerMessage = S["WsServerMessage"];
export type WsServerMessageType = WsServerMessage["type"];

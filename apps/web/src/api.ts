import { ChatSocket, createApiClient } from "@alphaforge/api-client";

// Default: same origin, under <base>api. The Vite dev server forwards it to the backend,
// so this works on localhost and behind a path proxy without CORS or mixed-content problems.
// Set VITE_API_BASE_URL / VITE_WS_URL to point at a deployed backend instead.
const sameOriginApi = `${location.origin}${import.meta.env.BASE_URL}api`;
const baseUrl = import.meta.env.VITE_API_BASE_URL || sameOriginApi;
const wsUrl = import.meta.env.VITE_WS_URL || `${sameOriginApi.replace(/^http/, "ws")}/ws`;

// TODO: replace with the Cognito ID token once sign-in is wired.
const getToken = () => (import.meta.env.VITE_DEV_TOKEN as string | undefined) || null;

export const api = createApiClient({ baseUrl, getToken });

export function createChatSocket(): ChatSocket {
  return new ChatSocket({
    url: wsUrl,
    getTicket: async () => {
      const { data, error } = await api.POST("/ws-ticket");
      if (error || !data) throw new Error("Could not get a WebSocket ticket");
      return data.ticket;
    },
  });
}

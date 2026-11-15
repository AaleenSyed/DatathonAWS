import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./generated/schema.js";

export interface ApiClientOptions {
  /** Base URL of the API, e.g. http://localhost:8000 */
  baseUrl: string;
  /** Returns the current Cognito ID token, or null when signed out. Called on every request. */
  getToken: () => Promise<string | null> | string | null;
  /** Custom fetch (tests, React Native polyfills). Defaults to the global fetch. */
  fetch?: typeof fetch;
}

/** Typed REST client. Every path, parameter and response comes from contracts/openapi.yaml. */
export function createApiClient(options: ApiClientOptions) {
  const client = createClient<paths>({
    baseUrl: options.baseUrl,
    fetch: options.fetch,
  });

  const auth: Middleware = {
    async onRequest({ request }) {
      const token = await options.getToken();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
  };
  client.use(auth);

  return client;
}

export type ApiClient = ReturnType<typeof createApiClient>;

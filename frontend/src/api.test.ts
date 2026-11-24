/** The API client: error envelope, auth header, and the click-event guard. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  executePipeline,
  generatePipeline,
  getAccessToken,
  getHealth,
  setAccessToken,
  uploadDataset,
} from "./api";

function respond(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

let fetchMock: ReturnType<typeof respond>;

beforeEach(() => {
  window.localStorage.clear();
  fetchMock = respond(200, {});
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function lastCall() {
  const [url, init] = fetchMock.mock.calls.at(-1) as unknown as [string, RequestInit];
  return { url, init, headers: new Headers(init.headers) };
}

describe("api client", () => {
  it("unwraps the error envelope into an ApiError", async () => {
    fetchMock = respond(422, {
      error: { code: "DUPLICATE_COLUMNS", message: "Duplicate: id", retryable: false, details: {} },
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(uploadDataset(new File(["a,b"], "x.csv"))).rejects.toMatchObject({
      detail: { code: "DUPLICATE_COLUMNS", retryable: false },
    });
  });

  it("synthesises a retryable detail when the network fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    const error = await getHealth().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).detail).toMatchObject({ code: "NETWORK_ERROR", retryable: true });
  });

  it("sends no Authorization header without a token", async () => {
    await getHealth();
    expect(lastCall().headers.has("Authorization")).toBe(false);
  });

  it("sends the stored token as a bearer header", async () => {
    setAccessToken("  team-token  ");
    await getHealth();
    expect(lastCall().headers.get("Authorization")).toBe("Bearer team-token");
  });

  it("drops a token the server refuses", async () => {
    setAccessToken("stale");
    fetchMock = respond(401, {
      error: { code: "UNAUTHORIZED", message: "no", retryable: false, details: {} },
    });
    vi.stubGlobal("fetch", fetchMock);
    await getHealth().catch(() => undefined);
    expect(getAccessToken()).toBeNull();
  });

  it("never serialises a click event as the exclusion list", async () => {
    // The miswiring documented in docs/development.md: onClick={generate}
    // passes a MouseEvent as the first parameter.
    const event = new MouseEvent("click") as unknown as string[];
    await generatePipeline("ds-1", event);
    expect(JSON.parse(lastCall().init.body as string)).toEqual({ excluded_columns: [] });
  });

  it("sends only strings in the exclusion list", async () => {
    await generatePipeline("ds-1", ["plan", 3 as unknown as string]);
    expect(JSON.parse(lastCall().init.body as string)).toEqual({ excluded_columns: ["plan"] });
  });

  it("execute sends no body - the server runs only code it stored", async () => {
    await executePipeline("ds-1");
    const { url, init } = lastCall();
    expect(url).toMatch(/\/datasets\/ds-1\/execute$/);
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });
});

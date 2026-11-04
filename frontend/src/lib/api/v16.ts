/**
 * QUANT EDGE V16: Centralized API Client
 * Connects to live V16 Backend using configured NEXT_PUBLIC_API_URL or relative proxy.
 * Strict zero-fabrication: returns actual responses or handles errors gracefully.
 */

import {
  V16SignalsResponse,
  V16ThesesResponse,
  V16EventsResponse,
  V16RegimeResponse,
  V16EndpointHealth,
} from "@/types/v16";

const getApiBase = (): string => {
  if (typeof window !== "undefined") {
    // Client-side: use existing reverse proxy path if on domain, or env
    return process.env.NEXT_PUBLIC_API_URL || "";
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
};

async function fetchWithHealth<T>(
  path: string
): Promise<{ data: T | null; health: V16EndpointHealth; error?: string }> {
  const sep = path.includes("?") ? "&" : "?";
  const nonce = Math.random().toString(36).slice(2, 8);
  const url = `${getApiBase()}${path}${sep}_t=${Date.now()}&_nonce=${nonce}`;
  const start = performance.now();
  const nowStr = new Date().toISOString().substring(11, 19) + " UTC";

  try {
    const res = await fetch(url, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        Pragma: "no-cache",
      },
    });
    const latency = Math.round(performance.now() - start);

    if (!res.ok) {
      return {
        data: null,
        health: {
          endpoint: path,
          status: res.status,
          latencyMs: latency,
          lastUpdated: nowStr,
          itemCount: 0,
        },
        error: `HTTP ${res.status}: ${res.statusText}`,
      };
    }

    const json = (await res.json()) as T;
    let count = 0;
    if (Array.isArray((json as any)?.data)) {
      count = (json as any).data.length;
    } else if (typeof json === "object" && json !== null) {
      count = 1;
    }

    return {
      data: json,
      health: {
        endpoint: path,
        status: res.status,
        latencyMs: latency,
        lastUpdated: nowStr,
        itemCount: count,
      },
    };
  } catch (err: any) {
    const latency = Math.round(performance.now() - start);
    return {
      data: null,
      health: {
        endpoint: path,
        status: "ERR",
        latencyMs: latency,
        lastUpdated: nowStr,
        itemCount: 0,
      },
      error: err?.message || "Network request failed",
    };
  }
}

export const v16Api = {
  getSignals: async (params?: { status?: string; symbol?: string }) => {
    let query = "";
    if (params) {
      const q = new URLSearchParams();
      if (params.status) q.append("status", params.status);
      if (params.symbol) q.append("symbol", params.symbol);
      const str = q.toString();
      if (str) query = `?${str}`;
    }
    return fetchWithHealth<V16SignalsResponse>(`/api/v16/signals${query}`);
  },

  getTheses: async () => {
    return fetchWithHealth<V16ThesesResponse>(`/api/v16/theses`);
  },

  getEvents: async (limit = 100) => {
    return fetchWithHealth<V16EventsResponse>(`/api/v16/events?limit=${limit}`);
  },

  getRegime: async () => {
    return fetchWithHealth<V16RegimeResponse>(`/api/v16/regime`);
  },

  getStatus: async () => {
    return fetchWithHealth<any>(`/api/v16/status`);
  },

  getValidation: async (cohort = "current") => {
    return fetchWithHealth<any>(`/api/v16/validation?cohort=${cohort}`);
  },
};

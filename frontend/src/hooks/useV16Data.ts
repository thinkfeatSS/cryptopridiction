"use client";

import { useQuery } from "@tanstack/react-query";
import { v16Api } from "@/lib/api/v16";
import {
  V16SignalEnvelope,
  V16TradeThesis,
  V16AuditEvent,
  V16RegimeResponse,
  V16EndpointHealth,
} from "@/types/v16";

export function useV16Signals(filters?: { status?: string; symbol?: string }) {
  return useQuery<{
    signals: V16SignalEnvelope[];
    total: number;
    health: V16EndpointHealth;
    error?: string;
  }>({
    queryKey: ["v16-signals", filters?.status, filters?.symbol],
    queryFn: async () => {
      const res = await v16Api.getSignals(filters);
      return {
        signals: res.data?.data || [],
        total: res.data?.total || 0,
        health: res.health,
        error: res.error,
      };
    },
    refetchInterval: 10000, // 10s auto-refresh
    staleTime: 3000,
    refetchOnWindowFocus: true,
    retry: 2,
  });
}

export function useV16Theses() {
  return useQuery<{
    theses: V16TradeThesis[];
    total: number;
    health: V16EndpointHealth;
    error?: string;
  }>({
    queryKey: ["v16-theses"],
    queryFn: async () => {
      const res = await v16Api.getTheses();
      return {
        theses: res.data?.data || [],
        total: res.data?.total_theses || 0,
        health: res.health,
        error: res.error,
      };
    },
    refetchInterval: 15000,
    staleTime: 5000,
    refetchOnWindowFocus: true,
    retry: 2,
  });
}

export function useV16Events(limit = 100) {
  return useQuery<{
    events: V16AuditEvent[];
    count: number;
    health: V16EndpointHealth;
    error?: string;
  }>({
    queryKey: ["v16-events", limit],
    queryFn: async () => {
      const res = await v16Api.getEvents(limit);
      return {
        events: res.data?.data || [],
        count: res.data?.count || 0,
        health: res.health,
        error: res.error,
      };
    },
    refetchInterval: 10000,
    staleTime: 3000,
    refetchOnWindowFocus: true,
    retry: 2,
  });
}

export function useV16Regime() {
  return useQuery<{
    regime: V16RegimeResponse | null;
    health: V16EndpointHealth;
    error?: string;
  }>({
    queryKey: ["v16-regime"],
    queryFn: async () => {
      const res = await v16Api.getRegime();
      return {
        regime: res.data,
        health: res.health,
        error: res.error,
      };
    },
    refetchInterval: 15000,
    staleTime: 5000,
    refetchOnWindowFocus: true,
    retry: 2,
  });
}

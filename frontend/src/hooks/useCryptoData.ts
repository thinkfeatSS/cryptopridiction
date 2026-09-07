"use client";

import { useQuery } from "@tanstack/react-query";
import {
  fetchKpi,
  fetchDailySummary,
  fetchSignals,
  fetchSignalsBySymbol,
  fetchPortfolio,
  fetchForecast,
  fetchStatus,
} from "@/lib/api";

export function useKpiQuery() {
  return useQuery({
    queryKey: ["kpi"],
    queryFn: fetchKpi,
    refetchInterval: 5000,
  });
}

export function useDailySummaryQuery() {
  return useQuery({
    queryKey: ["dailySummary"],
    queryFn: fetchDailySummary,
    refetchInterval: 8000,
  });
}

export function useSignalsQuery(params?: {
  search?: string;
  date?: string;
  outcome?: string;
  grade?: string;
  horizon?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ["signals", params],
    queryFn: () => fetchSignals(params),
    refetchInterval: 5000,
  });
}

export function useCoinSignalsQuery(symbol?: string) {
  return useQuery({
    queryKey: ["coinSignals", symbol],
    queryFn: () => (symbol ? fetchSignalsBySymbol(symbol) : Promise.resolve([])),
    enabled: !!symbol,
    refetchInterval: 6000,
  });
}

export function usePortfolioQuery() {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: fetchPortfolio,
    refetchInterval: 5000,
  });
}

export function useForecastQuery() {
  return useQuery({
    queryKey: ["forecast"],
    queryFn: fetchForecast,
    refetchInterval: 6000,
  });
}

export function useStatusQuery() {
  return useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    refetchInterval: 2500,
  });
}

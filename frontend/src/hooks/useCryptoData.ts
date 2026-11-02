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
  fetchLivePrices,
} from "@/lib/api";

export function useKpiQuery() {
  return useQuery({
    queryKey: ["kpi"],
    queryFn: fetchKpi,
    refetchInterval: 12000,
    staleTime: 5000,
    refetchOnWindowFocus: true,
  });
}

export function useDailySummaryQuery() {
  return useQuery({
    queryKey: ["dailySummary"],
    queryFn: fetchDailySummary,
    refetchInterval: 15000,
    staleTime: 5000,
    refetchOnWindowFocus: true,
  });
}

export function useSignalsQuery(params?: {
  search?: string;
  date?: string;
  outcome?: string;
  grade?: string;
  horizon?: string;
  direction?: string;
  min_return?: number;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ["signals", params],
    queryFn: () => fetchSignals(params),
    refetchInterval: 10000,
    staleTime: 3000,
    refetchOnWindowFocus: true,
  });
}

export function useCoinSignalsQuery(symbol?: string) {
  return useQuery({
    queryKey: ["coinSignals", symbol],
    queryFn: () => (symbol ? fetchSignalsBySymbol(symbol) : Promise.resolve([])),
    enabled: !!symbol,
    refetchInterval: 10000,
    staleTime: 3000,
    refetchOnWindowFocus: true,
  });
}

export function usePortfolioQuery() {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: fetchPortfolio,
    refetchInterval: 8000,
    staleTime: 3000,
    refetchOnWindowFocus: true,
  });
}

export function useForecastQuery() {
  return useQuery({
    queryKey: ["forecast"],
    queryFn: fetchForecast,
    refetchInterval: 8000,
    staleTime: 3000,
    refetchOnWindowFocus: true,
  });
}

export function useStatusQuery() {
  return useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    refetchInterval: 3000,
    staleTime: 1500,
    refetchOnWindowFocus: true,
  });
}

export function useLivePricesQuery() {
  return useQuery({
    queryKey: ["livePrices"],
    queryFn: fetchLivePrices,
    refetchInterval: 2500,
    staleTime: 1000,
    refetchOnWindowFocus: true,
  });
}

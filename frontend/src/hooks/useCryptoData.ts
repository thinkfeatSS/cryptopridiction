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
    refetchInterval: 20000,
    staleTime: 10000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

export function useDailySummaryQuery() {
  return useQuery({
    queryKey: ["dailySummary"],
    queryFn: fetchDailySummary,
    refetchInterval: 20000,
    staleTime: 10000,
    refetchIntervalInBackground: false,
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
    refetchInterval: 15000,
    staleTime: 10000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

export function useCoinSignalsQuery(symbol?: string) {
  return useQuery({
    queryKey: ["coinSignals", symbol],
    queryFn: () => (symbol ? fetchSignalsBySymbol(symbol) : Promise.resolve([])),
    enabled: !!symbol,
    refetchInterval: 15000,
    staleTime: 10000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

export function usePortfolioQuery() {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: fetchPortfolio,
    refetchInterval: 12000,
    staleTime: 8000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

export function useForecastQuery() {
  return useQuery({
    queryKey: ["forecast"],
    queryFn: fetchForecast,
    refetchInterval: 12000,
    staleTime: 8000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

export function useStatusQuery() {
  return useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    refetchInterval: 10000,
    staleTime: 6000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

export function useLivePricesQuery() {
  return useQuery({
    queryKey: ["livePrices"],
    queryFn: fetchLivePrices,
    refetchInterval: 8000,
    staleTime: 5000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

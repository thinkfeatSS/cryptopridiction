"use client";

import { useQuery } from "@tanstack/react-query";
import {
  fetchKpi,
  fetchDailySummary,
  fetchSignals,
  fetchPortfolio,
  fetchForecast,
  fetchStatus,
} from "@/lib/api";

export function useKpiQuery() {
  return useQuery({
    queryKey: ["kpi"],
    queryFn: fetchKpi,
    refetchInterval: 10000,
  });
}

export function useDailySummaryQuery() {
  return useQuery({
    queryKey: ["dailySummary"],
    queryFn: fetchDailySummary,
    refetchInterval: 10000,
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
    refetchInterval: 10000,
  });
}

export function usePortfolioQuery() {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: fetchPortfolio,
    refetchInterval: 8000,
  });
}

export function useForecastQuery() {
  return useQuery({
    queryKey: ["forecast"],
    queryFn: fetchForecast,
    refetchInterval: 15000,
  });
}

export function useStatusQuery() {
  return useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    refetchInterval: 3000,
  });
}

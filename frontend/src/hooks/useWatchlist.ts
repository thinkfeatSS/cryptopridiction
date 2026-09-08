"use client";

import { useState, useEffect, useCallback } from "react";

const STORAGE_KEY = "quantedge_watchlist";

export function useWatchlist() {
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        setWatchlist(JSON.parse(stored));
      }
    } catch (e) {
      console.error("Failed to load watchlist from localStorage", e);
    } finally {
      setIsLoaded(true);
    }
  }, []);

  const toggleWatchlist = useCallback((symbol: string) => {
    setWatchlist((prev) => {
      const sym = symbol.toUpperCase();
      const updated = prev.includes(sym) ? prev.filter((s) => s !== sym) : [...prev, sym];
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      } catch (e) {
        console.error("Failed to save watchlist to localStorage", e);
      }
      return updated;
    });
  }, []);

  const isStarred = useCallback(
    (symbol: string) => {
      return watchlist.includes(symbol.toUpperCase());
    },
    [watchlist]
  );

  return {
    watchlist,
    toggleWatchlist,
    isStarred,
    isLoaded,
  };
}

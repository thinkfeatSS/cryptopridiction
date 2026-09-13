"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

export interface WebSocketStreamState {
  isConnected: boolean;
  lastMessageTime: number | null;
  connectionStatus: "connected" | "connecting" | "disconnected" | "fallback";
}

export function useWebSocketStream() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<WebSocketStreamState>({
    isConnected: false,
    lastMessageTime: null,
    connectionStatus: "connecting",
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);

  const getWebSocketUrl = useCallback(() => {
    if (typeof window === "undefined") return "";
    const isHttps = window.location.protocol === "https:";
    const host = window.location.host;
    
    // In local dev without proxy, default to backend port 8005 or 8000
    if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
      return `ws://127.0.0.1:8005/ws/live`;
    }
    
    return `${isHttps ? "wss:" : "ws:"}//${host}/ws/live`;
  }, []);

  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const msg = JSON.parse(event.data);
      setStatus((prev) => ({ ...prev, lastMessageTime: Date.now() }));

      if (msg.type === "ping") {
        wsRef.current?.send("pong");
        return;
      }

      if (msg.type === "asset_update" && msg.data) {
        const updatedAsset = msg.data;
        queryClient.setQueryData(["forecast"], (oldData: any) => {
          if (!oldData) return oldData;
          const currentList = Array.isArray(oldData.scanner_leaderboard)
            ? [...oldData.scanner_leaderboard]
            : [];
          const idx = currentList.findIndex((item) => item.symbol === updatedAsset.symbol);
          if (idx >= 0) {
            currentList[idx] = { ...currentList[idx], ...updatedAsset };
          } else {
            currentList.push(updatedAsset);
          }
          return {
            ...oldData,
            timestamp: updatedAsset.server_prediction_time || oldData.timestamp,
            scanner_leaderboard: currentList,
          };
        });
      } else if (msg.type === "batch_assets_update" && Array.isArray(msg.data)) {
        const batchMap = new Map(msg.data.map((item: any) => [item.symbol, item]));
        queryClient.setQueryData(["forecast"], (oldData: any) => {
          if (!oldData) return oldData;
          const currentList = Array.isArray(oldData.scanner_leaderboard)
            ? oldData.scanner_leaderboard.map((item: any) => batchMap.get(item.symbol) || item)
            : msg.data;
          return {
            ...oldData,
            scanner_leaderboard: currentList,
          };
        });
      } else if (msg.type === "shield_tick" && msg.data) {
        queryClient.setQueryData(["forecast"], (oldData: any) => {
          if (!oldData) return oldData;
          return {
            ...oldData,
            btc_market_shield: msg.data,
            timestamp: msg.timestamp || oldData.timestamp,
          };
        });
      } else if (msg.type === "signals_sync") {
        queryClient.setQueryData(["forecast"], (oldData: any) => {
          if (!oldData) return oldData;
          return {
            ...oldData,
            top_round_signals: msg.top_signals || oldData.top_round_signals,
            signals_by_horizon: msg.signals_by_horizon || oldData.signals_by_horizon,
            timestamp: msg.timestamp || oldData.timestamp,
          };
        });
      }
    } catch (e) {
      // Ignore parse errors on heartbeats
    }
  }, [queryClient]);

  const connect = useCallback(() => {
    if (!isMountedRef.current) return;
    const url = getWebSocketUrl();
    if (!url) return;

    try {
      if (wsRef.current) {
        wsRef.current.close();
      }

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMountedRef.current) return;
        reconnectAttemptRef.current = 0;
        setStatus({
          isConnected: true,
          lastMessageTime: Date.now(),
          connectionStatus: "connected",
        });
      };

      ws.onmessage = handleMessage;

      ws.onclose = () => {
        if (!isMountedRef.current) return;
        setStatus((prev) => ({
          ...prev,
          isConnected: false,
          connectionStatus: reconnectAttemptRef.current > 3 ? "fallback" : "connecting",
        }));

        // Exponential backoff reconnect: 1s, 2s, 4s, max 8s
        const backoff = Math.min(1000 * Math.pow(1.5, reconnectAttemptRef.current), 8000);
        reconnectAttemptRef.current += 1;
        reconnectTimeoutRef.current = setTimeout(connect, backoff);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch (e) {
      reconnectTimeoutRef.current = setTimeout(connect, 3000);
    }
  }, [getWebSocketUrl, handleMessage]);

  useEffect(() => {
    isMountedRef.current = true;
    connect();

    return () => {
      isMountedRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return status;
}

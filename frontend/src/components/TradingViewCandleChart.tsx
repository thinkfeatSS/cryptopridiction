"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  ColorType,
  LineStyle,
} from "lightweight-charts";
import { formatUsd } from "@/lib/utils";
import { BarChart3, Maximize2, RefreshCw } from "lucide-react";

interface TradingViewCandleChartProps {
  symbol: string;
  currentPrice: number;
  entryPrice?: number;
  tp1Price?: number;
  tp2Price?: number;
  tp3Price?: number;
  slPrice?: number;
  direction?: string;
}

export default function TradingViewCandleChart({
  symbol,
  currentPrice,
  entryPrice,
  tp1Price,
  tp2Price,
  tp3Price,
  slPrice,
  direction = "LONG",
}: TradingViewCandleChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [timeframe, setTimeframe] = useState<"15M" | "1H" | "1D">("15M");

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Clean up previous instance
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const container = chartContainerRef.current;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 320,
      layout: {
        background: { type: ColorType.Solid, color: "#090d16" },
        textColor: "#94a3b8",
        fontSize: 11,
        fontFamily: "monospace",
      },
      grid: {
        vertLines: { color: "rgba(30, 41, 59, 0.4)" },
        horzLines: { color: "rgba(30, 41, 59, 0.4)" },
      },
      crosshair: {
        vertLine: { color: "#38bdf8", width: 1, style: LineStyle.Dashed },
        horzLine: { color: "#38bdf8", width: 1, style: LineStyle.Dashed },
      },
      rightPriceScale: {
        borderColor: "rgba(51, 65, 85, 0.5)",
        scaleMargins: {
          top: 0.15,
          bottom: 0.15,
        },
      },
      timeScale: {
        borderColor: "rgba(51, 65, 85, 0.5)",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#f43f5e",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#f43f5e",
    });

    // Generate realistic multi-candle price action leading to currentPrice
    const base = currentPrice > 0 ? currentPrice : 100.0;
    const isBull = direction.toUpperCase().includes("LONG") || direction.toUpperCase().includes("BULL");
    const numCandles = 40;
    const candleData: CandlestickData[] = [];
    const nowSec = Math.floor(Date.now() / 1000);
    const step = timeframe === "15M" ? 900 : timeframe === "1H" ? 3600 : 86400;

    let p = isBull ? base * 0.96 : base * 1.04;
    for (let i = numCandles; i >= 1; i--) {
      const time = (nowSec - i * step) as any;
      const noise = (Math.random() - 0.48) * (base * 0.012);
      const open = p;
      const close = i === 1 ? base : p + noise + (isBull ? base * 0.001 : -base * 0.001);
      const high = Math.max(open, close) + Math.random() * (base * 0.006);
      const low = Math.min(open, close) - Math.random() * (base * 0.006);

      candleData.push({
        time,
        open,
        high,
        low,
        close,
      });
      p = close;
    }

    candleSeries.setData(candleData);

    // Overlay TP / SL / Entry price lines
    if (entryPrice && entryPrice > 0) {
      candleSeries.createPriceLine({
        price: entryPrice,
        color: "#38bdf8",
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: "🔵 ENTRY",
      });
    }

    if (tp1Price && tp1Price > 0) {
      candleSeries.createPriceLine({
        price: tp1Price,
        color: "#10b981",
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "🟢 TP1 (1:2 R:R)",
      });
    }

    if (tp2Price && tp2Price > 0 && tp2Price !== tp1Price) {
      candleSeries.createPriceLine({
        price: tp2Price,
        color: "#34d399",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: "🟢 TP2",
      });
    }

    if (slPrice && slPrice > 0) {
      candleSeries.createPriceLine({
        price: slPrice,
        color: "#f43f5e",
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "🔴 STOP-LOSS",
      });
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
      }
    };
  }, [symbol, currentPrice, entryPrice, tp1Price, tp2Price, slPrice, direction, timeframe]);

  return (
    <div className="rounded-xl bg-dark-950 border border-slate-800/80 p-3 overflow-hidden">
      {/* Chart Header Toolbar */}
      <div className="flex items-center justify-between border-b border-slate-800/60 pb-2.5 mb-2">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-cyan-400" />
          <span className="text-xs font-bold text-white font-mono">{symbol} Interactive Chart</span>
          <span className="rounded bg-cyan-950 px-2 py-0.5 text-[10px] font-bold text-cyan-400 border border-cyan-800">
            {direction}
          </span>
        </div>

        {/* Timeframe Selector */}
        <div className="flex items-center gap-1 rounded-lg bg-dark-900 p-0.5 border border-slate-800">
          {(["15M", "1H", "1D"] as const).map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`rounded px-2 py-0.5 text-[10px] font-bold transition-all ${
                timeframe === tf
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Lightweight Chart Container */}
      <div ref={chartContainerRef} className="w-full relative" />

      {/* Target Legend */}
      <div className="mt-2 flex flex-wrap items-center justify-between text-[10px] font-mono border-t border-slate-800/60 pt-2 px-1 text-slate-400">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-cyan-400" /> Entry: {formatUsd(entryPrice || currentPrice)}
          </span>
          <span className="flex items-center gap-1 text-emerald-400">
            <span className="h-2 w-2 rounded-full bg-emerald-400" /> TP1: {formatUsd(tp1Price)}
          </span>
          <span className="flex items-center gap-1 text-rose-400">
            <span className="h-2 w-2 rounded-full bg-rose-400" /> SL: {formatUsd(slPrice)}
          </span>
        </div>
        <span className="text-slate-500">TradingView Lightweight Engine</span>
      </div>
    </div>
  );
}

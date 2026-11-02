import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatUsd(price: number | string | null | undefined): string {
  if (price === null || price === undefined || price === "") return "$0.00";
  const num = typeof price === "string" ? parseFloat(price) : price;
  if (isNaN(num)) return "$0.00";
  if (num === 0) return "$0.00";

  const isNeg = num < 0;
  const abs = Math.abs(num);
  let res = "";

  if (abs >= 50.0) {
    res = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(abs);
  } else if (abs >= 0.1) {
    res = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    }).format(abs);
  } else if (abs >= 0.001) {
    res = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 6,
      maximumFractionDigits: 6,
    }).format(abs);
  } else {
    res = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 8,
      maximumFractionDigits: 10,
    }).format(abs);
  }

  return isNeg ? `-${res}` : res;
}

export function formatPercent(val: number | string | null | undefined): string {
  if (val === null || val === undefined || val === "") return "0.00%";
  const num = typeof val === "string" ? parseFloat(val.replace("%", "").replace("+", "")) : val;
  if (isNaN(num)) return "0.00%";
  const sign = num > 0 ? "+" : "";
  return `${sign}${num.toFixed(2)}%`;
}

export function formatTimeRemaining(seconds: number): string {
  if (seconds <= 0) return "00m 00s";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, "0")}m ${s.toString().padStart(2, "0")}s`;
}

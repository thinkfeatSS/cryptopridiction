"use client";

import React, { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export default class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("[QuantEdge Uncaught Error Caught by Boundary]:", error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: undefined });
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-xl border border-rose-500/40 bg-rose-950/20 p-4 text-center">
          <div className="flex flex-col items-center justify-center gap-2">
            <AlertTriangle className="h-6 w-6 text-rose-400" />
            <span className="text-xs font-bold text-rose-300">
              {this.props.fallbackTitle || "An unexpected error occurred in this widget"}
            </span>
            <button
              onClick={this.handleReset}
              className="mt-2 flex items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/20 px-3 py-1 text-xs text-rose-200 hover:bg-rose-500/30 transition-colors"
            >
              <RefreshCw className="h-3 w-3" /> Retry View
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

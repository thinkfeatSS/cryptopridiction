import type { Metadata } from "next";
import "./globals.css";
import Providers from "@/components/Providers";
import Navbar from "@/components/Navbar";

export const metadata: Metadata = {
  title: "QUANT EDGE V15.0 - Quantitative Crypto Terminal",
  description: "AI-powered quantitative cryptocurrency trading predictions, multi-horizon signal engine, and live win/loss audit tracking.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="bg-dark-950 text-slate-100 min-h-screen flex flex-col antialiased selection:bg-cyan-500/30 selection:text-cyan-300">
        <Providers>
          <Navbar />
          <main className="flex-1 w-full max-w-7xl mx-auto px-4 py-6 sm:px-6">
            {children}
          </main>
          <footer className="border-t border-slate-800/80 bg-dark-950 py-6 text-center text-xs text-slate-500">
            <p>
              QUANT EDGE AI V15.0 • Quantitative Multi-Horizon Trading Terminal • 24/7 Live Daemon
            </p>
          </footer>
        </Providers>
      </body>
    </html>
  );
}

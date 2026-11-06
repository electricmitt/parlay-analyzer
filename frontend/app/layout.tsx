import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { AppShell } from "@/components/shell/AppShell";
import { SlateProvider } from "@/lib/slate";
import "./globals.css";

export const metadata: Metadata = {
  title: "Courtside AI",
  description: "NBA player prop research. Model estimates, not guarantees.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen antialiased">
        <SlateProvider>
          <AppShell>{children}</AppShell>
        </SlateProvider>
      </body>
    </html>
  );
}

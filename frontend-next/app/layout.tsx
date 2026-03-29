import type { Metadata } from "next";

import { AppShellClient } from "@/components/app-shell-client";

import "./globals.css";

export const metadata: Metadata = {
  title: "Cerebro Diagnostico Pericial",
  description: "Frontend para entrada, processamento, consultas e resultados periciais.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <AppShellClient>{children}</AppShellClient>
      </body>
    </html>
  );
}

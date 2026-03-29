import type { Route } from "next";
import Link from "next/link";
import { ClipboardCheck, FileSearch, FolderInput, Gauge, Layers, ScanEye, SquareChartGantt } from "lucide-react";

import { cn } from "@/lib/utils";

type NavItem = {
  href: Route;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const links: NavItem[] = [
  { href: "/", label: "Painel", icon: Gauge },
  { href: "/ingestao", label: "Entradas", icon: FolderInput },
  { href: "/processamento", label: "Processamento", icon: Layers },
  { href: "/analise-img", label: "Analise IMG", icon: ScanEye },
  { href: "/consultas", label: "Consultas", icon: FileSearch },
  { href: "/pericias", label: "Pericias", icon: ClipboardCheck },
  { href: "/resultados", label: "Resultados", icon: SquareChartGantt },
];

export function AppShell({
  pathname,
  children,
}: {
  pathname: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-4 py-6 md:grid-cols-[260px_1fr]">
        <aside className="rounded-xl border bg-card p-4">
          <p className="mb-1 text-xs uppercase tracking-[0.2em] text-muted-foreground">Analise Pericial</p>
          <h1 className="mb-6 text-xl font-semibold">Cerebro Diagnostico</h1>
          <nav className="space-y-2">
            {links.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                    active
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>

        <main>{children}</main>
      </div>
    </div>
  );
}

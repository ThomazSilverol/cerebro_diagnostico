"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type AnaliseStatus = {
  running: boolean;
  pid: number | null;
  pastas: {
    entrada: number;
    processadas: number;
    erros: number;
  };
  metricas: {
    totalLaudos: number;
    laudosAbertos: number;
    imagensAnalisadas: number;
  };
  laudos: Array<{
    id: number;
    nome: string;
    status: string;
    dataEdicao: string;
    imagens: number;
  }>;
  logTail: string;
  meta: {
    status: "idle" | "running" | "stopped";
    lastStartAt: string | null;
    lastStopAt: string | null;
    lastMessage: string | null;
  };
};

type UploadItem = {
  nomeOriginal: string;
  nomeSalvo: string;
  destinoAbsoluto: string;
};

function fmtDate(value: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString("pt-BR");
}

function badgeStatus(ativo: boolean) {
  if (ativo) return <Badge variant="warning">Em execucao</Badge>;
  return <Badge variant="outline">Parado</Badge>;
}

export function AnaliseImgPanel() {
  const [status, setStatus] = useState<AnaliseStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState<null | "start" | "stop" | "upload">(null);
  const [error, setError] = useState<string>("");
  const [message, setMessage] = useState<string>("");
  const [uploads, setUploads] = useState<UploadItem[]>([]);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/analise-img", { cache: "no-store" });
      if (!res.ok) {
        const payload = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(payload.message ?? "Falha ao carregar status.");
      }
      const payload = (await res.json()) as AnaliseStatus;
      setStatus(payload);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao carregar status.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
    const id = window.setInterval(() => {
      void fetchStatus();
    }, 10000);
    return () => window.clearInterval(id);
  }, [fetchStatus]);

  async function executarAcao(action: "start" | "stop") {
    setActionBusy(action);
    setMessage("");
    setError("");
    try {
      const res = await fetch("/api/analise-img", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const payload = (await res.json().catch(() => ({}))) as {
        message?: string;
        status?: AnaliseStatus;
      };
      if (!res.ok) throw new Error(payload.message ?? "Falha ao executar acao.");
      setMessage(payload.message ?? "Acao executada.");
      if (payload.status) setStatus(payload.status);
      await fetchStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao executar acao.");
    } finally {
      setActionBusy(null);
    }
  }

  async function uploadImagens(formData: FormData) {
    setActionBusy("upload");
    setMessage("");
    setError("");

    formData.append("categoria", "img_patologias_entrada");
    formData.append("destino", "pipeline");
    try {
      const res = await fetch("/api/uploads", {
        method: "POST",
        body: formData,
      });
      const payload = (await res.json().catch(() => ({}))) as {
        error?: string;
        itens?: UploadItem[];
      };
      if (!res.ok) throw new Error(payload.error ?? "Falha ao enviar imagens.");
      setUploads((prev) => [...(payload.itens ?? []), ...prev].slice(0, 8));
      setMessage(`${payload.itens?.length ?? 0} imagem(ns) enviada(s) para img_patologias_entrada.`);
      await fetchStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao enviar imagens.");
    } finally {
      setActionBusy(null);
    }
  }

  const statusAtual = useMemo(() => {
    if (!status) return "Carregando";
    if (status.running) return "Processamento em andamento";
    if (status.meta.status === "stopped") return "Ultima execucao encerrada";
    return "Aguardando execucao";
  }, [status]);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Controle de Analise Integrada de Imagens</CardTitle>
          <CardDescription>
            Fluxo: imagens em `img_patologias_entrada` → GUT + IBAPE + Banco + IA → laudos e movimentacao de pastas.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {badgeStatus(Boolean(status?.running))}
            <Badge variant="secondary">{statusAtual}</Badge>
            <Badge variant="outline">PID: {status?.pid ?? "—"}</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button disabled={Boolean(status?.running) || actionBusy !== null} onClick={() => void executarAcao("start")}>
              {actionBusy === "start" ? "Iniciando..." : "Executar analise_img"}
            </Button>
            <Button
              variant="destructive"
              disabled={!status?.running || actionBusy !== null}
              onClick={() => void executarAcao("stop")}
            >
              {actionBusy === "stop" ? "Parando..." : "Parar execucao"}
            </Button>
            <Button variant="outline" disabled={actionBusy !== null} onClick={() => void fetchStatus()}>
              Atualizar status
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Ultimo inicio: {fmtDate(status?.meta.lastStartAt ?? null)} | Ultima parada:{" "}
            {fmtDate(status?.meta.lastStopAt ?? null)}
          </p>
          {status?.meta.lastMessage ? <p className="text-xs text-muted-foreground">{status.meta.lastMessage}</p> : null}
          {message ? <p className="text-sm text-emerald-700">{message}</p> : null}
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Fila de entrada</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{status?.pastas.entrada ?? (loading ? "..." : 0)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Imagens processadas</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{status?.pastas.processadas ?? (loading ? "..." : 0)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Imagens com erro</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{status?.pastas.erros ?? (loading ? "..." : 0)}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Enviar imagens de patologia</CardTitle>
          <CardDescription>Upload direto para `img_patologias_entrada` com disparo posterior via botao executar.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            action={(fd) => {
              void uploadImagens(fd);
            }}
            className="space-y-3"
          >
            <Input name="arquivos" type="file" multiple accept="image/*" />
            <Button type="submit" disabled={actionBusy !== null}>
              {actionBusy === "upload" ? "Enviando..." : "Enviar para fila de imagens"}
            </Button>
          </form>
          {uploads.length > 0 ? (
            <div className="mt-4 space-y-2">
              {uploads.map((item) => (
                <div key={`${item.nomeSalvo}-${item.destinoAbsoluto}`} className="rounded-md border p-2 text-xs">
                  <p className="font-medium">{item.nomeOriginal}</p>
                  <p className="text-muted-foreground">{item.destinoAbsoluto}</p>
                </div>
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Laudos de imagem recentes</CardTitle>
          <CardDescription>
            Laudos totais: {status?.metricas.totalLaudos ?? 0} | Em aberto: {status?.metricas.laudosAbertos ?? 0} | Imagens
            analisadas: {status?.metricas.imagensAnalisadas ?? 0}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Laudo</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Imagens</TableHead>
                <TableHead>Ultima edicao</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(status?.laudos ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    Nenhum laudo de imagem encontrado ainda.
                  </TableCell>
                </TableRow>
              ) : (
                status?.laudos.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>{item.id}</TableCell>
                    <TableCell>{item.nome}</TableCell>
                    <TableCell>{item.status}</TableCell>
                    <TableCell>{item.imagens}</TableCell>
                    <TableCell>{fmtDate(item.dataEdicao)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Log da execucao</CardTitle>
          <CardDescription>Trecho final do `logs/analise_img_web.log` para acompanhamento.</CardDescription>
        </CardHeader>
        <CardContent>
          <pre className="max-h-80 overflow-auto rounded-md border bg-muted/30 p-3 text-xs leading-5">
            {status?.logTail?.trim() || "Sem logs no momento."}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}

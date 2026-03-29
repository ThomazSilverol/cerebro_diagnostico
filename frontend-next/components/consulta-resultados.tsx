"use client";

import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ConsultaResultado } from "@/lib/mock";

type FonteFiltro = "todas" | "normas" | "laudos" | "referencias";
type ConsultaModo = "evidencias" | "ia";
type SortKey = "titulo" | "fonte" | "tipo" | "confianca" | "score";
type SortDirection = "asc" | "desc";

type ConsultaResultadosProps = {
  resultados: ConsultaResultado[];
  query: string;
  fonte: string;
  modo: string;
};

function badgeTipo(tipo: ConsultaResultado["tipo"]) {
  if (tipo === "norma") return <Badge variant="secondary">Norma</Badge>;
  if (tipo === "laudo") return <Badge>Laudo</Badge>;
  return <Badge variant="outline">Referencia</Badge>;
}

function normalizarFonte(fonte: string): FonteFiltro {
  return ["todas", "normas", "laudos", "referencias"].includes(fonte) ? (fonte as FonteFiltro) : "todas";
}

function normalizarModo(modo: string): ConsultaModo {
  return modo === "ia" ? "ia" : "evidencias";
}

function comparar(a: ConsultaResultado, b: ConsultaResultado, key: SortKey, direction: SortDirection) {
  const factor = direction === "asc" ? 1 : -1;

  if (key === "score") return (a.score - b.score) * factor;
  if (key === "confianca") return (a.confianca - b.confianca) * factor;

  const left = String(a[key]).toLocaleLowerCase();
  const right = String(b[key]).toLocaleLowerCase();
  return left.localeCompare(right, "pt-BR") * factor;
}

export function ConsultaResultados({ resultados, query, fonte, modo }: ConsultaResultadosProps) {
  const fonteAtual = normalizarFonte(fonte);
  const modoAtual = normalizarModo(modo);

  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [selecionadoId, setSelecionadoId] = useState<number | null>(resultados[0]?.id ?? null);
  const [modalResultadoId, setModalResultadoId] = useState<number | null>(null);

  const resultadosOrdenados = useMemo(() => {
    return [...resultados].sort((a, b) => comparar(a, b, sortKey, sortDirection));
  }, [resultados, sortDirection, sortKey]);

  const totalResultados = resultados.length;
  const topScore = totalResultados > 0 ? Math.round(Math.max(...resultados.map((r) => r.score)) * 100) : 0;
  const confiancaMedia =
    totalResultados > 0
      ? Math.round((resultados.reduce((acc, item) => acc + item.confianca, 0) / totalResultados) * 100)
      : 0;
  const fontesDistintas = new Set(resultados.map((r) => r.fonte)).size;
  const selecionado = resultadosOrdenados.find((r) => r.id === selecionadoId) ?? resultadosOrdenados[0] ?? null;
  const resultadoModal = resultadosOrdenados.find((r) => r.id === modalResultadoId) ?? null;

  useEffect(() => {
    if (resultados.length === 0) {
      setSelecionadoId(null);
      setModalResultadoId(null);
      return;
    }

    setSelecionadoId((current) => {
      if (current == null) return resultados[0].id;
      return resultados.some((item) => item.id === current) ? current : resultados[0].id;
    });
  }, [resultados]);

  useEffect(() => {
    if (!resultadoModal) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setModalResultadoId(null);
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [resultadoModal]);

  function toggleSort(nextKey: SortKey) {
    if (sortKey === nextKey) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextKey);
    setSortDirection(nextKey === "score" || nextKey === "confianca" ? "desc" : "asc");
  }

  function labelSort(key: SortKey, titulo: string) {
    const ativo = sortKey === key;
    const sufixo = ativo ? (sortDirection === "asc" ? " ^" : " v") : "";
    return `${titulo}${sufixo}`;
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Consulta pericial com evidencias</CardTitle>
          <CardDescription>
            Pesquise termos tecnicos e visualize score, confianca, tipo e conteudo completo ao selecionar um resultado.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form method="GET" action="/consultas" className="grid gap-3 lg:grid-cols-[1fr_180px_180px_130px]">
            <Input name="q" defaultValue={query} placeholder="Ex: infiltracao fachada esquadria n=10" />
            <select
              name="modo"
              defaultValue={modoAtual}
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="evidencias">Modo: Evidencias</option>
              <option value="ia">Modo: Consulta IA</option>
            </select>
            <select
              name="fonte"
              defaultValue={fonteAtual}
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="todas">Todas as fontes</option>
              <option value="normas">Normas ABNT</option>
              <option value="laudos">Laudos judiciais</option>
              <option value="referencias">Referencias tecnicas</option>
            </select>
            <Button type="submit" className="gap-2">
              <Search className="h-4 w-4" />
              Consultar
            </Button>
          </form>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top score</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{topScore}%</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Resultados</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{totalResultados}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Confianca media</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{confiancaMedia}%</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Fontes distintas</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{fontesDistintas}</p>
          </CardContent>
        </Card>
      </div>

      {totalResultados === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Nenhum resultado encontrado</CardTitle>
            <CardDescription>
              Ajuste os termos da consulta ou selecione outra fonte para ampliar a busca.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <p>
              Termo atual: <strong>{query || "vazio"}</strong>
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Resultados da consulta</CardTitle>
            <CardDescription>
              Clique em um resultado para abrir o conteudo completo em modal. Colunas ordenaveis: titulo, fonte, tipo,
              confianca e score.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>
                    <button type="button" onClick={() => toggleSort("titulo")} className="font-medium hover:underline">
                      {labelSort("titulo", "Titulo e trecho")}
                    </button>
                  </TableHead>
                  <TableHead>
                    <button type="button" onClick={() => toggleSort("fonte")} className="font-medium hover:underline">
                      {labelSort("fonte", "Fonte")}
                    </button>
                  </TableHead>
                  <TableHead>
                    <button type="button" onClick={() => toggleSort("tipo")} className="font-medium hover:underline">
                      {labelSort("tipo", "Tipo")}
                    </button>
                  </TableHead>
                  <TableHead>
                    <button type="button" onClick={() => toggleSort("confianca")} className="font-medium hover:underline">
                      {labelSort("confianca", "Confianca")}
                    </button>
                  </TableHead>
                  <TableHead>
                    <button type="button" onClick={() => toggleSort("score")} className="font-medium hover:underline">
                      {labelSort("score", "Score")}
                    </button>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {resultadosOrdenados.map((item) => {
                  const ativo = item.id === selecionado?.id;
                  return (
                    <TableRow
                      key={item.id}
                      className={ativo ? "cursor-pointer bg-secondary/40" : "cursor-pointer"}
                      onClick={() => {
                        setSelecionadoId(item.id);
                        setModalResultadoId(item.id);
                      }}
                    >
                      <TableCell>
                        <p className="font-medium">{item.titulo}</p>
                        <p className="text-xs text-muted-foreground">{item.trecho}</p>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {item.evidencias.map((ev) => (
                            <Badge key={`${item.id}-${ev}`} variant="outline">
                              {ev}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>{item.fonte}</TableCell>
                      <TableCell>{badgeTipo(item.tipo)}</TableCell>
                      <TableCell>{Math.round(item.confianca * 100)}%</TableCell>
                      <TableCell>{Math.round(item.score * 100)}%</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {resultadoModal ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setModalResultadoId(null)}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-xl border bg-background shadow-lg"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b px-5 py-4">
              <div>
                <h3 className="text-base font-semibold">Visualizacao completa do resultado selecionado</h3>
                <p className="text-xs text-muted-foreground">
                  {resultadoModal.titulo} | {resultadoModal.fonte}
                </p>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={() => setModalResultadoId(null)}>
                Fechar
              </Button>
            </div>

            <div className="max-h-[calc(90vh-74px)] space-y-4 overflow-auto p-5">
              <div className="flex flex-wrap gap-2 text-xs">
                {badgeTipo(resultadoModal.tipo)}
                <Badge variant="outline">Confianca {Math.round(resultadoModal.confianca * 100)}%</Badge>
                <Badge variant="outline">Score {Math.round(resultadoModal.score * 100)}%</Badge>
              </div>
              <div className="flex flex-wrap gap-1">
                {resultadoModal.evidencias.map((ev) => (
                  <Badge key={`modal-${resultadoModal.id}-${ev}`} variant="outline">
                    {ev}
                  </Badge>
                ))}
              </div>
              <div className="rounded-lg border p-4">
                <p className="whitespace-pre-wrap break-words text-sm leading-6">
                  {resultadoModal.textoCompleto?.trim() || resultadoModal.trecho}
                </p>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

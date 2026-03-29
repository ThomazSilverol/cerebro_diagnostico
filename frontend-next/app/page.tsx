import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { indicadoresMock } from "@/lib/mock";

const cards = [
  {
    titulo: "Topicos indexados",
    valor: String(indicadoresMock.documentosNoBanco),
    detalhe: "Base textual para consultas, evidencias e correlacoes.",
  },
  {
    titulo: "Parametros extraidos",
    valor: String(indicadoresMock.parametrosExtraidos),
    detalhe: "Valores tecnicos capturados de normas e laudos.",
  },
  {
    titulo: "Analises IBAPE",
    valor: String(indicadoresMock.analisesIbape),
    detalhe: "Classificacoes tecnicas de anomalia/falha/risco.",
  },
  {
    titulo: "Pendencias de processamento",
    valor: String(indicadoresMock.pendenciasProcessamento),
    detalhe: "Itens aguardando refinamento ou classificacao final.",
  },
];

export default function HomePage() {
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border bg-card p-6">
        <p className="mb-2 text-xs uppercase tracking-[0.2em] text-muted-foreground">Operacao</p>
        <h2 className="mb-2 text-2xl font-semibold">Central de analise de documentos e pericias</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Painel para entrada de arquivos, acompanhamento do pipeline, consultas com evidencias e emissao
          de resultados tecnicos com rastreabilidade.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Badge variant="secondary">Ingestao</Badge>
          <Badge variant="secondary">Extracao</Badge>
          <Badge variant="secondary">Consulta hibrida</Badge>
          <Badge variant="secondary">GUT + IBAPE</Badge>
          <Badge variant="secondary">Resultados visuais</Badge>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((c) => (
          <Card key={c.titulo}>
            <CardHeader>
              <CardTitle className="text-base">{c.titulo}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-semibold">{c.valor}</p>
              <p className="mt-2 text-xs text-muted-foreground">{c.detalhe}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Atalhos de trabalho</CardTitle>
          <CardDescription>Fluxo recomendado para uso diario da aplicacao.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>1. Subir arquivos nas telas de entrada.</p>
          <p>2. Executar processamento e acompanhar fases.</p>
          <p>3. Rodar consultas por termo, norma ou patologia.</p>
          <p>4. Revisar pericias IBAPE/GUT e consolidar resultado.</p>
          <p className="pt-2">
            Ir para: <Link href="/ingestao" className="font-medium text-primary underline">Entradas de arquivos</Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

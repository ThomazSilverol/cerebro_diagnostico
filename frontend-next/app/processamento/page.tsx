import { AutoRefresh } from "@/components/auto-refresh";
import { PipelineVisual } from "@/components/pipeline-visual";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { obterSnapshotPipeline } from "@/lib/pipeline";

export const dynamic = "force-dynamic";

export default function ProcessamentoPage() {
  const snapshot = obterSnapshotPipeline();

  return (
    <div className="space-y-6">
      <AutoRefresh intervalMs={15000} />
      <PipelineVisual steps={snapshot.steps} />

      <Card>
        <CardHeader>
          <CardTitle>Controles de processamento</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>Este painel representa o fluxo real: extracao, enriquecimento IA, classificacao pericial e consolidacao.</p>
          <p>
            Atualizacao automatica a cada 15s. Laudos ativos: <strong>{snapshot.resumo.laudosAtivos}</strong> | Topicos:{" "}
            <strong>{snapshot.resumo.topicosTotal}</strong> | Pendentes Fase 2:{" "}
            <strong>{snapshot.resumo.pendentesFase2}</strong> | Entradas pendentes:{" "}
            <strong>{snapshot.resumo.entradasPendentes}</strong>
          </p>
          {snapshot.resumo.ultimaOperacao ? (
            <p className="text-muted-foreground">Ultima operacao registrada: {snapshot.resumo.ultimaOperacao}</p>
          ) : (
            <p className="text-muted-foreground">Sem operacoes registradas em `reprocessamento_log` ate o momento.</p>
          )}
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">offline_extractor</Badge>
            <Badge variant="secondary">ia_integrator</Badge>
            <Badge variant="secondary">quality_manager</Badge>
            <Badge variant="secondary">analise_ibape</Badge>
            <Badge variant="secondary">analise_imagem</Badge>
          </div>
          <p>Status baseado nos dados reais do banco e das pastas operacionais.</p>
        </CardContent>
      </Card>
    </div>
  );
}

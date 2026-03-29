import { AlertTriangle, CheckCircle2, LoaderCircle, PauseCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { type PipelineStep } from "@/lib/mock";

function iconFor(status: PipelineStep["status"]) {
  if (status === "concluido") return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
  if (status === "em_andamento") return <LoaderCircle className="h-4 w-4 animate-spin text-blue-600" />;
  if (status === "erro") return <AlertTriangle className="h-4 w-4 text-red-600" />;
  return <PauseCircle className="h-4 w-4 text-muted-foreground" />;
}

function badgeFor(status: PipelineStep["status"]) {
  if (status === "concluido") return <Badge variant="success">Concluido</Badge>;
  if (status === "em_andamento") return <Badge>Em andamento</Badge>;
  if (status === "erro") return <Badge variant="danger">Erro</Badge>;
  return <Badge variant="outline">Pendente</Badge>;
}

export function PipelineVisual({ steps }: { steps: PipelineStep[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Pipeline de processamento</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {steps.map((step) => (
          <div key={step.id} className="rounded-lg border p-4">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                {iconFor(step.status)}
                <p className="text-sm font-medium">{step.nome}</p>
              </div>
              {badgeFor(step.status)}
            </div>
            <Progress value={step.percentual} className="mb-2" />
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{step.detalhe}</span>
              <span>{step.percentual}%</span>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

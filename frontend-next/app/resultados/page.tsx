import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { resultadosMock } from "@/lib/mock";

export default function ResultadosPage() {
  const maxScore = Math.max(...resultadosMock.map((r) => r.score));

  const distribuicaoRisco = resultadosMock.reduce(
    (acc, item) => {
      acc[item.grauRisco] += 1;
      return acc;
    },
    { Critico: 0, Medio: 0, Minimo: 0 },
  );

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Resultado visual das consultas</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {resultadosMock.map((r) => {
            const width = Math.round((r.score / maxScore) * 100);
            return (
              <div key={r.id}>
                <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span>{r.titulo}</span>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">Confianca {Math.round(r.confianca * 100)}%</Badge>
                    <span>{Math.round(r.score * 100)}%</span>
                  </div>
                </div>
                <div className="h-3 rounded-full bg-secondary">
                  <div className="h-3 rounded-full bg-primary" style={{ width: `${width}%` }} />
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Distribuicao por grau de risco</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Critico</p>
            <p className="text-3xl font-semibold">{distribuicaoRisco.Critico}</p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Medio</p>
            <p className="text-3xl font-semibold">{distribuicaoRisco.Medio}</p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Minimo</p>
            <p className="text-3xl font-semibold">{distribuicaoRisco.Minimo}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

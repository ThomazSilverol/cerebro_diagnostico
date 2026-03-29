import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { periciasMock } from "@/lib/mock";

function badgeStatus(status: "aberta" | "em_revisao" | "finalizada") {
  if (status === "finalizada") return <Badge variant="success">Finalizada</Badge>;
  if (status === "em_revisao") return <Badge variant="warning">Em revisao</Badge>;
  return <Badge>Aberta</Badge>;
}

function badgeRisco(risco: "Critico" | "Medio" | "Minimo") {
  if (risco === "Critico") return <Badge variant="danger">Critico</Badge>;
  if (risco === "Medio") return <Badge variant="warning">Medio</Badge>;
  return <Badge variant="success">Minimo</Badge>;
}

export default function PericiasPage() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Painel de pericias (GUT + IBAPE)</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Acompanhe classificacoes tecnicas, prioridade GUT e status de revisao das pericias consolidadas.
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Analises recentes</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Codigo</TableHead>
                <TableHead>Item analisado</TableHead>
                <TableHead>Origem</TableHead>
                <TableHead>Risco</TableHead>
                <TableHead>Prioridade</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {periciasMock.map((item) => (
                <TableRow key={item.codigo}>
                  <TableCell>{item.codigo}</TableCell>
                  <TableCell>{item.item}</TableCell>
                  <TableCell>{item.origem}</TableCell>
                  <TableCell>{badgeRisco(item.grauRisco)}</TableCell>
                  <TableCell>{item.prioridade}</TableCell>
                  <TableCell>{badgeStatus(item.status)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

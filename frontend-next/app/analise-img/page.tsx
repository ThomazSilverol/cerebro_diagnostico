import { AnaliseImgPanel } from "@/components/analise-img-panel";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const dynamic = "force-dynamic";

export default function AnaliseImgPage() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>analise_img: Analise Integrada de Imagens</CardTitle>
          <CardDescription>
            Funcionalidade equivalente ao comando `analise_img` do backend, com foco em GUT + IBAPE + Banco + IA.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Use este painel para subir imagens de patologia, iniciar o processamento, acompanhar log e visualizar os laudos
          recentes gerados no banco `laudos_imagem.db`.
        </CardContent>
      </Card>

      <AnaliseImgPanel />
    </div>
  );
}

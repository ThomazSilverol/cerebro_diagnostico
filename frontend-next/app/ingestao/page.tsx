import { UploadPanel } from "@/components/upload-panel";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function IngestaoPage() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Entradas de arquivos para analise</CardTitle>
          <CardDescription>
            Defina a categoria correta para cada arquivo e envie para pasta operacional ou armazenamento provisorio.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>
            Pastas operacionais do pipeline:{" "}
            <code>doc_entrada</code>, <code>pdf_entrada</code>,{" "}
            <code>img_normas_entrada</code>, <code>img_patologias_entrada</code>.
          </p>
          <p>
            Opcao provisoria recomendada para triagem inicial:{" "}
            <code>frontend-next/storage/tmp</code>.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Badge variant="outline">DOCX/TXT para doc_entrada</Badge>
            <Badge variant="outline">PDF para pdf_entrada</Badge>
            <Badge variant="outline">Imagem norma para img_normas_entrada</Badge>
            <Badge variant="outline">Imagem patologia para img_patologias_entrada</Badge>
          </div>
        </CardContent>
      </Card>

      <UploadPanel />
    </div>
  );
}

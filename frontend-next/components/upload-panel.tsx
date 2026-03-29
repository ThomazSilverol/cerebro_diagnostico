"use client";

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type UploadCategoria = "doc_entrada" | "pdf_entrada" | "img_normas_entrada" | "img_patologias_entrada";
type UploadDestino = "provisorio" | "pipeline";

type UploadResult = {
  nomeOriginal: string;
  nomeSalvo: string;
  categoria: UploadCategoria;
  destinoTipo: UploadDestino;
  destinoAbsoluto: string;
  tamanhoBytes: number;
};

const categoriaInfo: Record<
  UploadCategoria,
  { titulo: string; accept: string; pastaPipeline: string }
> = {
  doc_entrada: {
    titulo: "Laudos DOC/DOCX/TXT",
    accept: ".doc,.docx,.txt",
    pastaPipeline: "doc_entrada",
  },
  pdf_entrada: {
    titulo: "PDFs tecnicos e normas",
    accept: ".pdf",
    pastaPipeline: "pdf_entrada",
  },
  img_normas_entrada: {
    titulo: "Imagens de normas",
    accept: "image/*",
    pastaPipeline: "img_normas_entrada",
  },
  img_patologias_entrada: {
    titulo: "Imagens de patologias",
    accept: "image/*",
    pastaPipeline: "img_patologias_entrada",
  },
};

export function UploadPanel() {
  const [categoria, setCategoria] = useState<UploadCategoria>("pdf_entrada");
  const [destino, setDestino] = useState<UploadDestino>("pipeline");
  const [isSending, setIsSending] = useState(false);
  const [items, setItems] = useState<UploadResult[]>([]);
  const [erro, setErro] = useState("");

  const alvoDescricao = useMemo(() => {
    if (destino === "pipeline") {
      return `Pasta operacional: ${categoriaInfo[categoria].pastaPipeline}`;
    }
    return `Pasta provisoria: frontend-next/storage/tmp/${categoria}`;
  }, [categoria, destino]);

  async function onSubmit(formData: FormData) {
    setErro("");
    setIsSending(true);
    try {
      const response = await fetch("/api/uploads", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.error ?? "Falha no upload.");
      }

      const payload = (await response.json()) as { itens: UploadResult[] };
      setItems((prev) => [...payload.itens, ...prev]);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro inesperado no upload.");
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>Entrada de arquivos do sistema pericial</CardTitle>
          <CardDescription>
            Selecione a categoria correta para alimentar o pipeline de extracao e analise.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            action={(fd) => {
              fd.append("categoria", categoria);
              fd.append("destino", destino);
              void onSubmit(fd);
            }}
            className="space-y-4"
          >
            <div>
              <p className="mb-2 text-sm font-medium">Categoria de entrada</p>
              <div className="grid gap-2 md:grid-cols-2">
                {(Object.keys(categoriaInfo) as UploadCategoria[]).map((cat) => (
                  <Button
                    key={cat}
                    type="button"
                    variant={categoria === cat ? "default" : "outline"}
                    className="justify-start"
                    onClick={() => setCategoria(cat)}
                  >
                    {categoriaInfo[cat].titulo}
                  </Button>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2 text-sm font-medium">Destino dos arquivos</p>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant={destino === "pipeline" ? "default" : "outline"}
                  onClick={() => setDestino("pipeline")}
                >
                  Operacional (pastas *_entrada)
                </Button>
                <Button
                  type="button"
                  variant={destino === "provisorio" ? "default" : "outline"}
                  onClick={() => setDestino("provisorio")}
                >
                  Provisorio (storage/tmp)
                </Button>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">{alvoDescricao}</p>
            </div>

            <div className="rounded-lg border border-dashed p-4">
              <label className="mb-2 block text-sm font-medium">Arquivos</label>
              <Input name="arquivos" type="file" multiple accept={categoriaInfo[categoria].accept} />
            </div>

            {erro ? <p className="text-sm text-red-600">{erro}</p> : null}

            <Button type="submit" disabled={isSending}>
              {isSending ? "Enviando..." : "Enviar para fila de entrada"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ultimos envios</CardTitle>
          <CardDescription>Validacao de entrada antes do processamento.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nenhum envio realizado nesta sessao.</p>
          ) : (
            items.map((item) => (
              <div key={`${item.nomeSalvo}-${item.categoria}`} className="rounded-lg border p-3">
                <div className="mb-1 flex items-center justify-between gap-3">
                  <p className="truncate text-sm font-medium">{item.nomeOriginal}</p>
                  <Badge variant={item.destinoTipo === "pipeline" ? "success" : "secondary"}>
                    {item.destinoTipo}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">Categoria: {item.categoria}</p>
                <p className="text-xs text-muted-foreground">{item.destinoAbsoluto}</p>
                <p className="text-xs text-muted-foreground">{Math.round(item.tamanhoBytes / 1024)} KB</p>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}

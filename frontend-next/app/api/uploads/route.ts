import { NextResponse } from "next/server";

import { salvarUpload, type UploadCategoria, type UploadDestino } from "@/lib/storage";

const CATEGORIAS = new Set<UploadCategoria>([
  "doc_entrada",
  "pdf_entrada",
  "img_normas_entrada",
  "img_patologias_entrada",
]);

const DESTINOS = new Set<UploadDestino>(["provisorio", "pipeline"]);

export async function POST(req: Request) {
  try {
    const formData = await req.formData();
    const categoriaRaw = String(formData.get("categoria") ?? "pdf_entrada");
    const destinoRaw = String(formData.get("destino") ?? "provisorio");

    const categoria = CATEGORIAS.has(categoriaRaw as UploadCategoria)
      ? (categoriaRaw as UploadCategoria)
      : null;

    const destino = DESTINOS.has(destinoRaw as UploadDestino)
      ? (destinoRaw as UploadDestino)
      : null;

    if (!categoria) {
      return NextResponse.json({ error: "Categoria invalida." }, { status: 400 });
    }

    if (!destino) {
      return NextResponse.json({ error: "Destino invalido." }, { status: 400 });
    }

    const arquivos = formData
      .getAll("arquivos")
      .filter((item): item is File => item instanceof File && item.size > 0);

    if (arquivos.length === 0) {
      return NextResponse.json({ error: "Nenhum arquivo informado." }, { status: 400 });
    }

    const itens = [];
    for (const arquivo of arquivos) {
      const salvo = await salvarUpload(arquivo, categoria, destino);
      itens.push(salvo);
    }

    return NextResponse.json({ itens }, { status: 201 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Falha inesperada no upload." },
      { status: 500 },
    );
  }
}

import fs from "node:fs/promises";
import path from "node:path";

const BASE_PROVISORIO = path.join(process.cwd(), "storage", "tmp");

const PASTAS_PIPELINE = {
  doc_entrada: "doc_entrada",
  pdf_entrada: "pdf_entrada",
  img_normas_entrada: "img_normas_entrada",
  img_patologias_entrada: "img_patologias_entrada",
} as const;

export type UploadCategoria = keyof typeof PASTAS_PIPELINE;
export type UploadDestino = "provisorio" | "pipeline";

function sanitizeFileName(name: string) {
  return name.replace(/[^a-zA-Z0-9._-]/g, "_");
}

function resolverPastaDestino(categoria: UploadCategoria, destino: UploadDestino) {
  if (destino === "pipeline") {
    const raizProjeto = path.resolve(process.cwd(), "..");
    return path.join(raizProjeto, PASTAS_PIPELINE[categoria]);
  }
  return path.join(BASE_PROVISORIO, categoria);
}

export async function salvarUpload(
  file: File,
  categoria: UploadCategoria,
  destino: UploadDestino,
) {
  const bytes = await file.arrayBuffer();
  const buffer = Buffer.from(bytes);

  const pasta = resolverPastaDestino(categoria, destino);
  await fs.mkdir(pasta, { recursive: true });

  const nome = `${Date.now()}_${sanitizeFileName(file.name)}`;
  const caminhoFinal = path.join(pasta, nome);
  await fs.writeFile(caminhoFinal, buffer);

  return {
    nomeOriginal: file.name,
    nomeSalvo: nome,
    categoria,
    destinoTipo: destino,
    destinoAbsoluto: caminhoFinal,
    tamanhoBytes: buffer.byteLength,
  };
}

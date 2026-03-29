import path from "node:path";
import { DatabaseSync } from "node:sqlite";

import type { ConsultaResultado } from "@/lib/mock";

type FonteFiltro = "todas" | "normas" | "laudos" | "referencias";

type BuscarParams = {
  q?: string;
  fonte?: FonteFiltro;
  limite?: number;
};

type Row = {
  id: number;
  titulo_topico: string;
  texto_original: string;
  palavras_chave: string;
  nome_arquivo: string;
  tipo_fonte: string;
  grau_risco: string | null;
  ia_score_confianca: number | null;
};

function dbPath() {
  return path.resolve(process.cwd(), "..", "banco_pericial.db");
}

function normalizeText(value: string): string {
  return (value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function parseTokens(q: string): string[] {
  return normalizeText(q)
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t.length >= 2)
    .slice(0, 8);
}

function mapTipoFonte(tipoFonte: string): ConsultaResultado["tipo"] {
  if (["norma_abnt", "norma_iso", "norma_outro"].includes(tipoFonte)) return "norma";
  if (["laudo_judicial", "parecer_tecnico"].includes(tipoFonte)) return "laudo";
  return "referencia";
}

function mapGrauRisco(grau: string | null, scoreBruto: number): ConsultaResultado["grauRisco"] {
  const g = (grau ?? "").toLowerCase();
  if (g.includes("crit")) return "Critico";
  if (g.includes("med")) return "Medio";
  if (g.includes("min")) return "Minimo";
  if (scoreBruto >= 30) return "Critico";
  if (scoreBruto >= 16) return "Medio";
  return "Minimo";
}

function extrairTrecho(texto: string, termos: string[]): string {
  const clean = (texto ?? "").replace(/\s+/g, " ").trim();
  if (!clean) return "Sem trecho disponivel.";

  const idx = termos
    .map((t) => clean.toLowerCase().indexOf(t.toLowerCase()))
    .filter((n) => n >= 0)
    .sort((a, b) => a - b)[0];

  if (idx === undefined) return clean.slice(0, 220);

  const start = Math.max(0, idx - 60);
  const end = Math.min(clean.length, idx + 160);
  return clean.slice(start, end);
}

function scoreRow(row: Row, termos: string[]): number {
  const titulo = normalizeText(row.titulo_topico ?? "");
  const texto = normalizeText(row.texto_original ?? "");
  const palavras = normalizeText(row.palavras_chave ?? "");
  const arquivo = normalizeText(row.nome_arquivo ?? "");

  let score = 0;
  for (const termo of termos) {
    score += (titulo.match(new RegExp(termo, "g")) ?? []).length * 6;
    score += (palavras.match(new RegExp(termo, "g")) ?? []).length * 4;
    score += (texto.match(new RegExp(termo, "g")) ?? []).length * 1;
    score += (arquivo.match(new RegExp(termo, "g")) ?? []).length * 2;
  }

  if (["norma_abnt", "norma_iso"].includes(row.tipo_fonte)) score += 5;
  if (["laudo_judicial", "parecer_tecnico"].includes(row.tipo_fonte)) score += 3;

  return score;
}

function fonteClause(fonte: FonteFiltro): { sql: string; params: string[] } {
  if (fonte === "normas") {
    return { sql: " AND l.tipo_fonte IN ('norma_abnt','norma_iso','norma_outro') ", params: [] };
  }
  if (fonte === "laudos") {
    return { sql: " AND l.tipo_fonte IN ('laudo_judicial','parecer_tecnico') ", params: [] };
  }
  if (fonte === "referencias") {
    return {
      sql: " AND l.tipo_fonte NOT IN ('norma_abnt','norma_iso','norma_outro','laudo_judicial','parecer_tecnico') ",
      params: [],
    };
  }
  return { sql: "", params: [] };
}

export function buscarConsultas({ q = "", fonte = "todas", limite = 30 }: BuscarParams): ConsultaResultado[] {
  const db = new DatabaseSync(dbPath());
  try {
    const termos = parseTokens(q);

    let sql = `
      SELECT
        t.id,
        COALESCE(t.titulo_topico, '') AS titulo_topico,
        COALESCE(t.texto_original, '') AS texto_original,
        COALESCE(t.palavras_chave, '') AS palavras_chave,
        COALESCE(l.nome_arquivo, '') AS nome_arquivo,
        COALESCE(l.tipo_fonte, '') AS tipo_fonte,
        COALESCE(t.grau_risco, '') AS grau_risco,
        COALESCE(t.ia_score_confianca, 0) AS ia_score_confianca
      FROM topicos t
      JOIN laudos l ON l.id = t.laudo_id
      WHERE l.status = 'ativo'
    `;

    const fonteSql = fonteClause(fonte);
    sql += fonteSql.sql;
    const fetchLimit = termos.length > 0 ? Math.max(300, Math.min(5000, limite * 120)) : Math.max(1, Math.min(100, limite * 4));
    sql += ` ORDER BY t.id DESC LIMIT ${fetchLimit}`;

    const rows = db.prepare(sql).all() as Row[];

    const scored = rows.map((row) => ({ row, scoreBruto: scoreRow(row, termos) }));
    const filtered = termos.length > 0 ? scored.filter((item) => item.scoreBruto > 0) : scored;

    filtered.sort((a, b) => b.scoreBruto - a.scoreBruto);

    const top = filtered.slice(0, limite);
    const maxScore = Math.max(1, ...top.map((x) => x.scoreBruto));

    return top.map(({ row, scoreBruto }) => {
      const confianca = Math.max(0.35, Math.min(0.99, Number(row.ia_score_confianca || 0) || scoreBruto / (maxScore * 1.1)));
      const score = Math.max(0.2, Math.min(0.99, scoreBruto / maxScore));
      const trecho = extrairTrecho(row.texto_original, termos);

      const evidencias = (
        row.palavras_chave
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
          .slice(0, 3)
      );

      if (evidencias.length === 0 && termos.length > 0) {
        evidencias.push(...termos.slice(0, 3));
      }

      return {
        id: row.id,
        titulo: row.titulo_topico || "Topico sem titulo",
        fonte: row.nome_arquivo || "Fonte desconhecida",
        score,
        grauRisco: mapGrauRisco(row.grau_risco, scoreBruto),
        confianca,
        tipo: mapTipoFonte(row.tipo_fonte),
        evidencias: evidencias.length > 0 ? evidencias : ["sem palavras-chave"],
        trecho,
        textoCompleto: (row.texto_original ?? "").trim() || trecho,
      } satisfies ConsultaResultado;
    });
  } finally {
    db.close();
  }
}

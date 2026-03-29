import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

import type { PipelineStep } from "@/lib/mock";

type PipelineResumo = {
  laudosAtivos: number;
  topicosTotal: number;
  pendentesFase2: number;
  entradasPendentes: number;
  ultimaOperacao: string | null;
};

export type PipelineSnapshot = {
  steps: PipelineStep[];
  resumo: PipelineResumo;
};

function dbPath() {
  return path.resolve(process.cwd(), "..", "banco_pericial.db");
}

function projetoRoot() {
  return path.resolve(process.cwd(), "..");
}

function toPercent(done: number, total: number, fallback = 0) {
  if (total <= 0) return fallback;
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
}

function countFilesRecursive(dir: string): number {
  if (!fs.existsSync(dir)) return 0;

  const entries = fs.readdirSync(dir, { withFileTypes: true });
  let total = 0;
  for (const entry of entries) {
    const current = path.join(dir, entry.name);
    if (entry.isDirectory()) total += countFilesRecursive(current);
    else if (entry.isFile()) total += 1;
  }
  return total;
}

function scalar(db: DatabaseSync, sql: string, ...params: (string | number)[]) {
  try {
    const row = db.prepare(sql).get(...params) as Record<string, number> | undefined;
    if (!row) return 0;
    const value = Object.values(row)[0];
    return typeof value === "number" ? value : Number(value ?? 0);
  } catch {
    return 0;
  }
}

function buildFileStats() {
  const raiz = projetoRoot();
  const entradas = [
    "doc_entrada",
    "pdf_entrada",
    "img_normas_entrada",
    "img_patologias_entrada",
  ].reduce((acc, dir) => acc + countFilesRecursive(path.join(raiz, dir)), 0);

  const processados = [
    "doc_processados",
    "pdf_processados",
    "img_normas_processadas",
    "img_patologias_processadas",
  ].reduce((acc, dir) => acc + countFilesRecursive(path.join(raiz, dir)), 0);

  return { entradas, processados };
}

export function obterSnapshotPipeline(): PipelineSnapshot {
  const fileStats = buildFileStats();
  const db = new DatabaseSync(dbPath());
  try {
    const laudosAtivos = scalar(db, "SELECT COUNT(*) FROM laudos WHERE status='ativo'");
    const laudosComTopicos = scalar(db, "SELECT COUNT(DISTINCT laudo_id) FROM topicos");
    const topicosTotal = scalar(
      db,
      "SELECT COUNT(*) FROM topicos t JOIN laudos l ON l.id=t.laudo_id WHERE l.status='ativo'",
    );
    const topicosNaoIniciados = scalar(db, "SELECT COUNT(*) FROM topicos WHERE status_processamento='nao_iniciado'");

    const fase1Processados = scalar(db, "SELECT COUNT(*) FROM laudos_estruturado WHERE processado_fase1=1");
    const fase2Alvo = scalar(
      db,
      `
      SELECT COUNT(*) FROM laudos_estruturado
      WHERE processado_fase1=1
        AND upper(COALESCE(confianca_extracao,'')) IN ('BAIXA','MEDIA','FALLBACK')
      `,
    );
    const fase2Concluidos = scalar(
      db,
      `
      SELECT COUNT(*) FROM laudos_estruturado
      WHERE processado_fase1=1
        AND processado_fase2=1
        AND upper(COALESCE(confianca_extracao,'')) IN ('BAIXA','MEDIA','FALLBACK')
      `,
    );
    const fase2Pendentes = Math.max(0, fase2Alvo - fase2Concluidos);

    const fase3Elegiveis = scalar(
      db,
      `
      SELECT COUNT(*) FROM topicos
      WHERE texto_original IS NOT NULL
        AND length(trim(texto_original)) > 50
      `,
    );
    const fase3Concluidos = scalar(
      db,
      `
      SELECT COUNT(*) FROM topicos
      WHERE status_processamento IN ('fase_3_ia','completo')
        AND texto_original IS NOT NULL
        AND length(trim(texto_original)) > 50
      `,
    );
    const fase3Pendentes = Math.max(0, fase3Elegiveis - fase3Concluidos);

    const laudosComQuesitos = scalar(db, "SELECT COUNT(DISTINCT laudo_id) FROM quesitos_respondidos");

    const ultima = db
      .prepare("SELECT fase, status, mensagem FROM reprocessamento_log ORDER BY id DESC LIMIT 1")
      .get() as { fase: number; status: string; mensagem: string } | undefined;

    const totalArquivosFluxo = fileStats.entradas + fileStats.processados;
    const coletaPercentual = totalArquivosFluxo > 0 ? toPercent(fileStats.processados, totalArquivosFluxo, 0) : 0;
    const coletaStatus: PipelineStep["status"] =
      totalArquivosFluxo === 0 ? "pendente" : fileStats.entradas > 0 ? "em_andamento" : "concluido";
    const coletaDetalhe =
      fileStats.entradas > 0
        ? `${fileStats.entradas} arquivo(s) aguardando processamento nas pastas de entrada.`
        : "Sem pendencias nas pastas de entrada.";

    const extracaoLaudosPct = toPercent(laudosComTopicos, Math.max(laudosAtivos, 1), 0);
    const extracaoTopicosPct = topicosTotal > 0 ? toPercent(topicosTotal - topicosNaoIniciados, topicosTotal, 0) : 0;
    const extracaoPercentual = laudosAtivos > 0 ? Math.round(extracaoLaudosPct * 0.7 + extracaoTopicosPct * 0.3) : 0;
    const extracaoStatus: PipelineStep["status"] =
      laudosAtivos === 0 ? "pendente" : extracaoPercentual >= 100 ? "concluido" : "em_andamento";

    const enriquecimentoPercentual = fase2Alvo > 0 ? toPercent(fase2Concluidos, fase2Alvo, 0) : fase1Processados > 0 ? 100 : 0;
    const enriquecimentoStatus: PipelineStep["status"] =
      fase1Processados === 0 ? "pendente" : fase2Pendentes > 0 ? "em_andamento" : "concluido";

    const classificacaoPercentual = fase3Elegiveis > 0 ? toPercent(fase3Concluidos, fase3Elegiveis, 0) : 0;
    const classificacaoStatus: PipelineStep["status"] =
      fase3Elegiveis === 0
        ? "pendente"
        : fase3Pendentes === 0
          ? "concluido"
          : fase2Pendentes > 0 && fase3Concluidos === 0
            ? "pendente"
            : "em_andamento";

    const consolidacaoPercentual = laudosAtivos > 0 ? toPercent(laudosComQuesitos, laudosAtivos, 0) : 0;
    const consolidacaoStatus: PipelineStep["status"] =
      laudosAtivos === 0
        ? "pendente"
        : consolidacaoPercentual >= 100
          ? "concluido"
          : laudosComQuesitos > 0
            ? "em_andamento"
            : "pendente";

    const steps: PipelineStep[] = [
      {
        id: "coleta",
        nome: "Coleta de arquivos de entrada",
        status: coletaStatus,
        percentual: coletaPercentual,
        detalhe: coletaDetalhe,
      },
      {
        id: "extracao",
        nome: "Extracao offline e indexacao",
        status: extracaoStatus,
        percentual: extracaoPercentual,
        detalhe: `${topicosTotal} topico(s) ativos no banco. ${topicosNaoIniciados} ainda nao iniciado(s).`,
      },
      {
        id: "enriquecimento",
        nome: "Enriquecimento IA por fases",
        status: enriquecimentoStatus,
        percentual: enriquecimentoPercentual,
        detalhe:
          fase2Pendentes > 0
            ? `Fase 2 pendente para ${fase2Pendentes} topico(s) de baixa/media confianca.`
            : "Fase 2 concluida para os topicos elegiveis.",
      },
      {
        id: "classificacao",
        nome: "Classificacao GUT e IBAPE",
        status: classificacaoStatus,
        percentual: classificacaoPercentual,
        detalhe:
          fase3Pendentes > 0
            ? `${fase3Pendentes} topico(s) aguardando classificacao semantica final.`
            : "Classificacao concluida para topicos elegiveis.",
      },
      {
        id: "consolidacao",
        nome: "Consolidacao e exportacao de laudos",
        status: consolidacaoStatus,
        percentual: consolidacaoPercentual,
        detalhe:
          laudosComQuesitos > 0
            ? `${laudosComQuesitos} laudo(s) com quesitos consolidados.`
            : "Aguardando consolidacao dos laudos processados.",
      },
    ];

    return {
      steps,
      resumo: {
        laudosAtivos,
        topicosTotal,
        pendentesFase2: fase2Pendentes,
        entradasPendentes: fileStats.entradas,
        ultimaOperacao: ultima ? `Fase ${ultima.fase} - ${ultima.status}: ${ultima.mensagem || "sem mensagem"}` : null,
      },
    };
  } catch {
    return {
      steps: [
        {
          id: "coleta",
          nome: "Coleta de arquivos de entrada",
          status: "erro",
          percentual: 0,
          detalhe: "Falha ao ler status do banco.",
        },
      ],
      resumo: {
        laudosAtivos: 0,
        topicosTotal: 0,
        pendentesFase2: 0,
        entradasPendentes: 0,
        ultimaOperacao: null,
      },
    };
  } finally {
    db.close();
  }
}

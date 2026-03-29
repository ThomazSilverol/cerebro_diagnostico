import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import { NextResponse } from "next/server";

type ApiAction = "start" | "stop";

type MetaState = {
  status: "idle" | "running" | "stopped";
  lastStartAt: string | null;
  lastStopAt: string | null;
  lastMessage: string | null;
};

type LaudoRow = {
  id: number;
  nome_laudo: string;
  status: string;
  data_edicao: string;
  imagens: number;
};

const ROOT = path.resolve(process.cwd(), "..");
const LOGS_DIR = path.join(ROOT, "logs");
const PID_FILE = path.join(LOGS_DIR, "analise_img_web.pid");
const LOG_FILE = path.join(LOGS_DIR, "analise_img_web.log");
const META_FILE = path.join(LOGS_DIR, "analise_img_web.meta.json");
const RUNNER_FILE = path.join(ROOT, "scripts", "run_analise_img_web.py");
const DB_IMG_FILE = path.join(ROOT, "laudos_imagem.db");

const DIR_ENTRADA = path.join(ROOT, "img_patologias_entrada");
const DIR_PROCESSADAS = path.join(ROOT, "img_patologias_processadas");
const DIR_ERROS = path.join(ROOT, "img_patologias_erros");

const IMAGE_EXT = new Set([".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"]);

function nowIso() {
  return new Date().toISOString();
}

function readMeta(): MetaState {
  try {
    const raw = fs.readFileSync(META_FILE, "utf8");
    const json = JSON.parse(raw) as Partial<MetaState>;
    return {
      status: json.status === "running" || json.status === "stopped" ? json.status : "idle",
      lastStartAt: json.lastStartAt ?? null,
      lastStopAt: json.lastStopAt ?? null,
      lastMessage: json.lastMessage ?? null,
    };
  } catch {
    return { status: "idle", lastStartAt: null, lastStopAt: null, lastMessage: null };
  }
}

function writeMeta(meta: MetaState) {
  fs.mkdirSync(LOGS_DIR, { recursive: true });
  fs.writeFileSync(META_FILE, JSON.stringify(meta, null, 2), "utf8");
}

function readPid(): number | null {
  try {
    const value = fs.readFileSync(PID_FILE, "utf8").trim();
    const pid = Number(value);
    return Number.isFinite(pid) && pid > 0 ? pid : null;
  } catch {
    return null;
  }
}

function isPidRunning(pid: number | null) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function clearPidFile() {
  try {
    fs.unlinkSync(PID_FILE);
  } catch {}
}

function countImages(dir: string): number {
  if (!fs.existsSync(dir)) return 0;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  let total = 0;
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      total += countImages(full);
      continue;
    }
    if (!entry.isFile()) continue;
    const ext = path.extname(entry.name).toLowerCase();
    if (IMAGE_EXT.has(ext)) total += 1;
  }
  return total;
}

function readTail(filePath: string, maxBytes = 12000): string {
  try {
    if (!fs.existsSync(filePath)) return "";
    const stat = fs.statSync(filePath);
    if (stat.size <= 0) return "";
    const start = Math.max(0, stat.size - maxBytes);
    const fd = fs.openSync(filePath, "r");
    try {
      const length = stat.size - start;
      const buffer = Buffer.alloc(length);
      fs.readSync(fd, buffer, 0, length, start);
      return buffer.toString("utf8");
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    return "";
  }
}

function queryLaudos() {
  const fallback = {
    laudos: [] as Array<{ id: number; nome: string; status: string; dataEdicao: string; imagens: number }>,
    totalLaudos: 0,
    laudosAbertos: 0,
    totalImagensAnalisadas: 0,
  };

  if (!fs.existsSync(DB_IMG_FILE)) return fallback;

  const db = new DatabaseSync(DB_IMG_FILE);
  try {
    const laudos = db
      .prepare(
        `
        SELECT
          l.id,
          l.nome_laudo,
          COALESCE(l.status, 'aberto') AS status,
          COALESCE(l.data_edicao, l.data_criacao, '') AS data_edicao,
          COUNT(i.id) AS imagens
        FROM laudos_img l
        LEFT JOIN imagens_laudo_img i ON i.laudo_id = l.id
        GROUP BY l.id
        ORDER BY l.data_edicao DESC
        LIMIT 12
        `,
      )
      .all() as LaudoRow[];

    const totalLaudos = Number(
      (
        db.prepare("SELECT COUNT(*) AS total FROM laudos_img").get() as {
          total: number;
        } | undefined
      )?.total ?? 0,
    );
    const laudosAbertos = Number(
      (
        db.prepare("SELECT COUNT(*) AS total FROM laudos_img WHERE status='aberto'").get() as {
          total: number;
        } | undefined
      )?.total ?? 0,
    );
    const totalImagensAnalisadas = Number(
      (
        db.prepare("SELECT COUNT(*) AS total FROM imagens_laudo_img").get() as {
          total: number;
        } | undefined
      )?.total ?? 0,
    );

    return {
      laudos: laudos.map((item) => ({
        id: item.id,
        nome: item.nome_laudo,
        status: item.status,
        dataEdicao: item.data_edicao,
        imagens: Number(item.imagens ?? 0),
      })),
      totalLaudos,
      laudosAbertos,
      totalImagensAnalisadas,
    };
  } catch {
    return fallback;
  } finally {
    db.close();
  }
}

function ensureStateConsistency() {
  const pid = readPid();
  const running = isPidRunning(pid);
  const meta = readMeta();

  if (pid && !running) {
    clearPidFile();
    if (meta.status === "running") {
      writeMeta({
        ...meta,
        status: "stopped",
        lastStopAt: nowIso(),
        lastMessage: "Processo finalizado.",
      });
    }
  }
}

function getStatusPayload() {
  ensureStateConsistency();
  const pid = readPid();
  const running = isPidRunning(pid);
  const meta = readMeta();
  const laudos = queryLaudos();
  const entrada = countImages(DIR_ENTRADA);
  const processadas = countImages(DIR_PROCESSADAS);
  const erros = countImages(DIR_ERROS);

  return {
    running,
    pid,
    pastas: {
      entrada,
      processadas,
      erros,
    },
    metricas: {
      totalLaudos: laudos.totalLaudos,
      laudosAbertos: laudos.laudosAbertos,
      imagensAnalisadas: laudos.totalImagensAnalisadas,
    },
    laudos: laudos.laudos,
    logTail: readTail(LOG_FILE),
    meta,
  };
}

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json(getStatusPayload());
}

export async function POST(req: Request) {
  try {
    const body = (await req.json().catch(() => ({}))) as { action?: ApiAction };
    const action = body.action ?? "start";

    ensureStateConsistency();
    const currentPid = readPid();
    const running = isPidRunning(currentPid);

    if (action === "stop") {
      if (!running || !currentPid) {
        return NextResponse.json(
          { ok: false, message: "Nenhuma execucao em andamento." },
          { status: 409 },
        );
      }

      process.kill(currentPid);
      clearPidFile();

      const meta = readMeta();
      writeMeta({
        ...meta,
        status: "stopped",
        lastStopAt: nowIso(),
        lastMessage: "Processo interrompido pelo frontend.",
      });

      return NextResponse.json({
        ok: true,
        message: "Execucao interrompida.",
        status: getStatusPayload(),
      });
    }

    if (running) {
      return NextResponse.json(
        { ok: false, message: `Ja existe execucao em andamento (PID ${currentPid}).` },
        { status: 409 },
      );
    }

    if (!fs.existsSync(RUNNER_FILE)) {
      return NextResponse.json(
        { ok: false, message: "Runner Python nao encontrado para analise de imagens." },
        { status: 500 },
      );
    }

    fs.mkdirSync(LOGS_DIR, { recursive: true });
    const outFd = fs.openSync(LOG_FILE, "a");
    fs.appendFileSync(LOG_FILE, `\n[${new Date().toISOString()}] Iniciando analise integrada via frontend.\n`);

    const child = spawn("python", [RUNNER_FILE], {
      cwd: ROOT,
      detached: true,
      stdio: ["ignore", outFd, outFd],
      windowsHide: true,
    });

    fs.closeSync(outFd);

    if (!child.pid) {
      return NextResponse.json(
        { ok: false, message: "Falha ao iniciar processo de analise de imagens." },
        { status: 500 },
      );
    }

    child.unref();
    fs.writeFileSync(PID_FILE, String(child.pid), "utf8");

    const meta = readMeta();
    writeMeta({
      ...meta,
      status: "running",
      lastStartAt: nowIso(),
      lastMessage: `Processo iniciado pelo frontend (PID ${child.pid}).`,
    });

    return NextResponse.json({
      ok: true,
      message: "Analise integrada iniciada.",
      pid: child.pid,
      status: getStatusPayload(),
    });
  } catch (error) {
    return NextResponse.json(
      {
        ok: false,
        message: error instanceof Error ? error.message : "Falha inesperada ao controlar analise de imagens.",
      },
      { status: 500 },
    );
  }
}

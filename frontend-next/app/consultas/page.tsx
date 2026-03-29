import { ConsultaResultados } from "@/components/consulta-resultados";
import { buscarConsultas } from "@/lib/consultas";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;
type FonteFiltro = "todas" | "normas" | "laudos" | "referencias";

type ConsultasPageProps = {
  searchParams: SearchParams;
};

function getParam(value: string | string[] | undefined, fallback = ""): string {
  if (Array.isArray(value)) return value[0] ?? fallback;
  return value ?? fallback;
}

export const dynamic = "force-dynamic";

export default async function ConsultasPage({ searchParams }: ConsultasPageProps) {
  const params = await searchParams;
  const q = getParam(params.q).trim();
  const fonteRaw = getParam(params.fonte, "todas");
  const modo = getParam(params.modo, "evidencias");

  const fonte: FonteFiltro = ["todas", "normas", "laudos", "referencias"].includes(fonteRaw)
    ? (fonteRaw as FonteFiltro)
    : "todas";
  const resultados = buscarConsultas({ q, fonte, limite: 30 });

  return <ConsultaResultados resultados={resultados} query={q} fonte={fonte} modo={modo} />;
}

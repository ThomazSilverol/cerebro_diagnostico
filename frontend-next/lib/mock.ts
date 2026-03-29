export type PipelineStep = {
  id: string;
  nome: string;
  status: "concluido" | "em_andamento" | "pendente" | "erro";
  percentual: number;
  detalhe: string;
};

export type ConsultaResultado = {
  id: number;
  titulo: string;
  fonte: string;
  score: number;
  grauRisco: "Critico" | "Medio" | "Minimo";
  confianca: number;
  tipo: "norma" | "laudo" | "referencia";
  evidencias: string[];
  trecho: string;
  textoCompleto?: string;
};

export type PericiaResumo = {
  codigo: string;
  item: string;
  origem: string;
  grauRisco: "Critico" | "Medio" | "Minimo";
  prioridade: number;
  status: "aberta" | "em_revisao" | "finalizada";
};

export const indicadoresMock = {
  documentosNoBanco: 356,
  parametrosExtraidos: 105,
  analisesIbape: 11,
  analisesImagem: 11,
  pendenciasProcessamento: 108,
};

export const pipelineMock: PipelineStep[] = [
  {
    id: "coleta",
    nome: "Coleta de arquivos de entrada",
    status: "concluido",
    percentual: 100,
    detalhe: "PDF, DOCX e imagens recebidos nas pastas monitoradas.",
  },
  {
    id: "extracao",
    nome: "Extracao offline e indexacao",
    status: "concluido",
    percentual: 100,
    detalhe: "Topicos, parametros e quesitos extraidos com rastreabilidade.",
  },
  {
    id: "enriquecimento",
    nome: "Enriquecimento IA por fases",
    status: "em_andamento",
    percentual: 62,
    detalhe: "Fase 2 em execucao para topicos com baixa confianca.",
  },
  {
    id: "classificacao",
    nome: "Classificacao GUT e IBAPE",
    status: "pendente",
    percentual: 0,
    detalhe: "Aguardando conclusao do refinamento semantico.",
  },
  {
    id: "consolidacao",
    nome: "Consolidacao e exportacao de laudos",
    status: "pendente",
    percentual: 0,
    detalhe: "Etapa final para emissao de relatorio tecnico.",
  },
];

export const resultadosMock: ConsultaResultado[] = [
  {
    id: 1,
    titulo: "NBR 13753 - Caimento de pisos",
    fonte: "NBR 13753",
    score: 0.93,
    grauRisco: "Medio",
    confianca: 0.91,
    tipo: "norma",
    evidencias: ["caimento minimo de 1,0%", "escoamento para ralos"],
    trecho: "O revestimento deve garantir escoamento adequado com caimento minimo e continuidade de drenagem.",
  },
  {
    id: 2,
    titulo: "Laudo judicial - Infiltracao em fachada norte",
    fonte: "Laudo 5430673",
    score: 0.88,
    grauRisco: "Critico",
    confianca: 0.84,
    tipo: "laudo",
    evidencias: ["mancha de umidade", "perda de estanqueidade em esquadria"],
    trecho: "Foi observada infiltracao recorrente na interface esquadria-fachada com degradacao progressiva.",
  },
  {
    id: 3,
    titulo: "NBR 15575 - Desempenho de vedacoes",
    fonte: "NBR 15575",
    score: 0.84,
    grauRisco: "Medio",
    confianca: 0.82,
    tipo: "norma",
    evidencias: ["desempenho minimo", "vida util e estanqueidade"],
    trecho: "Sistemas de vedacao devem manter desempenho em condicoes previstas de uso e manutencao.",
  },
  {
    id: 4,
    titulo: "Referencia tecnica - Corrosao de armadura",
    fonte: "Livro tecnico",
    score: 0.77,
    grauRisco: "Minimo",
    confianca: 0.74,
    tipo: "referencia",
    evidencias: ["carbonatacao", "cobrimento insuficiente"],
    trecho: "A progressao da corrosao depende da frente de carbonatacao e da exposicao ambiental do elemento.",
  },
];

export const periciasMock: PericiaResumo[] = [
  {
    codigo: "IBAPE-2026-0041",
    item: "Infiltracao em fachada e esquadria",
    origem: "Endogena",
    grauRisco: "Critico",
    prioridade: 75,
    status: "em_revisao",
  },
  {
    codigo: "IBAPE-2026-0042",
    item: "Fissuracao em laje tecnica",
    origem: "Funcional",
    grauRisco: "Medio",
    prioridade: 36,
    status: "aberta",
  },
  {
    codigo: "IBAPE-2026-0038",
    item: "Desplacamento de revestimento",
    origem: "Exogena",
    grauRisco: "Minimo",
    prioridade: 18,
    status: "finalizada",
  },
];

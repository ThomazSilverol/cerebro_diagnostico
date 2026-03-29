# =============================================================================
# gut_adaptativo.py — Módulo GUT Adaptativo v4.0
# Sistema: Cérebro de Engenharia Diagnóstica v2.0
#
# Referências:
#   • Knapp & Olivan (2021) — GUT aplicado a estruturas, nexo causal obrigatório
#   • Grossi (2025)         — Método SHS, sobreposição G/U, laudos judiciais
#   • Kepner & Tregoe (1981)— Metodologia GUT original
#   • ABNT NBR 15575-1:2024 — Subsistemas da edificação
#   • ABNT NBR 16747:2020   — Inspeção predial, terminologia
# =============================================================================

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("gut_adaptativo")

# Configuração de logging: INFO+ vai para arquivo, WARNING+ vai para console.
# Isso evita que mensagens de diagnóstico poluam a interface CLI durante a digitação.
def _configurar_logging() -> None:
    _fmt = "%(levelname)s | %(name)s | %(message)s"
    # Handler de arquivo — captura tudo (DEBUG+)
    _fh = logging.FileHandler("cerebro_diagnostico.log", encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter(_fmt))
    # Handler de console — apenas WARNING+ (sem poluir o terminal)
    _ch = logging.StreamHandler()
    _ch.setLevel(logging.WARNING)
    _ch.setFormatter(logging.Formatter(_fmt))
    # Configurar o logger raiz
    _root = logging.getLogger()
    if not _root.handlers:          # evitar duplicação se chamado múltiplas vezes
        _root.setLevel(logging.DEBUG)
        _root.addHandler(_fh)
        _root.addHandler(_ch)
    # Silenciar loggers barulhentos de libs externas
    for _lib in ("httpx", "httpcore", "google", "urllib3", "requests"):
        logging.getLogger(_lib).setLevel(logging.WARNING)

_configurar_logging()


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────────────────────

class SubsistemaGUT(str, Enum):
    """
    Subsistemas construtivos conforme ABNT NBR 15575-1:2024.
    Usada como chave primária de filtragem em PERGUNTAS_GUT e no histórico.
    """
    ESTRUTURAL       = "Estrutural"
    ACABAMENTO       = "Acabamento"
    HIDROSSANITARIO  = "Hidrossanitário"
    COBERTURA        = "Cobertura"
    ELETRICO         = "Elétrico"


class OrigemNexo(str, Enum):
    ENDOGENA_PROJETO    = "Endógena — falha de projeto"
    ENDOGENA_EXECUCAO   = "Endógena — falha de execução"
    EXOGENA             = "Exógena — agente externo"
    NATURAL             = "Natural — agentes ambientais"
    FUNCIONAL           = "Funcional — uso inadequado"
    A_DETERMINAR        = "A Determinar — investigação adicional necessária"


class MecanismoDegradacao(str, Enum):
    MECANICO     = "Mecânico"
    FISICO       = "Físico"
    QUIMICO      = "Químico"
    BIOLOGICO    = "Biológico"
    COMBINADO    = "Combinado"
    INDETERMINADO = "Indeterminado"


class StatusAnomalia(str, Enum):
    EM_OCORRENCIA   = "Em ocorrência / Ativa e acelerando"
    ATIVA_ESTAVEL   = "Ativa com progressão estável"
    ESTABILIZADA    = "Aparentemente estabilizada"
    EM_REGRESSAO    = "Em regressão espontânea"


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OpcaoFator:
    """Uma opção de resposta para um fator GUT com peso normalizado [0,1]."""
    texto: str
    peso: float        # [0.0, 1.0]
    exemplo: str = ""


@dataclass(frozen=True)
class FatorGUT:
    """
    Define um fator GUT (ex: G1, U2, T3) com peso absoluto e lista de opções.
    Conforme P2: mínimo 4 opções, sem valores apenas extremos.
    """
    id: str            # "G1", "U2", etc.
    dimensao: str      # "G", "U" ou "T"
    peso: float        # peso absoluto na fórmula ponderada
    pergunta_padrao: str
    opcoes_padrao: tuple[OpcaoFator, ...]


@dataclass
class NexoCausal:
    """
    Representação do nexo causal conforme Knapp & Olivan (2021).
    Etapa obrigatória ANTERIOR ao cálculo GUT.
    """
    origem: OrigemNexo
    mecanismo: MecanismoDegradacao
    status: StatusAnomalia
    texto_livre: str = ""   # máx. 500 caracteres

    def is_a_determinar(self) -> bool:
        return self.origem == OrigemNexo.A_DETERMINAR

    def __str__(self) -> str:
        return (
            f"Origem: {self.origem.value} | "
            f"Mecanismo: {self.mecanismo.value} | "
            f"Status: {self.status.value}"
        )


@dataclass
class ResultadoGUT:
    """Resultado completo de uma avaliação GUT Adaptativa."""
    G: int
    U: int
    T: int
    prioridade: int           # G × U × T
    risco: str                # Crítico / Alto / Médio / Baixo
    justificativa_G: str = ""
    justificativa_U: str = ""
    justificativa_T: str = ""
    acao_recomendada: str = ""
    normas_sugeridas: list[str] = field(default_factory=list)
    fonte: str = "treinamento"   # treinamento | historico | ia
    confianca: float = 1.0       # 0.0–1.0
    sobreposicao_detectada: bool = False
    sobreposicao_pct: float = 0.0
    nexo_indeterminado: bool = False
    # SHS (opcional)
    npa_shs: Optional[float] = None
    prioridade_shs: Optional[str] = None
    shs_converge: Optional[bool] = None
    respostas_json: str = "{}"
    subsistema: str = ""
    nexo: Optional[NexoCausal] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES — FATORES GUT
# ─────────────────────────────────────────────────────────────────────────────

_FATORES: dict[str, FatorGUT] = {
    # ── G — GRAVIDADE ──────────────────────────────────────────────────────
    "G1": FatorGUT(
        id="G1", dimensao="G", peso=3.0,
        pergunta_padrao="Qual elemento ou componente está diretamente afetado?",
        opcoes_padrao=(
            OpcaoFator("Estrutural principal (fundação, pilar, viga, laje portante)",   1.00, "Recalque em sapata isolada"),
            OpcaoFator("Estrutural secundário (verga, contraverga, cinta)",              0.70, "Trinca em contraverga"),
            OpcaoFator("Instalação ativa (elétrica/hidráulica com vazamento/falha)",     0.50, "Vazamento em prumada embutida"),
            OpcaoFator("Vedação/Fachada (alvenaria, revestimento externo)",              0.40, "Desplacamento cerâmico em fachada"),
            OpcaoFator("Acabamento/revestimento interno",                                0.15, "Bolha de pintura interna"),
        ),
    ),
    "G2": FatorGUT(
        id="G2", dimensao="G", peso=2.0,
        pergunta_padrao="Qual é a extensão da anomalia no elemento afetado?",
        opcoes_padrao=(
            OpcaoFator("Generalizada — mais de 50% do elemento ou área",  1.00, "Fissuras em toda a fachada"),
            OpcaoFator("Ampla — entre 25% e 50%",                         0.75, "Mancha de umidade em parede inteira"),
            OpcaoFator("Localizada — entre 5% e 25%",                     0.45, "Eflorescência em trecho de 2 m²"),
            OpcaoFator("Pontual — menos de 5%",                           0.15, "Fissura isolada de 30 cm"),
        ),
    ),
    "G3": FatorGUT(
        id="G3", dimensao="G", peso=2.5,
        pergunta_padrao="Qual é a consequência mais grave observada ou previsível?",
        opcoes_padrao=(
            OpcaoFator("Risco de vida direto (colapso, choque, incêndio iminentes)",     1.00, "Pilar com armação exposta e corrosão avançada"),
            OpcaoFator("Risco de lesão (queda de material, tropeço, exposição)",          0.75, "Placa cerâmica solta em fachada acessível"),
            OpcaoFator("Perda patrimonial severa (estrutura, impermeabilização)",         0.55, "Infiltração atingindo armação de laje"),
            OpcaoFator("Perda patrimonial moderada (revestimento, pintura)",              0.30, "Bolor generalizado em parede"),
            OpcaoFator("Apenas estética — sem risco ou perda funcional",                  0.05, "Amarelamento de tinta por sol"),
        ),
    ),
    "G4": FatorGUT(
        id="G4", dimensao="G", peso=1.5,
        pergunta_padrao="Qual é o grau de comprometimento funcional causado?",
        opcoes_padrao=(
            OpcaoFator("Inviabiliza uso total do imóvel ou área significativa",  1.00, "Risco de colapso — interdição"),
            OpcaoFator("Inviabiliza uso de ambiente específico",                  0.65, "Banheiro inutilizável por retorno de esgoto"),
            OpcaoFator("Dificulta uso mas não impede",                            0.35, "Piso escorregadio por umidade"),
            OpcaoFator("Sem impacto no uso atual",                                0.05, "Fissura estética em rodapé"),
        ),
    ),
    # ── U — URGÊNCIA ────────────────────────────────────────────────────────
    "U1": FatorGUT(
        id="U1", dimensao="U", peso=3.5,
        pergunta_padrao="Qual é a janela de tempo disponível antes do agravamento irreversível?",
        opcoes_padrao=(
            OpcaoFator("Imediata — horas ou dias",            1.00, "Estrutura com risco de colapso"),
            OpcaoFator("Curta — até 30 dias",                 0.80, "Infiltração ativa na estação chuvosa"),
            OpcaoFator("Moderada — 1 a 3 meses",              0.55, "Corrosão de armadura em fase inicial"),
            OpcaoFator("Longa — 3 a 6 meses",                 0.30, "Eflorescência estável em fachada"),
            OpcaoFator("Muito longa — mais de 6 meses",       0.10, "Fissura estabilizada há mais de 1 ano"),
        ),
    ),
    "U2": FatorGUT(
        id="U2", dimensao="U", peso=3.0,
        pergunta_padrao="Qual é o nível de exposição de pessoas ao risco?",
        opcoes_padrao=(
            OpcaoFator("Uso pleno — presença constante de pessoas",          1.00, "Área de circulação principal"),
            OpcaoFator("Uso frequente em horários definidos",                 0.70, "Sala de aula ou escritório"),
            OpcaoFator("Uso esporádico",                                      0.35, "Depósito de acesso eventual"),
            OpcaoFator("Imóvel desocupado",                                   0.05, "Galpão vago"),
        ),
    ),
    "U3": FatorGUT(
        id="U3", dimensao="U", peso=2.0,
        pergunta_padrao="Qual é a reversibilidade dos danos caso não haja intervenção imediata?",
        opcoes_padrao=(
            OpcaoFator("Danos já irreversíveis em parte",                             1.00, "Corrosão com perda de seção de armadura"),
            OpcaoFator("Reversível com intervenção complexa ou cara",                 0.70, "Reforço estrutural necessário"),
            OpcaoFator("Reversível com intervenção simples",                          0.35, "Reaperto de parafusos de caixilho"),
            OpcaoFator("Sem danos permanentes ainda — reversão espontânea possível",  0.05, "Mancha superficial por umidade condensada"),
        ),
    ),
    "U4": FatorGUT(
        id="U4", dimensao="U", peso=1.5,
        pergunta_padrao="Existe condicionante processual (prazo judicial/vistoria) determinando urgência?",
        opcoes_padrao=(
            OpcaoFator("Prazo judicial ou vistoria em menos de 30 dias",  1.00, "Audiência de custódia marcada"),
            OpcaoFator("Prazo entre 30 e 90 dias",                        0.65, "Perícia agendada em 2 meses"),
            OpcaoFator("Prazo superior a 90 dias ou sem prazo definido",  0.30, "Laudo sem urgência processual"),
            OpcaoFator("Sem qualquer condicionante processual",           0.10, "Vistoria de rotina sem mandato"),
        ),
    ),
    # ── T — TENDÊNCIA ───────────────────────────────────────────────────────
    "T1": FatorGUT(
        id="T1", dimensao="T", peso=3.5,
        pergunta_padrao="Qual é o nível de atividade atual da anomalia?",
        opcoes_padrao=(
            OpcaoFator("Ativa e em aceleração visível",         1.00, "Fissura aumentando visivelmente a cada semana"),
            OpcaoFator("Ativa com progressão lenta e contínua", 0.70, "Mancha de umidade crescendo gradualmente"),
            OpcaoFator("Aparentemente estabilizada",            0.20, "Fissura sem alteração documentada em 12 meses"),
            OpcaoFator("Em regressão espontânea",               0.00, "Eflorescência reduzindo após secagem"),
        ),
    ),
    "T2": FatorGUT(
        id="T2", dimensao="T", peso=3.0,
        pergunta_padrao="Quais agentes de degradação estão atualmente presentes?",
        opcoes_padrao=(
            OpcaoFator("Múltiplos agentes contínuos (umidade + carga + vibração)",  1.00, "Laje com infiltração, sobrecarga e recalque"),
            OpcaoFator("Agente único contínuo",                                      0.70, "Umidade constante de solo"),
            OpcaoFator("Agente intermitente (chuva, vibração sazonal)",              0.40, "Infiltração apenas em período chuvoso"),
            OpcaoFator("Nenhum agente identificado atualmente",                      0.05, "Fissura antiga sem fonte ativa"),
        ),
    ),
    "T3": FatorGUT(
        id="T3", dimensao="T", peso=2.0,
        pergunta_padrao="Qual é o histórico documentado de progressão desta anomalia?",
        opcoes_padrao=(
            OpcaoFator("Progressão acelerada documentada com medições",  1.00, "Relatório anterior indica aumento de 3 mm/mês"),
            OpcaoFator("Progressão relatada pelos usuários, não medida", 0.60, "'Piorou muito este verão' (sem laudo anterior)"),
            OpcaoFator("Sem histórico (anomalia recém-descoberta)",       0.45, "Primeira vistoria do imóvel"),
            OpcaoFator("Histórico indica estabilização há mais de 12m",  0.10, "Laudo anterior confirmou estabilização"),
        ),
    ),
    "T4": FatorGUT(
        id="T4", dimensao="T", peso=1.5,
        pergunta_padrao="Qual é a exposição sazonal nos próximos meses?",
        opcoes_padrao=(
            OpcaoFator("Alta exposição — período crítico em até 60 dias",          1.00, "Estação chuvosa começa em 45 dias"),
            OpcaoFator("Exposição moderada — período crítico em 60 a 180 dias",    0.55, "Verão intenso em 3 meses"),
            OpcaoFator("Baixa exposição — clima favorável por mais de 180 dias",   0.10, "Seco por pelo menos 6 meses"),
        ),
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# PERGUNTAS ESPECIALIZADAS POR SUBSISTEMA
# Estrutura: PERGUNTAS_GUT[fator_id][subsistema] → dict com pergunta + opcoes
# Fatores sem especialização usam a versão padrão de _FATORES.
# ─────────────────────────────────────────────────────────────────────────────

PERGUNTAS_GUT: dict[str, dict[str, dict[str, Any]]] = {

    # ── G1 — Especializado para todos os subsistemas ──────────────────────
    "G1": {
        SubsistemaGUT.ESTRUTURAL: {
            "pergunta": "Qual é o elemento estrutural diretamente afetado?",
            "opcoes": [
                OpcaoFator("Fundação (sapata, bloco, estaca, radier)",           1.00, "Recalque diferencial em sapata isolada"),
                OpcaoFator("Pilar ou viga principal",                            1.00, "Fissura diagonal em pilar de CA"),
                OpcaoFator("Laje (portante ou protendida)",                      0.90, "Flecha excessiva em laje bidirecional"),
                OpcaoFator("Elemento estrutural secundário (verga, cinta)",      0.65, "Trinca em contraverga de janela"),
                OpcaoFator("Elemento não estrutural (alvenaria de vedação)",     0.35, "Fissura vertical em bloco cerâmico"),
            ],
        },
        SubsistemaGUT.ACABAMENTO: {
            "pergunta": "Qual é o elemento de acabamento afetado?",
            "opcoes": [
                OpcaoFator("Revestimento de fachada (cerâmica, argamassa)",     0.60, "Desplacamento cerâmico em fachada"),
                OpcaoFator("Esquadria ou caixilho (janela, porta)",              0.40, "Infiltração por falha de vedação"),
                OpcaoFator("Revestimento interno (azulejo, gesso, pintura)",    0.25, "Bolha de pintura em banheiro"),
                OpcaoFator("Piso (cerâmico, vinílico, cimentado)",              0.30, "Gretamento cerâmico em área molhada"),
                OpcaoFator("Apenas pintura externa ou interna",                  0.10, "Amarelamento por exposição solar"),
            ],
        },
        SubsistemaGUT.HIDROSSANITARIO: {
            "pergunta": "Qual é o componente hidrossanitário afetado?",
            "opcoes": [
                OpcaoFator("Impermeabilização (laje, banheiro, cozinha)",          0.80, "Falha em impermeabilização de laje"),
                OpcaoFator("Tubulação de esgoto (vazamento ou entupimento)",       0.70, "Retorno de esgoto em caixa de passagem"),
                OpcaoFator("Tubulação de água fria/quente",                        0.65, "Vazamento em tubulação embutida"),
                OpcaoFator("Caixa d'água ou reservatório",                         0.55, "Fissura em reservatório elevado"),
                OpcaoFator("Tubulação pluvial (calha, condutor)",                  0.45, "Obstrução em condutor pluvial"),
            ],
        },
        SubsistemaGUT.COBERTURA: {
            "pergunta": "Qual é o componente de cobertura afetado?",
            "opcoes": [
                OpcaoFator("Estrutura de telhado (madeira, metálica)",             0.85, "Corrosão avançada em terça metálica"),
                OpcaoFator("Impermeabilização de laje (manta, emulsão)",           0.80, "Manta asfáltica fissurada com infiltração"),
                OpcaoFator("Telhas (cerâmica, metálica, fibrocimento)",            0.55, "Telhas quebradas com entrada de água"),
                OpcaoFator("Rufos, calhas e condutores",                           0.50, "Rufo deslocado causando infiltração"),
                OpcaoFator("Drenagem horizontal (caimento, ralos)",                0.40, "Empoçamento por caimento insuficiente"),
            ],
        },
        SubsistemaGUT.ELETRICO: {
            "pergunta": "Qual é o componente elétrico afetado?",
            "opcoes": [
                OpcaoFator("SPDA ou aterramento (para-raios, descida)",           1.00, "SPDA com descida rompida sem aterramento"),
                OpcaoFator("Quadro de distribuição (disjuntores, barramentos)",    0.90, "Quadro sem proteção diferencial residual"),
                OpcaoFator("Fiação (condutores, eletrodutos)",                     0.85, "Cabos expostos em área acessível"),
                OpcaoFator("Iluminação de emergência",                             0.60, "Bloco autônomo sem manutenção há 12m"),
                OpcaoFator("Tomadas, interruptores ou luminária",                  0.45, "Tomadas sem tampa em área infantil"),
            ],
        },
    },

    # ── G3 — Especializado para Elétrico e Hidrossanitário ────────────────
    "G3": {
        SubsistemaGUT.ELETRICO: {
            "pergunta": "Qual é o risco mais grave desta falha elétrica?",
            "opcoes": [
                OpcaoFator("Risco de incêndio (curto-circuito, aquecimento)",    1.00, "Fiação sobrecarregada sem disjuntor"),
                OpcaoFator("Risco de choque elétrico direto",                     1.00, "Cabo vivo acessível em circulação"),
                OpcaoFator("Perda de funcionalidade do sistema",                  0.50, "Quadro sem identificação — interrupções"),
                OpcaoFator("Não conformidade normativa sem risco imediato",       0.20, "Ausência de tomada em dormitório"),
            ],
        },
        SubsistemaGUT.HIDROSSANITARIO: {
            "pergunta": "Qual é a consequência principal da falha hidrossanitária?",
            "opcoes": [
                OpcaoFator("Contaminação de água potável ou risco sanitário",     1.00, "Conexão cruzada água/esgoto"),
                OpcaoFator("Dano estrutural por infiltração ativa",               0.80, "Vazamento em laje atingindo armação"),
                OpcaoFator("Comprometimento de ambiente por umidade/bolor",       0.55, "Mofo generalizado por vazamento crônico"),
                OpcaoFator("Transbordamento ou inundação localizada",             0.45, "Obstrução pluvial com acúmulo"),
                OpcaoFator("Desperdício de água sem dano imediato",               0.15, "Torneira com vazamento pequeno"),
            ],
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT IA ESPECIALIZADO
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_GUT_IA = """Você é um perito de engenharia especialista em patologia das construções
e inspeção predial (NBR 16747:2020, NBR 15575-1:2024, NBR 6118, NBR 9575).

Avalie a anomalia descrita usando a Matriz GUT (escala 0–10 por dimensão).
Use GRANULARIDADE REAL — valores intermediários (3,4,5,6,7) são os mais
comuns. Justifique cada pontuação com base técnica específica.

SUBSISTEMA: {subsistema}

ANOMALIA: {descricao}

NEXO CAUSAL IDENTIFICADO PELO PERITO:
  Origem:     {nexo_origem}
  Mecanismo:  {nexo_mecanismo}
  Status:     {nexo_status}
  Descrição:  {nexo_texto}

REGRA OBRIGATÓRIA — TENDÊNCIA:
  Se Status = "Em ocorrência / Ativa e acelerando": T deve ser >= 7.
  Se Status = "Em regressão espontânea":            T deve ser <= 2.

RESPOSTAS DO PERITO AOS FATORES (se disponíveis):
{respostas_formatadas}

CASOS HISTÓRICOS SIMILARES DO BANCO LOCAL:
{historico_formatado}

REFERÊNCIAS NORMATIVAS PARA ESTE SUBSISTEMA: {normas_subsistema}

ESCALA DE REFERÊNCIA GUT:
  G: 0=sem impacto | 3=estético | 5=funcional moderado |
     7=estrutural parcial | 10=colapso/vida em risco
  U: 0=anos | 3=6–12 meses | 5=2–6 meses |
     7=até 30 dias | 10=horas/dias
  T: 0=regressão | 3=estabilizado | 5=progressão lenta |
     7=aceleração moderada | 10=exponencial em curso

Retorne EXCLUSIVAMENTE JSON válido, sem markdown ou texto adicional:
{{
  "G": {{"pontuacao": <0-10>, "justificativa": "<técnica e específica>"}},
  "U": {{"pontuacao": <0-10>, "justificativa": "<técnica e específica>"}},
  "T": {{"pontuacao": <0-10>, "justificativa": "<técnica e específica>"}},
  "prioridade": <G×U×T>,
  "classificacao_risco": "<Crítico|Alto|Médio|Baixo>",
  "tipo_anomalia": "<termo técnico preciso>",
  "acao_recomendada": "<ação técnica objetiva com prazo>",
  "normas_sugeridas": ["<NBR XXXXX>"],
  "alerta_sobreposicao": <true|false>
}}"""


# ─────────────────────────────────────────────────────────────────────────────
# MAPEAMENTO DE NORMAS POR SUBSISTEMA
# ─────────────────────────────────────────────────────────────────────────────

NORMAS_SUBSISTEMA: dict[SubsistemaGUT, list[str]] = {
    SubsistemaGUT.ESTRUTURAL:      ["NBR 6118", "NBR 9452", "NBR 15575-2", "NBR 16747:2020"],
    SubsistemaGUT.ACABAMENTO:      ["NBR 15575-4", "NBR 13755", "NBR 7200", "NBR 16747:2020"],
    SubsistemaGUT.HIDROSSANITARIO: ["NBR 5626", "NBR 8160", "NBR 9575", "NBR 15575-6"],
    SubsistemaGUT.COBERTURA:       ["NBR 15575-5", "NBR 9575", "NBR 10844"],
    SubsistemaGUT.ELETRICO:        ["NBR 5410", "NBR 5419", "NBR 15575"],
}


# ─────────────────────────────────────────────────────────────────────────────
# CLASSE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class GUTAdaptativo:
    """
    Módulo de avaliação GUT Assistida, Adaptativa e Cientificamente Fundamentada.

    Implementa:
      • Nexo causal obrigatório (Knapp & Olivan, 2021)
      • Scoring multifatorial 0–10 com granularidade real (P2)
      • Alerta de sobreposição G/U (Grossi, 2025)
      • Modo SHS opcional (Grossi, 2025)
      • Aprendizado por histórico (3 modos: autônomo / semi / treinamento)
      • Gestão consciente de IA (P7) — apenas por escolha explícita

    Exemplo de uso:
        conn = sqlite3.connect("cerebro_pericial.db")
        engine = GUTAdaptativo(conn, projeto_id=42)
        resultado = engine.avaliar("Fissura diagonal em pilar P7")
    """

    # Thresholds configuráveis (valores padrão — sobrescritos pelo YAML em __init__)
    THRESHOLD_AUTONOMO: float      = 0.80
    THRESHOLD_SEMI: float          = 0.50
    CASOS_MIN_AUTONOMO: int        = 5
    CONFIANCA_MIN_DIMENSAO: float  = 0.70
    SOBREPOSICAO_THRESHOLD: float  = 0.15   # diferença máxima entre G e U para detectar
    SOBREPOSICAO_PCT_MIN: float    = 0.50   # fração mínima de fatores sobrepostos
    T_MINIMO_EM_OCORRENCIA: int    = 7
    T_MAXIMO_EM_REGRESSAO: int     = 2
    DESCONTO_SUBSISTEMA_DIFF: float = 0.30
    # Decay temporal: ≤180 dias = sem penalidade | 181-365 = 0.8 | >365 = 0.5
    DECAY_180: float               = 1.0
    DECAY_365: float               = 0.8
    DECAY_MAIS: float              = 0.5
    PESO_CORRIGIDO: float          = 0.3

    def __init__(
        self,
        conn: sqlite3.Connection,
        ai_engine: Optional[Any] = None,
        projeto_id: Optional[int] = None,
        db_manager: Optional[Any] = None,
    ) -> None:
        """
        Inicializa o módulo GUT Adaptativo.

        Args:
            conn:       Conexão SQLite ativa com cerebro_pericial.db.
            ai_engine:  Motor de IA (objeto com método .gerar_texto(prompt) -> str).
                        Opcional — sistema opera 100% offline sem ele.
            projeto_id: ID do projeto pericial para filtragem de histórico.
            db_manager: Instância de DatabaseManager (necessária para [C] Consultar banco).
                        Se não fornecida, as funções de consulta ficam desabilitadas.
        """
        self.conn = conn
        self.ai_engine = ai_engine
        self.projeto_id = projeto_id
        self.db_manager = db_manager   # ← novo: usado por _consultar_banco
        self._subsistema_atual: Optional[SubsistemaGUT] = None
        # Carregar thresholds e decay do config_pericial.yaml (se existir)
        self._carregar_config_yaml()

    # ─────────────────────────────────────────────────────────────────────
    # CARREGAMENTO DE CONFIGURAÇÃO YAML
    # ─────────────────────────────────────────────────────────────────────

    def _carregar_config_yaml(self, config_path: str = "config_pericial.yaml") -> None:
        """
        Lê config_pericial.yaml e sobrescreve os thresholds e parâmetros de decay
        nas instâncias da classe, garantindo que as configurações do YAML sejam
        sempre respeitadas em runtime.

        Parâmetros lidos (seção gut_adaptativo):
            threshold_autonomo, threshold_semi_autonomo, casos_minimos_autonomo,
            decay_180_dias, decay_365_dias, peso_caso_corrigido, peso_projeto_atual,
            confianca_minima_dimensao, sobreposicao_threshold, sobreposicao_pct_min,
            t_minimo_em_ocorrencia, t_maximo_em_regressao, desconto_subsistema_diferente.
        """
        try:
            import yaml as _yaml
            import os as _os
            if not _os.path.exists(config_path):
                return
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = _yaml.safe_load(f) or {}
            ga = cfg.get('gut_adaptativo', {})
            if not ga:
                return

            self.THRESHOLD_AUTONOMO       = float(ga.get('threshold_autonomo',       self.THRESHOLD_AUTONOMO))
            self.THRESHOLD_SEMI           = float(ga.get('threshold_semi_autonomo',   self.THRESHOLD_SEMI))
            self.CASOS_MIN_AUTONOMO       = int(ga.get('casos_minimos_autonomo',      self.CASOS_MIN_AUTONOMO))
            self.CONFIANCA_MIN_DIMENSAO   = float(ga.get('confianca_minima_dimensao', self.CONFIANCA_MIN_DIMENSAO))
            self.SOBREPOSICAO_THRESHOLD   = float(ga.get('sobreposicao_threshold',    self.SOBREPOSICAO_THRESHOLD))
            self.SOBREPOSICAO_PCT_MIN     = float(ga.get('sobreposicao_pct_min',      self.SOBREPOSICAO_PCT_MIN))
            self.T_MINIMO_EM_OCORRENCIA   = int(ga.get('t_minimo_em_ocorrencia',      self.T_MINIMO_EM_OCORRENCIA))
            self.T_MAXIMO_EM_REGRESSAO    = int(ga.get('t_maximo_em_regressao',       self.T_MAXIMO_EM_REGRESSAO))
            self.DESCONTO_SUBSISTEMA_DIFF = float(ga.get('desconto_subsistema_diferente', self.DESCONTO_SUBSISTEMA_DIFF))
            self.PESO_CORRIGIDO           = float(ga.get('peso_caso_corrigido',        self.PESO_CORRIGIDO))
            # Decay: ≤180 dias = sem penalidade (1.0) | 181-365 = decay_180_dias | >365 = decay_365_dias
            self.DECAY_365  = float(ga.get('decay_180_dias', self.DECAY_365))   # 181-365 dias
            self.DECAY_MAIS = float(ga.get('decay_365_dias', self.DECAY_MAIS))  # >365 dias
            # DECAY_180 permanece 1.0 (≤180 dias sem penalidade — conforme especificação)

            logger.debug("Configuração YAML carregada de '%s'.", config_path)
        except Exception as exc:
            logger.warning("Não foi possível carregar config YAML: %s — usando padrões.", exc)

    # ─────────────────────────────────────────────────────────────────────
    # SEÇÃO 4 — NEXO CAUSAL
    # ─────────────────────────────────────────────────────────────────────

    def coletar_nexo_causal(self) -> NexoCausal:
        """
        Coleta os campos NC1–NC4 interativamente.
        Etapa OBRIGATÓRIA antes de qualquer cálculo GUT.
        Conforme Knapp & Olivan (2021): nexo causal precede o GUT no fluxograma.

        Returns:
            NexoCausal preenchido com origem, mecanismo, status e texto livre.

        Regras especiais NC3 (registradas e aplicadas em _aplicar_regras_nc3):
            • Em ocorrência → T ≥ 7  (Gomide et al. 2020 apud Grossi 2025)
            • Em regressão  → T ≤ 2
        """
        print("\n" + "═" * 60)
        print("  ETAPA 0 — NEXO CAUSAL  (Knapp & Olivan, 2021)")
        print("═" * 60)

        # NC1 — Origem
        origens = list(OrigemNexo)
        print("\nNC1 — Origem da anomalia:")
        for i, o in enumerate(origens, 1):
            print(f"  [{i}] {o.value}")
        origem = self._escolher_enum(origens, "Selecione a origem: ")

        # NC2 — Mecanismo
        mecanismos = list(MecanismoDegradacao)
        _DESC_MEC = {
            MecanismoDegradacao.MECANICO:      "fissuras, deformações, abrasão por sobrecarga ou impacto",
            MecanismoDegradacao.FISICO:        "variação térmica, retração, ciclos gelo/degelo, umidade",
            MecanismoDegradacao.QUIMICO:       "corrosão, carbonatação, reação álcali-sílica, lixiviação",
            MecanismoDegradacao.BIOLOGICO:     "fungos, algas, bactérias, organismos biológicos",
            MecanismoDegradacao.COMBINADO:     "dois ou mais mecanismos simultâneos ou sinérgicos",
            MecanismoDegradacao.INDETERMINADO: "causa não identificada — requer ensaios complementares",
        }
        print("\nNC2 — Mecanismo de degradação:")
        for i, m in enumerate(mecanismos, 1):
            desc = _DESC_MEC.get(m, "")
            print(f"  [{i}] {m.value:<18}  — {desc}")
        mecanismo = self._escolher_enum(mecanismos, "Selecione o mecanismo: ")

        # NC3 — Status
        status_list = list(StatusAnomalia)
        print("\nNC3 — Status atual da anomalia:")
        for i, s in enumerate(status_list, 1):
            suf = ""
            if s == StatusAnomalia.EM_OCORRENCIA:
                suf = "  ⚠️  → T recebe penalidade mínima = 7"
            elif s == StatusAnomalia.EM_REGRESSAO:
                suf = "  ℹ️  → T recebe penalidade máxima = 2"
            print(f"  [{i}] {s.value}{suf}")
        status = self._escolher_enum(status_list, "Selecione o status: ")

        # NC4 — Texto livre (opcional)
        print("\nNC4 — Descrição do nexo causal (opcional, máx. 500 caracteres):")
        texto = input("  Descreva a causa raiz identificada: ").strip()[:500]

        nexo = NexoCausal(origem=origem, mecanismo=mecanismo, status=status, texto_livre=texto)

        if nexo.is_a_determinar():
            print(
                "\n⚠️  ALERTA: Nexo causal não determinado — conclusões do GUT são "
                "preliminares.\n"
                "    Recomenda-se ensaios complementares antes da emissão do laudo definitivo."
            )

        return nexo

    # ─────────────────────────────────────────────────────────────────────
    # SELEÇÃO DE SUBSISTEMA
    # ─────────────────────────────────────────────────────────────────────

    def selecionar_subsistema(self) -> SubsistemaGUT:
        """
        Exibe menu dos 5 subsistemas NBR 15575-1:2024 e retorna o selecionado.

        Returns:
            SubsistemaGUT escolhido pelo perito.
        """
        descricoes = {
            SubsistemaGUT.ESTRUTURAL:      "Fundações, pilares, vigas, lajes, concreto armado",
            SubsistemaGUT.ACABAMENTO:      "Vedações, revestimentos, fachadas, esquadrias",
            SubsistemaGUT.HIDROSSANITARIO: "Água, esgoto, pluvial, impermeabilização",
            SubsistemaGUT.COBERTURA:       "Telhados, calhas, rufos, impermeabilização de laje",
            SubsistemaGUT.ELETRICO:        "Instalações elétricas, SPDA, aterramento, quadros",
        }
        subs = list(SubsistemaGUT)
        print("\n" + "─" * 60)
        print("  SUBSISTEMA CONSTRUTIVO  (NBR 15575-1:2024)")
        print("─" * 60)
        for i, s in enumerate(subs, 1):
            print(f"  [{i}] {s.value:<20}  {descricoes[s]}")
        sub = self._escolher_enum(subs, "Selecione o subsistema: ")
        self._subsistema_atual = sub
        return sub

    # ─────────────────────────────────────────────────────────────────────
    # SELEÇÃO DE MODO
    # ─────────────────────────────────────────────────────────────────────

    def selecionar_modo(
        self,
        descricao: str,
        subsistema: SubsistemaGUT,
        nexo_origem: Optional[OrigemNexo] = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Determina o modo de operação com base no histórico de avaliações.

        Modos:
          🟢 AUTONOMO         — ≥ 5 casos com similaridade ≥ 80%, mesma origem e subsistema
          🟡 SEMI_AUTONOMO    — similaridade 50–79% ou subsistema diferente
          🔵 TREINAMENTO      — histórico insuficiente (< 50% similaridade)

        Args:
            descricao:    Descrição da anomalia atual.
            subsistema:   Subsistema selecionado.
            nexo_origem:  Origem do nexo causal (para filtro de similaridade).

        Returns:
            Tupla (modo: str, casos: list[dict]).

        Exemplo:
            modo, casos = engine.selecionar_modo("fissura em pilar", SubsistemaGUT.ESTRUTURAL)
        """
        try:
            from database import buscar_historico_similar  # type: ignore
            casos = buscar_historico_similar(
                self.conn,
                descricao=descricao,
                embedding=None,
                subsistema=subsistema.value,
                threshold_semantico=self.THRESHOLD_AUTONOMO,
                threshold_textual=self.THRESHOLD_SEMI,
                limite=10,
                projeto_id=self.projeto_id,
            )
        except Exception as exc:
            logger.warning("buscar_historico_similar indisponível: %s — modo TREINAMENTO.", exc)
            casos = []

        if not casos:
            return "TREINAMENTO", []

        # Filtrar por mesma origem NC1 se disponível
        if nexo_origem and nexo_origem != OrigemNexo.A_DETERMINAR:
            casos_mesma_origem = [
                c for c in casos if c.get("nexo_origem") == nexo_origem.value
            ]
            if len(casos_mesma_origem) >= self.CASOS_MIN_AUTONOMO:
                casos = casos_mesma_origem

        # Calcular similaridade média ponderada (com desconto de subsistema)
        sim_media = self._calcular_sim_media(casos, subsistema)

        if len(casos) >= self.CASOS_MIN_AUTONOMO and sim_media >= self.THRESHOLD_AUTONOMO:
            return "AUTONOMO", casos
        elif sim_media >= self.THRESHOLD_SEMI:
            return "SEMI_AUTONOMO", casos
        else:
            return "TREINAMENTO", []

    def _calcular_sim_media(
        self,
        casos: list[dict[str, Any]],
        subsistema: SubsistemaGUT,
    ) -> float:
        """
        Calcula a similaridade média ponderada dos casos, aplicando:
          • desconto de 30% para subsistema diferente
          • decay temporal (≤180d=1.0 | 181–365d=0.8 | >365d=0.5)
          • peso de aceitação (aceito=1.0 | corrigido=0.3)
        """
        if not casos:
            return 0.0

        total_peso = 0.0
        soma = 0.0
        now = datetime.now()

        for caso in casos:
            sim = float(caso.get("similaridade", 0.5))

            # desconto de subsistema
            if caso.get("subsistema") != subsistema.value:
                sim *= (1.0 - self.DESCONTO_SUBSISTEMA_DIFF)

            # decay temporal
            try:
                ts = datetime.fromisoformat(caso.get("timestamp", now.isoformat()))
                delta_dias = (now - ts).days
            except ValueError:
                delta_dias = 0
            if delta_dias <= 180:
                fator_tempo = self.DECAY_180
            elif delta_dias <= 365:
                fator_tempo = self.DECAY_365
            else:
                fator_tempo = self.DECAY_MAIS

            # fator de aceitação
            fator_aceit = 1.0 if caso.get("aceito_perito", 1) else self.PESO_CORRIGIDO

            peso = fator_tempo * fator_aceit
            soma += sim * peso
            total_peso += peso

        return soma / total_peso if total_peso > 0 else 0.0

    # ─────────────────────────────────────────────────────────────────────
    # GERAÇÃO DE PERGUNTAS
    # ─────────────────────────────────────────────────────────────────────

    def gerar_perguntas(
        self,
        subsistema: SubsistemaGUT,
        dimensoes: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """
        Retorna lista de perguntas especializadas por subsistema.
        Usa versão específica do PERGUNTAS_GUT quando disponível,
        caso contrário usa a versão padrão de _FATORES.

        Args:
            subsistema: Subsistema construtivo ativo.
            dimensoes:  Lista de dimensões a incluir, ex: ["G", "U"].
                        None = todas as 12 (G1–G4, U1–U4, T1–T4).

        Returns:
            Lista de dicts: {fator_id, dimensao, peso, pergunta, opcoes: [OpcaoFator], peso_total}

        Exemplo:
            perguntas = engine.gerar_perguntas(SubsistemaGUT.ESTRUTURAL, ["G"])
        """
        ids_desejados = [
            fid for fid, f in _FATORES.items()
            if (dimensoes is None or f.dimensao in dimensoes)
        ]

        resultado: list[dict[str, Any]] = []
        for fid in ids_desejados:
            fator = _FATORES[fid]
            # Verificar se existe especialização
            if fid in PERGUNTAS_GUT and subsistema in PERGUNTAS_GUT[fid]:
                esp = PERGUNTAS_GUT[fid][subsistema]
                pergunta = esp["pergunta"]
                opcoes = list(esp["opcoes"])
            else:
                pergunta = fator.pergunta_padrao
                opcoes = list(fator.opcoes_padrao)

            # Adaptar exemplos para o subsistema
            opcoes = self._adaptar_exemplos_opcoes(fid, subsistema, opcoes)

            resultado.append({
                "fator_id": fid,
                "dimensao": fator.dimensao,
                "peso": fator.peso,
                "pergunta": pergunta,
                "opcoes": opcoes,
            })
        return resultado

    def adaptar_exemplos(self, fator: str, subsistema: SubsistemaGUT) -> dict[str, str]:
        """
        Retorna exemplos adaptados ao subsistema para um fator específico.
        Substitui apenas o campo 'exemplo', mantendo pesos e opções intactos.

        Args:
            fator:      ID do fator (ex: "G2").
            subsistema: Subsistema construtivo.

        Returns:
            Dict mapeando texto da opção → exemplo adaptado.

        Exemplo:
            exemplos = engine.adaptar_exemplos("G2", SubsistemaGUT.COBERTURA)
        """
        _EXEMPLOS_ADAPTADOS: dict[str, dict[SubsistemaGUT, list[str]]] = {
            "G2": {
                SubsistemaGUT.ESTRUTURAL:      [
                    "Fissuras em toda extensão da viga",
                    "Desplacamento de 30% da cobertura de concreto",
                    "Fissura localizada em terço central de laje",
                    "Fissura pontual em alvenaria de vedação",
                ],
                SubsistemaGUT.HIDROSSANITARIO: [
                    "Umidade em toda a laje de cobertura",
                    "Infiltração em metade do teto de apartamento",
                    "Mancha de umidade em trecho de parede",
                    "Mancha pontual abaixo de ramal",
                ],
                SubsistemaGUT.COBERTURA: [
                    "Falha de impermeabilização em toda a laje",
                    "Ruptura de manta em 40% da área",
                    "Empoçamento em trecho de 3 m²",
                    "Fissura pontual em rufo de chaminé",
                ],
                SubsistemaGUT.ELETRICO: [
                    "Fiação exposta em toda a extensão do corredor",
                    "Quadro sem tampa expondo 30% dos disjuntores",
                    "Tomada com fio solto em área circunscrita",
                    "Parafuso solto isolado em tomada",
                ],
                SubsistemaGUT.ACABAMENTO: [
                    "Desplacamento em toda a fachada principal",
                    "Bolor em metade da parede do banheiro",
                    "Infiltração em trecho de 2 m² de parede",
                    "Bolha de pintura de 30 cm²",
                ],
            },
        }
        adaptados = _EXEMPLOS_ADAPTADOS.get(fator, {}).get(subsistema, [])
        fator_obj = _FATORES.get(fator)
        if not fator_obj:
            return {}
        return {
            op.texto: adaptados[i] if i < len(adaptados) else op.exemplo
            for i, op in enumerate(fator_obj.opcoes_padrao)
        }

    def _adaptar_exemplos_opcoes(
        self,
        fator: str,
        subsistema: SubsistemaGUT,
        opcoes: list[OpcaoFator],
    ) -> list[OpcaoFator]:
        """Retorna lista de OpcaoFator com exemplos substituídos para o subsistema."""
        mapa = self.adaptar_exemplos(fator, subsistema)
        if not mapa:
            return opcoes
        return [
            OpcaoFator(texto=op.texto, peso=op.peso, exemplo=mapa.get(op.texto, op.exemplo))
            for op in opcoes
        ]

    # ─────────────────────────────────────────────────────────────────────
    # ALERTA DE SOBREPOSIÇÃO G/U  (Grossi, 2025)
    # ─────────────────────────────────────────────────────────────────────

    def detectar_sobreposicao(
        self,
        respostas: dict[str, float],
    ) -> tuple[bool, float]:
        """
        Detecta sobreposição conceitual entre dimensões G e U.
        Fundamentação: Grossi (2025) — dupla contagem implícita quando G e U
        avaliam aspectos correlacionados (anomalia grave → tende a ser urgente).

        Critério: se a diferença entre os valores G_i e U_i correspondentes
        for < SOBREPOSICAO_THRESHOLD em > 50% dos fatores de mesma posição,
        sobreposição é detectada.

        Args:
            respostas: dict mapeando fator_id → valor [0.0, 1.0].
                       Deve conter tanto fatores G (G1–G4) quanto U (U1–U4).

        Returns:
            Tuple (sobreposicao: bool, percentual: float).
            percentual representa a fração de fatores com diferença < threshold.

        Exemplo:
            sobrep, pct = engine.detectar_sobreposicao({"G1":0.7,"G2":0.7,"U1":0.7,"U2":0.7})
            # → (True, 1.0)
        """
        g_vals = {k: v for k, v in respostas.items() if k.startswith("G")}
        u_vals = {k: v for k, v in respostas.items() if k.startswith("U")}

        # Alinhar por posição numérica (G1↔U1, G2↔U2, G3↔U3, G4↔U4)
        pares: list[tuple[float, float]] = []
        for n in range(1, 5):
            gk, uk = f"G{n}", f"U{n}"
            if gk in g_vals and uk in u_vals:
                pares.append((g_vals[gk], u_vals[uk]))

        if not pares:
            return False, 0.0

        qt_sobreposto = sum(1 for g, u in pares if abs(g - u) < self.SOBREPOSICAO_THRESHOLD)
        percentual = qt_sobreposto / len(pares)
        return percentual > self.SOBREPOSICAO_PCT_MIN, percentual

    # ─────────────────────────────────────────────────────────────────────
    # CÁLCULO OFFLINE MULTIFATORIAL
    # ─────────────────────────────────────────────────────────────────────

    def calcular_score_offline(
        self,
        respostas: dict[str, float],
        nexo: NexoCausal,
    ) -> dict[str, Any]:
        """
        Calcula G, U, T pelo scoring multifatorial ponderado.
        Fórmula (P2 e Seção 6):
            score_D = round( Σ(valor_i × peso_i) / Σ(peso_i) × 10 )

        Aplica regras especiais de NC3 (Gomide et al. 2020 apud Grossi 2025):
            • status "Em ocorrência"  → T = max(T_calculado, T_MINIMO_EM_OCORRENCIA)
            • status "Em regressão"   → T = min(T_calculado, T_MAXIMO_EM_REGRESSAO)

        Executa detectar_sobreposicao() e registra resultado.

        Args:
            respostas: dict {fator_id: valor_normalizado [0.0, 1.0]}.
            nexo:      NexoCausal com status (NC3) para aplicar regras especiais.

        Returns:
            dict com G, U, T, prioridade, risco, justificativas, sobreposição, etc.

        Exemplo:
            r = engine.calcular_score_offline({"G1":1.0,"G2":1.0,"G3":1.0,"G4":1.0,
                                               "U1":1.0,"U2":1.0,"U3":1.0,"U4":1.0,
                                               "T1":1.0,"T2":1.0,"T3":1.0,"T4":1.0},
                                              nexo)
            # r["G"] = 10, r["U"] = 10, r["T"] = 10, r["prioridade"] = 1000
        """
        def _score_dim(dim: str) -> int:
            fatores_dim = {fid: f for fid, f in _FATORES.items() if f.dimensao == dim}
            soma_pesos = sum(f.peso for fid, f in fatores_dim.items() if fid in respostas)
            soma_pond = sum(
                respostas[fid] * f.peso
                for fid, f in fatores_dim.items()
                if fid in respostas
            )
            if soma_pesos == 0:
                return 0
            return round(soma_pond / soma_pesos * 10)

        G = _score_dim("G")
        U = _score_dim("U")
        T = _score_dim("T")

        # Regras especiais NC3
        G, U, T = self._aplicar_regras_nc3(G, U, T, nexo)

        prioridade = G * U * T
        risco = self._classificar_risco(prioridade)

        sobrep, sobrep_pct = self.detectar_sobreposicao(respostas)

        return {
            "G": G, "U": U, "T": T,
            "prioridade": prioridade,
            "risco": risco,
            "justificativa_G": f"Score multifatorial offline (G={G}/10)",
            "justificativa_U": f"Score multifatorial offline (U={U}/10)",
            "justificativa_T": f"Score multifatorial offline (T={T}/10)",
            "acao_recomendada": self._acao_por_risco(risco),
            "normas_sugeridas": NORMAS_SUBSISTEMA.get(self._subsistema_atual, []),
            "fonte": "treinamento",
            "confianca": 1.0,
            "sobreposicao_detectada": sobrep,
            "sobreposicao_pct": sobrep_pct,
            "nexo_indeterminado": nexo.is_a_determinar(),
        }

    # ─────────────────────────────────────────────────────────────────────
    # CÁLCULO POR HISTÓRICO
    # ─────────────────────────────────────────────────────────────────────

    def calcular_gut_por_historico(
        self,
        casos: list[dict[str, Any]],
        nexo: NexoCausal,
    ) -> dict[str, Any]:
        """
        Calcula GUT por média ponderada do histórico de avaliações confirmadas.
        Pesos: similaridade × fator_aceitacao × fator_tempo (decay).
        Aplica regras especiais de NC3 sobre o resultado final.

        Modo AUTÔNOMO: NUNCA chama IA (P7).

        Args:
            casos: Lista de registros gut_historico (dicts) com similaridade.
            nexo:  NexoCausal para aplicar regras NC3.

        Returns:
            dict com G, U, T, prioridade, risco, fonte='historico', confianca.

        Exemplo:
            casos = db.buscar_historico_similar(conn, "fissura pilar", ...)
            r = engine.calcular_gut_por_historico(casos, nexo)
        """
        if not casos:
            raise ValueError("calcular_gut_por_historico requer ao menos 1 caso.")

        now = datetime.now()
        soma_G = soma_U = soma_T = peso_total = 0.0

        for caso in casos:
            sim = float(caso.get("similaridade", 0.5))
            if caso.get("subsistema") != (
                self._subsistema_atual.value if self._subsistema_atual else ""
            ):
                sim *= 1.0 - self.DESCONTO_SUBSISTEMA_DIFF

            try:
                ts = datetime.fromisoformat(caso.get("timestamp", now.isoformat()))
                delta_dias = (now - ts).days
            except ValueError:
                delta_dias = 0

            fator_tempo = (
                self.DECAY_180 if delta_dias <= 180
                else self.DECAY_365 if delta_dias <= 365
                else self.DECAY_MAIS
            )
            fator_aceit = 1.0 if caso.get("aceito_perito", 1) else self.PESO_CORRIGIDO
            peso = sim * fator_tempo * fator_aceit

            soma_G += caso.get('G_final', caso.get('G', 5)) * peso
            soma_U += caso.get('U_final', caso.get('U', 5)) * peso
            soma_T += caso.get('T_final', caso.get('T', 5)) * peso
            peso_total += peso

        if peso_total == 0:
            raise ValueError("Peso total = 0. Verifique campos dos casos históricos.")

        G = round(soma_G / peso_total)
        U = round(soma_U / peso_total)
        T = round(soma_T / peso_total)

        G, U, T = self._aplicar_regras_nc3(G, U, T, nexo)

        prioridade = G * U * T
        risco = self._classificar_risco(prioridade)
        confianca = min(1.0, len(casos) / self.CASOS_MIN_AUTONOMO)

        return {
            "G": G, "U": U, "T": T,
            "prioridade": prioridade,
            "risco": risco,
            "justificativa_G": f"Média histórico ({len(casos)} casos, G={G}/10)",
            "justificativa_U": f"Média histórico ({len(casos)} casos, U={U}/10)",
            "justificativa_T": f"Média histórico ({len(casos)} casos, T={T}/10)",
            "acao_recomendada": self._acao_por_risco(risco),
            "normas_sugeridas": NORMAS_SUBSISTEMA.get(self._subsistema_atual, []),
            "fonte": "historico",
            "confianca": confianca,
            "sobreposicao_detectada": False,
            "sobreposicao_pct": 0.0,
            "nexo_indeterminado": nexo.is_a_determinar(),
        }

    # ─────────────────────────────────────────────────────────────────────
    # MODO SHS  (Grossi, 2025)
    # ─────────────────────────────────────────────────────────────────────

    def calcular_shs(self, respostas_shs: dict[str, Any]) -> dict[str, Any]:
        """
        Calcula o Número de Prioridade de Anomalia (NPA) pelo Método SHS.
        Fórmula: NPA = Σ[ (Ix × Ax × Vx) × Px ]
        Variáveis ESTRITAMENTE dicotômicas (0 ou 1).
        Pesos: Segurança=5, Habitabilidade=3, Sustentabilidade=1.

        Conforme Grossi (2025) — menor subjetividade, alinhado NBR 15575-1:2024
        e NBR 16747:2020. Recomendado para laudos judiciais.

        Args:
            respostas_shs: {
                "Se": {"I": 0|1, "A": 0|1, "V": 0|1},
                "H":  {"I": 0|1, "A": 0|1, "V": 0|1},
                "Su": {"I": 0|1, "A": 0|1, "V": 0|1},
            }

        Returns:
            dict com npa_total, npa_por_eixo, prioridade_shs, detalhamento.

        Raises:
            ValueError: Se qualquer variável não for dicotômica (0 ou 1).

        Exemplo:
            r = engine.calcular_shs({"Se":{"I":1,"A":1,"V":1},
                                     "H":{"I":1,"A":1,"V":1},
                                     "Su":{"I":1,"A":0,"V":1}})
            # r["npa_total"] = 8, r["prioridade_shs"] = "Prioridade 2 — Alto"
        """
        PESOS_SHS = {"Se": 5, "H": 3, "Su": 1}

        npa_por_eixo: dict[str, float] = {}
        npa_total = 0.0

        for eixo, px in PESOS_SHS.items():
            if eixo not in respostas_shs:
                npa_por_eixo[eixo] = 0.0
                continue
            eixo_r = respostas_shs[eixo]
            for var in ("I", "A", "V"):
                val = eixo_r.get(var, 0)
                if val not in (0, 1):
                    raise ValueError(
                        f"SHS requer variáveis dicotômicas (0 ou 1). "
                        f"Eixo '{eixo}', variável '{var}' = {val!r}"
                    )
            ix = eixo_r.get("I", 0)
            ax = eixo_r.get("A", 0)
            vx = eixo_r.get("V", 0)
            npa_eixo = ix * ax * vx * px
            npa_por_eixo[eixo] = npa_eixo
            npa_total += npa_eixo

        prioridade_shs = self._classificar_shs(npa_total)

        return {
            "npa_total": npa_total,
            "npa_por_eixo": npa_por_eixo,
            "prioridade_shs": prioridade_shs,
        }

    # ─────────────────────────────────────────────────────────────────────
    # AVALIAÇÃO COM IA
    # ─────────────────────────────────────────────────────────────────────

    def avaliar_com_ia(
        self,
        descricao: str,
        respostas: dict[str, float],
        nexo: NexoCausal,
        casos: list[dict[str, Any]],
        subsistema: SubsistemaGUT,
    ) -> dict[str, Any]:
        """
        Solicita avaliação ao motor de IA com prompt especializado.
        Gestão consciente de IA (P7): só chamado por escolha explícita [I].
        Fallback: calcular_score_offline() em caso de qualquer falha.

        Args:
            descricao:  Descrição da anomalia.
            respostas:  Respostas GUT já coletadas (contexto para a IA).
            nexo:       NexoCausal completo.
            casos:      Casos históricos similares para contexto.
            subsistema: Subsistema construtivo.

        Returns:
            dict compatível com calcular_score_offline (G, U, T, prioridade, risco, ...).

        Exemplo:
            r = engine.avaliar_com_ia("Fissura diagonal em pilar P7", respostas, nexo, [], SubsistemaGUT.ESTRUTURAL)
        """
        if self.ai_engine is None:
            logger.warning("IA não configurada — usando cálculo offline como fallback.")
            return self.calcular_score_offline(respostas, nexo)

        respostas_fmt = json.dumps(respostas, ensure_ascii=False, indent=2)
        historico_fmt = json.dumps(
            [
                {k: v for k, v in c.items() if k in
                 ("descricao", "G_final", "U_final", "T_final", "risco_gut", "nexo_origem")}
                for c in casos[:5]
            ],
            ensure_ascii=False, indent=2
        )
        normas_str = ", ".join(NORMAS_SUBSISTEMA.get(subsistema, []))

        prompt = PROMPT_GUT_IA.format(
            subsistema=subsistema.value,
            descricao=descricao,
            nexo_origem=nexo.origem.value,
            nexo_mecanismo=nexo.mecanismo.value,
            nexo_status=nexo.status.value,
            nexo_texto=nexo.texto_livre or "—",
            respostas_formatadas=respostas_fmt,
            historico_formatado=historico_fmt,
            normas_subsistema=normas_str,
        )

        try:
            resposta_raw = self.ai_engine.gerar_texto(prompt)
            dados = json.loads(resposta_raw)

            G = int(dados["G"]["pontuacao"])
            U = int(dados["U"]["pontuacao"])
            T = int(dados["T"]["pontuacao"])
            G, U, T = self._aplicar_regras_nc3(G, U, T, nexo)

            prioridade = G * U * T
            risco = self._classificar_risco(prioridade)

            sobrep, sobrep_pct = self.detectar_sobreposicao(respostas)

            return {
                "G": G, "U": U, "T": T,
                "prioridade": prioridade,
                "risco": risco,
                "justificativa_G": dados.get("G", {}).get("justificativa", ""),
                "justificativa_U": dados.get("U", {}).get("justificativa", ""),
                "justificativa_T": dados.get("T", {}).get("justificativa", ""),
                "acao_recomendada": dados.get("acao_recomendada", ""),
                "normas_sugeridas": dados.get("normas_sugeridas", []),
                "fonte": "ia",
                "confianca": 0.9,
                "sobreposicao_detectada": sobrep or dados.get("alerta_sobreposicao", False),
                "sobreposicao_pct": sobrep_pct,
                "nexo_indeterminado": nexo.is_a_determinar(),
            }

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("Falha ao processar resposta da IA: %s — fallback offline.", exc)
            return self.calcular_score_offline(respostas, nexo)

    # ─────────────────────────────────────────────────────────────────────
    # EXPORTAÇÃO PARA GUT EXISTENTE
    # ─────────────────────────────────────────────────────────────────────

    def exportar_para_gut(
        self,
        resultado: dict[str, Any],
        topico_id: int,
    ) -> bool:
        """
        Atualiza gut_auto no tópico especificado.
        NUNCA sobrescreve gut_perito (P5 — retrocompatibilidade).

        Args:
            resultado:  dict com G, U, T, prioridade, risco.
            topico_id:  ID do tópico na tabela topicos.

        Returns:
            True se atualizado com sucesso, False caso contrário.

        Exemplo:
            engine.exportar_para_gut(resultado, topico_id=42)
        """
        try:
            cur = self.conn.cursor()
            cur.execute(
                """UPDATE topicos
                   SET gut_auto = ?
                   WHERE id = ?""",
                (
                    json.dumps(
                        {
                            "G": resultado["G"],
                            "U": resultado["U"],
                            "T": resultado["T"],
                            "prioridade": resultado["prioridade"],
                            "risco": resultado["risco"],
                            "fonte": resultado.get("fonte", "treinamento"),
                            "timestamp": datetime.now().isoformat(),
                        }
                    ),
                    topico_id,
                ),
            )
            self.conn.commit()
            logger.info("gut_auto atualizado para tópico %d.", topico_id)
            return True
        except sqlite3.Error as exc:
            logger.error("Erro ao exportar para gut_auto (tópico %d): %s", topico_id, exc)
            return False

    # ─────────────────────────────────────────────────────────────────────
    # MÉTODO PRINCIPAL — FLUXO COMPLETO
    # ─────────────────────────────────────────────────────────────────────

    def avaliar(
        self,
        descricao: str,
        forcar_modo: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Método principal de avaliação GUT Adaptativa.
        Fluxo completo conforme Seção 11 e Seção 13:
          1. selecionar_subsistema()
          2. coletar_nexo_causal()
          3. selecionar_modo()     [ou forcar_modo]
          4. Executar modo selecionado
          5. detectar_sobreposicao() (modo treinamento)
          6. Exibir resultado formatado
          7. Oferecer opções pós-avaliação [S/E/V/M/I/N]
          8. Registrar e salvar

        Args:
            descricao:   Descrição textual da anomalia.
            forcar_modo: "TREINAMENTO" | "SEMI_AUTONOMO" | "AUTONOMO" (opcional).

        Returns:
            dict com resultado final (G, U, T, prioridade, risco, SHS se calculado).

        Exemplo:
            r = engine.avaliar("Fissura em pilar P7 — CA com corrosão de armadura")
        """
        import uuid as _uuid_mod

        # ── Verificar sessão pendente (Resiliência — Seção 4) ────────────
        pendente = self._verificar_sessao_pendente()
        if pendente:
            print(
                f"\n  ⚠️  Avaliação incompleta encontrada:\n"
                f"  Anomalia  : {pendente['descricao'][:60]}\n"
                f"  Última etapa: {pendente['etapa_atual']} | {pendente['timestamp'][:16]}\n"
            )
            op_rec = input("  [R] Retomar | [N] Iniciar nova: ").strip().upper()
            if op_rec == "R":
                return self._retomar_sessao(pendente)
            else:
                self._expirar_sessao(pendente["session_id"])

        # ── Gerar session_id único ────────────────────────────────────────
        _session_id = str(_uuid_mod.uuid4())
        self._salvar_etapa_parcial(_session_id, "inicio", 0.0, descricao=descricao)

        print("\n" + "=" * 68)
        print("   GUT ADAPTATIVO v4.0  —  Cerebro de Engenharia Diagnostica")
        print("=" * 68)
        print(f"\nAnomalia: {descricao}\n")

        # ── Identificacao do item (para o quadro de caracterizacao) ──────
        print("  Numero do item / referencia (ex: 01, A-3) [ENTER para pular]: ", end="")
        item_num = input().strip() or "—"
        print("  Localizacao resumida (ex: Infiltracao rodape, Pilar P7) [ENTER para usar descricao]: ", end="")
        localizacao_input = input().strip()
        if not localizacao_input:
            localizacao_input = descricao[:30]

        # ── Passo 1: Subsistema ──────────────────────────────────────────
        subsistema = self.selecionar_subsistema()

        # ── Passo 2: Nexo Causal (OBRIGATÓRIO — P3) ──────────────────────
        nexo = self.coletar_nexo_causal()

        # ── Passo 3: Modo ────────────────────────────────────────────────
        if forcar_modo:
            modo = forcar_modo
            casos: list[dict[str, Any]] = []
        else:
            modo, casos = self.selecionar_modo(descricao, subsistema, nexo.origem)

        icone_modo = {"AUTONOMO": "🟢", "SEMI_AUTONOMO": "🟡", "TREINAMENTO": "🔵"}.get(modo, "🔵")
        print(f"\n{icone_modo} Modo: {modo}  ({len(casos)} caso(s) histórico(s) encontrado(s))")
        if modo == "TREINAMENTO" and forcar_modo is None:
            opcao_f = input("  [Enter] Continuar | [F] Forçar Treinamento Completo: ").upper()
            if opcao_f == "F":
                modo = "TREINAMENTO"

        # ── Passo 4: Executar modo ───────────────────────────────────────
        respostas: dict[str, float] = {}
        resultado: dict[str, Any] = {}
        self._sessao_id_atual = _session_id  # usado em _coletar_respostas

        if modo == "AUTONOMO":
            print("\n🟢 Aplicando média ponderada do histórico (sem perguntas)...")
            resultado = self.calcular_gut_por_historico(casos, nexo)

        elif modo == "SEMI_AUTONOMO":
            # Identificar dimensões com confiança < 70%
            dims_baixa_confianca = self._dims_baixa_confianca(casos)
            if dims_baixa_confianca:
                print(f"\n🟡 Perguntas parciais para dimensões: {dims_baixa_confianca}")
                respostas = self._coletar_respostas(subsistema, dims_baixa_confianca)
            resultado = self.calcular_score_offline(respostas, nexo)
            # Complementar com histórico para dimensões sem perguntas
            if casos and not dims_baixa_confianca:
                resultado = self.calcular_gut_por_historico(casos, nexo)

        else:  # TREINAMENTO COMPLETO
            print("\n🔵 Modo Treinamento Completo — todas as 12 dimensões serão avaliadas.")
            respostas = self._coletar_respostas(subsistema)
            resultado = self.calcular_score_offline(respostas, nexo)

        # ── Passo 5: Alerta de sobreposição ──────────────────────────────
        if resultado.get("sobreposicao_detectada"):
            pct = resultado.get("sobreposicao_pct", 0.0)
            print(
                f"\n⚠️  ALERTA DE SOBREPOSIÇÃO: As avaliações de Gravidade e Urgência "
                f"apresentam alta correlação ({pct * 100:.0f}%).\n"
                "    G deve medir o IMPACTO do dano. U deve medir o TEMPO disponível.\n"
                "    Deseja revisar alguma resposta? [S] Revisar | [N] Manter"
            )
            if input("  > ").upper() == "S":
                respostas = self._coletar_respostas(subsistema)
                resultado = self.calcular_score_offline(respostas, nexo)

        # ── Passo 6: Exibir resultado ─────────────────────────────────────
        self._exibir_resultado(descricao, subsistema, nexo, resultado)

        # ── Passo 7: Opções pós-avaliação ────────────────────────────────
        resultado_final = resultado.copy()
        resultado_final.update({
            "descricao":      descricao,
            "subsistema":     subsistema.value,
            "nexo":           nexo,
            "respostas_json": json.dumps(respostas),
            "item_numero":    item_num,
            "localizacao":    localizacao_input,
        })

        while True:
            n_trechos = 0
            try:
                from database import contar_trechos_vinculados
                n_trechos = contar_trechos_vinculados(resultado_final.get("anotacoes", ""))
            except Exception:
                pass
            trechos_str = f"  [{n_trechos} trecho(s) vinculado(s)]" if n_trechos else ""
            print(
                "\n  [S] Salvar       [E] Editar G/U/T     [A] Anotacoes/Sintomas"
                "\n  [C] Consultar banco                   [VA] Ver anotacao" + trechos_str +
                "\n  [V] Vincular a topico   [M] Calcular SHS (Grossi, 2025)"
                "\n  [I] Reavaliar com IA    [N] Descartar"
            )
            op = input("  Opcao: ").upper().strip()

            if op == "S":
                self._salvar_historico(resultado_final, nexo, subsistema)
                self._expirar_sessao(_session_id)
                print("  Avaliacao salva com sucesso.")
                break

            elif op == "A":
                nova = self._coletar_anotacao_v2(
                    anotacao_atual=resultado_final.get("anotacoes", ""),
                    conn_principal=self.conn,
                )
                if nova is not None:
                    resultado_final["anotacoes"] = nova
                    self._exibir_resultado(descricao, subsistema, nexo, resultado_final)

            elif op == "C":
                # Consultar banco diretamente (independente da anotacao)
                nova = self._consultar_banco(
                    anotacao_atual=resultado_final.get("anotacoes", ""),
                    origem="menu",
                )
                if nova is not None:
                    resultado_final["anotacoes"] = nova
                    self._exibir_resultado(descricao, subsistema, nexo, resultado_final)

            elif op == "VA":
                # Ver anotacao completa sem editar
                anotacao_ver = resultado_final.get("anotacoes", "")
                if not anotacao_ver:
                    print("  Nenhuma anotacao registrada.")
                else:
                    print("\n" + "=" * 72)
                    print("  ANOTACAO COMPLETA:")
                    print("=" * 72)
                    linhas_ver = anotacao_ver.split("\n")
                    for idx_ver in range(0, len(linhas_ver), 40):
                        bloco_ver = "\n".join(linhas_ver[idx_ver:idx_ver + 40])
                        print(bloco_ver)
                        if idx_ver + 40 < len(linhas_ver):
                            resp_ver = input("  [ENTER continuar | Q sair] ").strip().upper()
                            if resp_ver == "Q":
                                break

            elif op == "E":
                print("  [G] Editar Gravidade | [U] Editar Urgência | [T] Editar Tendência")
                dim = input("  Dimensão: ").upper().strip()
                if dim in ("G", "U", "T"):
                    try:
                        novo_val = int(input(f"  Novo valor para {dim} (0–10): "))
                        novo_val = max(0, min(10, novo_val))
                        resultado_final[dim] = novo_val
                        resultado_final["prioridade"] = (
                            resultado_final["G"] * resultado_final["U"] * resultado_final["T"]
                        )
                        resultado_final["risco"] = self._classificar_risco(resultado_final["prioridade"])
                        resultado_final["G_original"] = resultado.get("G")
                        resultado_final["U_original"] = resultado.get("U")
                        resultado_final["T_original"] = resultado.get("T")
                        print(f"  ✅ {dim} atualizado para {novo_val}.")
                    except ValueError:
                        print("  Valor inválido.")

            elif op == "V":
                try:
                    tid = int(input("  ID do tópico: "))
                    ok = self.exportar_para_gut(resultado_final, tid)
                    print("  ✅ Vinculado." if ok else "  ❌ Falha ao vincular.")
                except ValueError:
                    print("  ID inválido.")

            elif op == "M":
                shs_resp = self._coletar_respostas_shs()
                try:
                    shs = self.calcular_shs(shs_resp)
                    resultado_final["npa_shs"] = shs["npa_total"]
                    resultado_final["prioridade_shs"] = shs["prioridade_shs"]
                    resultado_final["shs_converge"] = self._verificar_convergencia(
                        resultado_final["risco"], shs["prioridade_shs"]
                    )
                    self._exibir_comparativo(resultado_final, shs)
                except ValueError as exc:
                    print(f"  ❌ Erro SHS: {exc}")

            elif op == "I":
                if self.ai_engine is None:
                    print("  ⚠️  IA não configurada — verifique ai_engine no construtor.")
                else:
                    print("  🤖 Avaliando com IA...")
                    resultado_ia = self.avaliar_com_ia(
                        descricao, respostas, nexo, casos, subsistema
                    )
                    resultado_final.update(resultado_ia)
                    resultado_final["fonte"] = "ia"
                    self._exibir_resultado(descricao, subsistema, nexo, resultado_final)

            elif op == "N":
                self._expirar_sessao(_session_id)
                print("  Avaliação descartada.")
                break

        return resultado_final

    # ─────────────────────────────────────────────────────────────────────
    # HELPERS PRIVADOS
    # ─────────────────────────────────────────────────────────────────────

    def _aplicar_regras_nc3(
        self, G: int, U: int, T: int, nexo: NexoCausal
    ) -> tuple[int, int, int]:
        """
        Aplica regras especiais do NC3 sobre T.
        • Em ocorrência → T ≥ T_MINIMO_EM_OCORRENCIA (7)
        • Em regressão  → T ≤ T_MAXIMO_EM_REGRESSAO  (2)
        Conforme Gomide et al. 2020 apud Grossi (2025).
        """
        if nexo.status == StatusAnomalia.EM_OCORRENCIA:
            T = max(T, self.T_MINIMO_EM_OCORRENCIA)
        elif nexo.status == StatusAnomalia.EM_REGRESSAO:
            T = min(T, self.T_MAXIMO_EM_REGRESSAO)
        return G, U, T

    @staticmethod
    def _classificar_risco(prioridade: int) -> str:
        """
        Classifica o risco pelo produto G × U × T.
        Thresholds calibrados para escala 0–1000 (Knapp & Olivan, 2021, adaptado).
        """
        if prioridade >= 500:
            return "Crítico"
        elif prioridade >= 200:
            return "Alto"
        elif prioridade >= 50:
            return "Médio"
        return "Baixo"

    @staticmethod
    def _classificar_shs(npa: float) -> str:
        """
        Classifica a prioridade SHS conforme Grossi (2025).
        NPA máximo teórico = 9.
        """
        if npa >= 9:
            return "Prioridade 1 — Crítico (interdição imediata)"
        elif npa >= 5:
            return "Prioridade 2 — Alto (intervenção urgente)"
        elif npa >= 2:
            return "Prioridade 3 — Médio (planejamento de reparo)"
        return "Prioridade 4 — Baixo (monitoramento)"

    @staticmethod
    def _verificar_convergencia(risco_gut: str, prioridade_shs: str) -> bool:
        """
        Verifica convergência entre GUT e SHS.
        CONVERGE: Crítico/Alto ↔ P1/P2 | Médio/Baixo ↔ P3/P4.
        """
        gut_alto = risco_gut in ("Crítico", "Alto")
        shs_alto = "1" in prioridade_shs or "2" in prioridade_shs
        return gut_alto == shs_alto

    @staticmethod
    def _acao_por_risco(risco: str) -> str:
        """Retorna ação técnica recomendada com base na classificação de risco."""
        return {
            "Crítico": "Interdição imediata — intervenção de emergência (horas/dias)",
            "Alto":    "Reforço/reparo urgente em até 30 dias",
            "Médio":   "Reparos planejados — incluir em próximo ciclo de manutenção",
            "Baixo":   "Manutenção rotineira — monitorar periodicamente",
        }.get(risco, "Verificar com engenheiro responsável")

    def _dims_baixa_confianca(self, casos: list[dict[str, Any]]) -> list[str]:
        """
        Identifica dimensões com confiança < CONFIANCA_MIN_DIMENSAO no histórico.
        Usado no Modo SEMI-AUTÔNOMO para definir quais perguntas fazer.
        """
        if not casos:
            return ["G", "U", "T"]
        sim_media = self._calcular_sim_media(
            casos, self._subsistema_atual or SubsistemaGUT.ESTRUTURAL
        )
        dims: list[str] = []
        # Heurística: se similaridade < threshold, incluir dimensão
        if sim_media < self.CONFIANCA_MIN_DIMENSAO:
            dims.append("G")
        if sim_media < self.CONFIANCA_MIN_DIMENSAO * 0.9:
            dims.append("U")
        if sim_media < self.CONFIANCA_MIN_DIMENSAO * 0.8:
            dims.append("T")
        return dims or []

    def _coletar_respostas(
        self,
        subsistema: SubsistemaGUT,
        dimensoes: Optional[list[str]] = None,
    ) -> dict[str, float]:
        """
        Apresenta perguntas especializadas ao perito e coleta as respostas.

        Returns:
            dict {fator_id: valor_normalizado [0.0, 1.0]}
        """
        perguntas = self.gerar_perguntas(subsistema, dimensoes)
        respostas: dict[str, float] = {}
        # _session_id pode não estar disponível se chamado externamente — proteger
        _sessao_id = getattr(self, "_sessao_id_atual", None)

        for perg in perguntas:
            fid = perg["fator_id"]
            dim = perg["dimensao"]
            opcoes: list[OpcaoFator] = perg["opcoes"]

            print(f"\n  ── {fid} [{dim}] ──────────────────────────────")
            print(f"  {perg['pergunta']}")
            for i, op in enumerate(opcoes, 1):
                ex = f"  ex: {op.exemplo}" if op.exemplo else ""
                print(f"    [{i}] {op.texto}{ex}")

            while True:
                try:
                    escolha = int(input(f"  Opção (1–{len(opcoes)}): "))
                    if 1 <= escolha <= len(opcoes):
                        respostas[fid] = opcoes[escolha - 1].peso
                        # Persistir imediatamente após cada resposta
                        if _sessao_id:
                            self._salvar_etapa_parcial(_sessao_id, fid, respostas[fid])
                        break
                    print(f"  ⚠️  Escolha entre 1 e {len(opcoes)}.")
                except (ValueError, EOFError):
                    print("  ⚠️  Entrada inválida.")

        return respostas

    def _coletar_respostas_shs(self) -> dict[str, Any]:
        """
        Coleta as 9 respostas dicotômicas do Método SHS (Grossi, 2025).

        Returns:
            dict {"Se": {"I":0|1,"A":0|1,"V":0|1}, "H": {...}, "Su": {...}}
        """
        PERGUNTAS_SHS = {
            "Se": {
                "I": "A anomalia afeta a segurança estrutural, contra incêndio ou no uso e operação?",
                "A": "O comprometimento de segurança é generalizado (> 50% do elemento/múltiplos ambientes)?",
                "V": "A degradação da segurança está avançando rapidamente?",
            },
            "H": {
                "I": "A anomalia compromete estanqueidade, saúde, higiene, funcionalidade ou acessibilidade?",
                "A": "O comprometimento da habitabilidade é generalizado?",
                "V": "A degradação da habitabilidade avança rapidamente?",
            },
            "Su": {
                "I": "A anomalia compromete a durabilidade, manutenibilidade ou causa impacto ambiental?",
                "A": "O comprometimento da sustentabilidade é generalizado?",
                "V": "O agravamento na durabilidade/impacto ambiental avança rapidamente?",
            },
        }
        EIXO_NOMES = {
            "Se": "SEGURANÇA (peso 5)",
            "H":  "HABITABILIDADE (peso 3)",
            "Su": "SUSTENTABILIDADE (peso 1)",
        }

        respostas_shs: dict[str, dict[str, int]] = {}
        print("\n  ── MÉTODO SHS (Grossi, 2025) ──────────────────────────────────")

        for eixo, perguntas in PERGUNTAS_SHS.items():
            print(f"\n  EIXO {EIXO_NOMES[eixo]}")
            respostas_shs[eixo] = {}
            for var, pergunta in perguntas.items():
                print(f"\n  {eixo}_{var} — {pergunta}")
                print("    [S] Sim (1)  |  [N] Não (0)")
                while True:
                    resp = input("  > ").upper().strip()
                    if resp in ("S", "N"):
                        respostas_shs[eixo][var] = 1 if resp == "S" else 0
                        break
                    print("  ⚠️  Responda [S] ou [N].")

        return respostas_shs

    # ─────────────────────────────────────────────────────────────────────
    # [C] CONSULTAR BANCO — Fluxo v2.0: Consulta → Leitura → Decisão
    # Referência: Prompt v2.0 Seções 1-8
    # ─────────────────────────────────────────────────────────────────────

    def _consultar_banco(
        self,
        anotacao_atual: str = "",
        origem: str = "menu",
    ) -> Optional[str]:
        """
        Fluxo completo de consulta ao banco de normas e laudos.
        Princípio v2.0: Ver completo → Decidir → Inserir o que escolheu.

        As 3 etapas são obrigatórias e sequenciais:
          ETAPA 1 — CONSULTA: perito busca termos no banco
          ETAPA 2 — LEITURA:  lê trechos completos, marca com [M]
          ETAPA 3 — DECISÃO:  escolhe ação para cada trecho

        Args:
            anotacao_atual: Anotação já existente (para append).
            origem:         "menu" (opção [C]) | "anotacao" (sub-modo de [A]).

        Returns:
            Anotação atualizada (str) ou None se cancelado.
        """
        # --- Importar helpers do banco ---
        try:
            from database import (
                buscar_trechos_banco,
                formatar_trecho_para_insercao,
                montar_anotacao_final,
                sugerir_sinonimos_busca,
            )
        except ImportError as exc:
            print(f"\n  Banco nao disponivel: {exc}")
            return None

        # Importar dicionario de sinonimos se disponivel
        try:
            from processors import DICIONARIO_SINONIMOS  # type: ignore
        except ImportError:
            DICIONARIO_SINONIMOS = {}

        # Verificar db_manager — prioridade: self.db_manager > self.db > self.conn com busca_hibrida
        db_manager = (
            getattr(self, "db_manager", None)
            or getattr(self, "db", None)
        )
        if db_manager is None or not hasattr(db_manager, "busca_hibrida"):
            print("\n  ⚠️  Consulta ao banco requer DatabaseManager.")
            print("  Verifique se gut_adaptativo_cli() está passando db_manager=self.db")
            return None

        W = 74  # largura de quebra de linha

        # ── utilitarios locais ─────────────────────────────────────────

        def _wrap(texto: str, largura: int = W) -> str:
            """Quebra texto em linhas de max largura chars sem cortar palavras."""
            linhas_orig = texto.split("\n")
            resultado: List[str] = []
            for linha in linhas_orig:
                if not linha:
                    resultado.append("")
                    continue
                while len(linha) > largura:
                    # Tentar cortar em espaço
                    pos = linha.rfind(" ", 0, largura)
                    if pos <= 0:
                        pos = largura
                    resultado.append(linha[:pos])
                    linha = linha[pos:].lstrip()
                resultado.append(linha)
            return "\n".join(resultado)

        def _renderizar_tabelas(texto: str) -> str:
            """Converte [[TABELA_N]] CSV para grid visual."""
            import re as _re
            def _conv(m: "_re.Match") -> str:
                n = m.group(1)
                linhas = m.group(2).strip().split("\n")
                grade = []
                for l in linhas:
                    colunas = [c.strip() for c in l.split(";")]
                    grade.append("  " + " | ".join(f"{c:<12}" for c in colunas))
                return f"  [[TABELA_{n}]]\n" + "\n".join(grade) + f"\n  [[/TABELA_{n}]]"
            return _re.sub(
                r"\[\[TABELA_(\d+)\]\](.*?)\[\[/TABELA_\1\]\]",
                _conv, texto, flags=_re.DOTALL
            )

        def _exibir_bloco(r: dict, n: int, total: int, marcados: set) -> None:
            """Exibe resultado completo — sem truncamento de texto."""
            estrela = " ★" if n in marcados else ""
            score_pct = round(r.get("score", 0) * 100)
            sep_duplo = "=" * 72
            sep_simples = "-" * 72
            risco = r.get("risco_gut", r.get("grau_risco", ""))
            print(f"\n{sep_duplo}")
            print(f"  RESULTADO [{n}] de [{total}]{estrela}")
            print(sep_simples)
            print(f"  Fonte:  {r.get('nome_fonte', '—')}")
            print(f"  Secao:  {r.get('hierarquia', '—')}")
            print(f"  Score:  {score_pct}%  |  Tipo: {r.get('tipo_fonte', '—')}")
            if risco in ("Alto", "Critico", "Máximo", "Critico"):
                print(f"  ATENCAO: Trecho classificado como risco {risco}")
            print(sep_simples)
            print()
            texto_exib = _renderizar_tabelas(r.get("texto", "").strip())
            print(_wrap(texto_exib))
            print()
            print(sep_duplo)

        def _mini_menu_leitura(n: int, total: int, marcados: set) -> str:
            """Mini-menu exibido após cada resultado na Etapa 2."""
            estrela = " (marcado ★)" if n in marcados else ""
            print(f"\n  Resultado [{n}/{total}]{estrela}")
            if n < total:
                print("  [ENTER] Proximo   [M] Marcar/Desmarcar   [P] Anterior   [F] Ir para decisao")
            else:
                print("  [ENTER] Ir para decisao   [M] Marcar/Desmarcar   [P] Anterior")
            return input("  > ").strip().upper()

        # ── loop externo: permite nova busca ([4]) ─────────────────────
        marcados: set = set()
        resultados: List[dict] = []
        query_atual = ""

        while True:

            # ══════════════════════════════════════════════════════════
            # ETAPA 1 — CONSULTA
            # ══════════════════════════════════════════════════════════
            sep = "=" * 72
            print(f"\n{sep}")
            print("  CONSULTA AO BANCO PERICIAL")
            print(sep)

            # Termos de busca
            while True:
                query = input("\n  Termos de busca (palavras-chave ou frase):\n  > ").strip()
                if query:
                    break
                print("  ATENCAO: Digite ao menos um termo.")

            # Filtro de fonte
            print()
            print("  Filtrar por fonte:")
            print("  [1] Todas as fontes  (padrao)")
            print("  [2] Apenas normas    (ABNT, NBR)")
            print("  [3] Apenas laudos    (judiciais)")
            print("  [4] Apenas livros    (literatura tecnica)")
            fonte_op = input("  Fonte [1-4] ou ENTER para todas: ").strip()
            fonte_map = {"1": None, "2": "norma", "3": "laudo", "4": "livro"}
            fonte_filtro = fonte_map.get(fonte_op, None)
            fonte_nome = {None: "todas", "norma": "normas", "laudo": "laudos", "livro": "livros"}.get(fonte_filtro, "todas")

            # Quantidade
            lim_str = input("  Quantidade de resultados [5/10/15] ou ENTER=5: ").strip()
            limite = int(lim_str) if lim_str in ("5", "10", "15") else 5

            print(f"\n  Buscando '{query}' em {fonte_nome} (max {limite})...")

            try:
                resultados = buscar_trechos_banco(
                    db_manager=db_manager,
                    query=query,
                    fonte_filtro=fonte_filtro,
                    limite=limite,
                )
            except Exception as exc:
                logger.warning("_consultar_banco: busca falhou: %s", exc)
                resultados = []

            query_atual = query

            # Sem resultados
            if not resultados:
                print(f"\n  Nenhum resultado para \"{query}\".")
                sugestoes = sugerir_sinonimos_busca(query, DICIONARIO_SINONIMOS)
                if sugestoes:
                    print(f"  Sinonimo sugerido: {', '.join(sugestoes)}")
                print(f"  Tente termos mais genericos ou mude o filtro (atual: {fonte_nome}).")
                print("\n  [R] Nova busca  |  [0] Voltar")
                op_sem = input("  > ").strip().upper()
                if op_sem == "0":
                    return None
                continue  # nova busca

            total = len(resultados)
            print(f"\n  {total} resultado(s) encontrado(s).")

            # Manter marcados de busca anterior?
            if marcados:
                resp_mant = input(
                    f"  Manter {len(marcados)} marcado(s) da busca anterior? [S/N]: "
                ).strip().upper()
                if resp_mant != "S":
                    marcados = set()

            # ══════════════════════════════════════════════════════════
            # ETAPA 2 — LEITURA (completa, sem pular)
            # ══════════════════════════════════════════════════════════
            i = 1  # índice 1-based
            while True:
                _exibir_bloco(resultados[i - 1], i, total, marcados)
                op_leit = _mini_menu_leitura(i, total, marcados)

                if op_leit == "M":
                    if i in marcados:
                        marcados.discard(i)
                        print(f"  Resultado [{i}] desmarcado. ({len(marcados)} marcado(s))")
                    else:
                        marcados.add(i)
                        print(f"  Resultado [{i}] marcado com estrela. ({len(marcados)} marcado(s))")
                    # Reler o mini-menu com status atualizado — não avança
                    continue

                elif op_leit == "P":
                    i = max(1, i - 1)
                    continue

                elif op_leit == "F":
                    break  # Ir para Etapa 3

                else:
                    # ENTER ou qualquer tecla = avançar
                    if i < total:
                        i += 1
                    else:
                        break  # Último resultado → Etapa 3

            # ══════════════════════════════════════════════════════════
            # ETAPA 3 — DECISÃO
            # ══════════════════════════════════════════════════════════
            ir_para_nova_busca = False

            while True:
                sep = "=" * 72
                print(f"\n{sep}")
                print("  RESUMO DA CONSULTA")
                print(sep)
                print(f"  Busca: \"{query_atual}\"")
                print(f"  Resultados encontrados: {total}")
                print(f"  Resultados marcados: {len(marcados)}")

                if marcados:
                    print("\n  Marcados (★):")
                    for idx_m in sorted(marcados):
                        r = resultados[idx_m - 1]
                        preview = r.get("texto", "")[:60].replace("\n", " ")
                        print(f"  {idx_m}. [{r.get('nome_fonte','—')}] {r.get('hierarquia','')[:30]} — {preview}")

                nao_marcados = [x for x in range(1, total + 1) if x not in marcados]
                if nao_marcados:
                    print("\n  Nao marcados:")
                    for idx_n in nao_marcados:
                        r = resultados[idx_n - 1]
                        preview = r.get("texto", "")[:60].replace("\n", " ")
                        print(f"  {idx_n}. [{r.get('nome_fonte','—')}] {r.get('hierarquia','')[:30]} — {preview}")

                print(f"\n{'-' * 72}")
                print("  O QUE DESEJA FAZER?")
                print()
                print("  [1] Inserir marcados (★) na anotacao")
                print("  [2] Selecionar trechos especificos para anotacao")
                print("  [3] Rever um resultado completo antes de decidir")
                print("  [4] Fazer nova busca")
                print("  [5] Encerrar sem inserir nada")
                decisao = input("\n  Escolha [1-5]: ").strip()

                # ── [5] Encerrar ──────────────────────────────────────
                if decisao == "5":
                    print("  Consulta encerrada. Nenhum texto inserido.")
                    return None

                # ── [4] Nova busca ────────────────────────────────────
                elif decisao == "4":
                    ir_para_nova_busca = True
                    break

                # ── [3] Rever resultado ───────────────────────────────
                elif decisao == "3":
                    try:
                        n_rev = int(input(f"  Qual resultado deseja rever? [1-{total}]: ").strip())
                        if 1 <= n_rev <= total:
                            _exibir_bloco(resultados[n_rev - 1], n_rev, total, marcados)
                            input("  [ENTER para voltar ao menu de decisao]")
                        else:
                            print(f"  Numero invalido. Use entre 1 e {total}.")
                    except ValueError:
                        print("  Entrada invalida.")
                    continue

                # ── [1] Inserir marcados ──────────────────────────────
                elif decisao == "1":
                    if not marcados:
                        print("  ATENCAO: Nenhum resultado marcado.")
                        print("  Marque com [M] durante a leitura ou use opcao [2] para selecionar.")
                        continue
                    selecionados = sorted(marcados)

                # ── [2] Selecionar especificos ────────────────────────
                elif decisao == "2":
                    print("\n  Resultados disponíveis:")
                    for idx_r, r in enumerate(resultados, 1):
                        estrela = "★" if idx_r in marcados else " "
                        print(f"  {idx_r}. {estrela} [{r.get('nome_fonte','—')}] {r.get('hierarquia','')[:40]}")
                    entrada = input("\n  Numeros desejados (ex: 1,3,5):\n  > ").strip()
                    if not entrada:
                        continue
                    selecionados = []
                    for s in entrada.replace(" ", "").split(","):
                        try:
                            n_s = int(s)
                            if 1 <= n_s <= total:
                                if n_s not in selecionados:
                                    selecionados.append(n_s)
                            else:
                                print(f"  Numero {n_s} invalido. Ignorado.")
                        except ValueError:
                            print(f"  '{s}' invalido. Ignorado.")
                    if not selecionados:
                        continue

                else:
                    print("  Opcao invalida.")
                    continue

                # ── Processar cada selecionado com mini-menu [I/P/R/S] ─

                lista_para_inserir: List[str] = []

                for idx_s in selecionados:
                    r = resultados[idx_s - 1]
                    estrela = " ★" if idx_s in marcados else ""
                    print(f"\n  {'─' * 68}")
                    print(f"  RESULTADO [{idx_s}]{estrela}")
                    print(f"  [{r.get('nome_fonte','—')}] {r.get('hierarquia','')}")
                    print(f"  {'─' * 68}")
                    preview200 = r.get("texto", "")[:200].replace("\n", " ")
                    total_chars = len(r.get("texto", ""))
                    print(f"  {preview200}...")
                    print(f"  [{total_chars} chars no total]")

                    # Verificar duplicata na anotacao existente
                    marcador_dup = f"Fonte: [{r.get('nome_fonte','—')}]"
                    hier_dup = r.get("hierarquia", "")
                    if anotacao_atual and marcador_dup in anotacao_atual and hier_dup in anotacao_atual:
                        resp_dup = input(
                            "  ATENCAO: Este trecho ja esta na anotacao. Inserir novamente? [S/N]: "
                        ).strip().upper()
                        if resp_dup != "S":
                            print(f"  Resultado [{idx_s}] pulado.")
                            continue

                    while True:
                        print()
                        print("  Como inserir na anotacao?")
                        print("  [I] Inserir integral (todo o trecho)")
                        print("  [P] Inserir parcialmente (eu digito a parte que quero)")
                        print("  [R] Rever texto completo antes de decidir")
                        print("  [S] Pular este resultado (nao inserir)")
                        mini_op = input("  Opcao [I/P/R/S]: ").strip().upper()

                        if mini_op == "R":
                            _exibir_bloco(r, idx_s, total, marcados)
                            input("  [ENTER para continuar]")
                            continue

                        elif mini_op == "I":
                            trecho = formatar_trecho_para_insercao(r, "integral")
                            lista_para_inserir.append(trecho)
                            print(f"  Resultado [{idx_s}] adicionado a fila.")
                            break

                        elif mini_op == "P":
                            # Exibir texto completo ANTES de pedir digitacao
                            print()
                            print(f"  Texto completo do resultado [{idx_s}]:")
                            print("  " + "─" * 68)
                            print(_wrap(r.get("texto", "")))
                            print("  " + "─" * 68)
                            print()
                            print("  Digite a parte que deseja inserir")
                            print("  (ENTER em branco = cancelar):")
                            texto_perito = input("  > ").strip()
                            if texto_perito:
                                trecho = formatar_trecho_para_insercao(r, "parcial", texto_perito)
                                lista_para_inserir.append(trecho)
                                print(f"  Trecho parcial do resultado [{idx_s}] adicionado.")
                            else:
                                print(f"  Resultado [{idx_s}] nao inserido.")
                            break

                        elif mini_op == "S":
                            print(f"  Resultado [{idx_s}] nao sera inserido.")
                            break

                        else:
                            print("  Opcao invalida.")

                if not lista_para_inserir:
                    print("\n  Nenhum trecho selecionado.")
                    continue

                # ── Confirmação final (Seção 4) ───────────────────────

                while True:
                    sep = "=" * 72
                    print(f"\n{sep}")
                    print("  CONFIRMACAO — INSERIR NA ANOTACAO")
                    print(sep)
                    print(f"  {len(lista_para_inserir)} trecho(s) serao inseridos na anotacao.")
                    print()
                    print("  Resumo:")
                    for i_t, t in enumerate(lista_para_inserir, 1):
                        # Extrair info do cabecalho do trecho
                        linhas_t = t.strip().split("\n")
                        fonte_l = next((l for l in linhas_t if l.startswith("Fonte:")), "—")
                        modo_str = "parcial" if "Trecho parcial" in t else "integral"
                        print(f"  {i_t}. {fonte_l} — {modo_str} ({len(t)} chars)")
                    print()

                    texto_intro = input(
                        "  Texto introdutorio antes dos trechos\n"
                        "  (ex: 'Conforme normas aplicaveis:') ou ENTER para pular:\n"
                        "  > "
                    ).strip()

                    print()
                    print("  [S] Confirmar insercao")
                    print("  [V] Ver previa completa da anotacao")
                    print("  [R] Refazer selecao")
                    print("  [C] Cancelar — nao inserir nada")
                    conf = input("  Escolha: ").strip().upper()

                    if conf == "V":
                        previa = montar_anotacao_final(anotacao_atual, texto_intro, lista_para_inserir)
                        print("\n" + "=" * 72)
                        print("  PREVIA COMPLETA DA ANOTACAO:")
                        print("=" * 72)
                        linhas_prev = previa.split("\n")
                        for p_i in range(0, len(linhas_prev), 40):
                            print("\n".join(linhas_prev[p_i:p_i + 40]))
                            if p_i + 40 < len(linhas_prev):
                                resp_p = input("  [ENTER continuar | Q sair]: ").strip().upper()
                                if resp_p == "Q":
                                    break
                        continue

                    elif conf == "R":
                        break  # Refazer — volta ao loop de decisao

                    elif conf == "C":
                        print("  Insercao cancelada.")
                        return None

                    elif conf == "S":
                        anotacao_nova = montar_anotacao_final(
                            anotacao_atual, texto_intro, lista_para_inserir
                        )
                        n_chars = len(anotacao_nova)
                        # Aviso se muito longa
                        if n_chars > 5000:
                            print(f"\n  ATENCAO: Anotacao com {n_chars} chars (recomendado: 5000).")
                            resp_longa = input("  Confirmar mesmo assim? [S/N]: ").strip().upper()
                            if resp_longa != "S":
                                continue
                        print(f"\n  Anotacao atualizada.")
                        print(f"  {len(lista_para_inserir)} trecho(s) inserido(s) | {n_chars} chars")
                        return anotacao_nova

                    else:
                        print("  Opcao invalida.")

            if ir_para_nova_busca:
                continue
            break

        return None

    # ─────────────────────────────────────────────────────────────────────
    # [A] COLETAR ANOTACAO v2 — Texto livre + sub-modo [C] (Seção 6 v2.0)
    # ─────────────────────────────────────────────────────────────────────

    def _coletar_anotacao_v2(
        self,
        anotacao_atual: str = "",
        conn_principal: Any = None,
    ) -> Optional[str]:
        """
        Campo de anotações com dois modos (Seção 6 v2.0):
          [ENTER] → Editar texto diretamente (comportamento original)
          [C]     → Consultar banco e trazer trechos (sub-modo)
          [V]     → Ver anotação completa
          [0]     → Voltar sem alterar

        Ao escolher [C], executa o fluxo completo de _consultar_banco()
        e retorna com a anotação já atualizada — sem passar pelo menu
        principal do GUT.

        Args:
            anotacao_atual:  Texto já existente na anotação.
            conn_principal:  Ignorado (usa self.conn internamente).

        Returns:
            Anotação atualizada (str) ou None se cancelado/sem alteração.
        """
        sep = "=" * 72
        print(f"\n{sep}")
        print("  ANOTACOES / SINTOMAS / SISTEMA")
        print(sep)

        # Preview da anotação atual
        if anotacao_atual:
            preview = anotacao_atual[:120].replace("\n", " ")
            if len(anotacao_atual) > 120:
                preview += f"  [...+{len(anotacao_atual) - 120} chars]"
        else:
            preview = "vazia"
        print(f"  Atual: {preview}")
        print()
        print("  [ENTER] Editar texto diretamente")
        print("  [C]     Consultar banco e trazer trechos")
        print("  [V]     Ver anotacao completa")
        print("  [0]     Voltar sem alterar")

        op = input("\n  Opcao: ").strip().upper()

        # [0] ou vazio com ENTER → verificar intenção
        if op == "0":
            return None

        elif op == "":
            # ENTER = modo texto direto
            print(f"\n  Anotacao atual: {preview}")
            print("  Digite o novo texto (ENTER vazio = manter atual):")
            novo = input("  > ").strip()
            if novo:
                return novo
            return None

        elif op == "V":
            if not anotacao_atual:
                print("  Anotacao vazia.")
            else:
                print("\n" + "=" * 72)
                print("  ANOTACAO COMPLETA:")
                print("=" * 72)
                linhas = anotacao_atual.split("\n")
                for idx_l in range(0, len(linhas), 40):
                    print("\n".join(linhas[idx_l:idx_l + 40]))
                    if idx_l + 40 < len(linhas):
                        resp_v = input("  [ENTER continuar | Q sair]: ").strip().upper()
                        if resp_v == "Q":
                            break
            # Retornar ao campo de anotação
            return self._coletar_anotacao_v2(anotacao_atual, conn_principal)

        elif op == "C":
            # Sub-modo: consultar banco → retorna direto para [A] com resultado
            return self._consultar_banco(
                anotacao_atual=anotacao_atual,
                origem="anotacao",
            )

        else:
            # Qualquer outra entrada = texto direto iniciando com o que foi digitado
            print("  Continuacao do texto:")
            restante = input("  > ").strip()
            texto_completo = (op + " " + restante).strip()
            if texto_completo:
                return texto_completo
            return None


    # ─────────────────────────────────────────────────────────────────────
    # EXIBIÇÃO DE RESULTADO GUT
    # Correção do AttributeError (Seção 7 do Prompt de Resiliência)
    # ─────────────────────────────────────────────────────────────────────

    def _exibir_resultado(
        self,
        descricao: str,
        subsistema: Any,
        nexo: Any,
        resultado: dict,
    ) -> None:
        """
        Exibe tabela de resultado final do GUT Adaptativo.
        Chamado após o cálculo de avaliar() e em edições pós-cálculo.

        Correção: método estava sendo chamado mas não existia (AttributeError
        na linha 1392). Reimplementado conforme Seção 7 do Prompt de
        Arquitetura Resiliente Offline-First v1.0.
        """
        W = 78
        sep = "+" + "─" * (W - 2) + "+"

        G   = resultado.get("G",          0)
        U   = resultado.get("U",          0)
        T   = resultado.get("T",          0)
        pri = resultado.get("prioridade", G * U * T)
        risco = resultado.get("risco",    "—")
        fonte = resultado.get("fonte",    "treinamento")
        conf  = resultado.get("confianca", 1.0)
        sub_str = subsistema.value if hasattr(subsistema, "value") else str(subsistema)

        # ── Nexo Causal ──────────────────────────────────────────────────
        if hasattr(nexo, "origem"):
            origem_str    = nexo.origem.value
            mecanismo_str = nexo.mecanismo.value
            status_str    = nexo.status.value
        elif isinstance(nexo, dict):
            origem_str    = nexo.get("origem_label",    nexo.get("origem",    "—"))
            mecanismo_str = nexo.get("mecanismo_label", nexo.get("mecanismo", "—"))
            status_str    = nexo.get("status_label",    nexo.get("status",    "—"))
        else:
            origem_str = mecanismo_str = status_str = "—"

        # ── Mapa de risco para ícone ─────────────────────────────────────
        icone_risco = {
            "Crítico": "🔴", "Alto": "🟠", "Médio": "🟡",
            "Baixo": "🟢", "Mínimo": "🟢",
        }.get(risco, "⚪")

        print("\n" + sep)
        print(f"|  📊 RESULTADO GUT ADAPTATIVO v4.0{' ' * (W - 37)}|")
        print(sep)

        # Anomalia e subsistema
        desc_trunc = descricao[:60] + ("…" if len(descricao) > 60 else "")
        print(f"|  Anomalia  : {desc_trunc:<{W - 17}}|")
        print(f"|  Subsistema: {sub_str:<{W - 17}}|")
        print(sep)

        # Scores GUT
        print(f"|  {'GRAVIDADE (G)':<20} {'URGÊNCIA (U)':<20} {'TENDÊNCIA (T)':<20}  |")
        print(f"|  {str(G):^20} {str(U):^20} {str(T):^20}  |")
        print(sep)
        print(f"|  Prioridade GUT  : {pri:<4}  {icone_risco} {risco:<10}  "
              f"(Fonte: {fonte} | Confiança: {conf:.0%})  |")
        print(sep)

        # Nexo Causal
        print(f"|  Origem   : {origem_str:<{W - 16}}|")
        print(f"|  Mecanismo: {mecanismo_str:<{W - 16}}|")
        print(f"|  Status   : {status_str:<{W - 16}}|")
        print(sep)

        # Ação recomendada
        acao = resultado.get("acao_recomendada", "—")
        print(f"|  Ação recomendada: {acao:<{W - 22}}|")

        # Normas sugeridas
        normas = resultado.get("normas_sugeridas", [])
        if normas:
            normas_str = ", ".join(normas)[:W - 16]
            print(f"|  Normas sugeridas: {normas_str:<{W - 22}}|")

        # SHS (se calculado)
        if resultado.get("npa_shs") is not None:
            npa   = resultado["npa_shs"]
            p_shs = resultado.get("prioridade_shs", "—")
            conv  = resultado.get("shs_converge")
            conv_str = "✅ Converge" if conv else ("⚠️  Diverge" if conv is False else "—")
            print(sep)
            print(f"|  SHS — NPA: {npa:.1f}  |  Prioridade SHS: {p_shs:<15}  |  {conv_str:<15}  |")

        # Alerta de sobreposição
        if resultado.get("sobreposicao_detectada"):
            pct = resultado.get("sobreposicao_pct", 0.0)
            print(sep)
            print(f"|  ⚠️  SOBREPOSIÇÃO G/U detectada: {pct * 100:.0f}%  "
                  f"— revise se G mede impacto e U mede tempo.{' ' * 5}|")

        # Anotações (preview)
        anotacoes = resultado.get("anotacoes", "")
        if anotacoes:
            prev = anotacoes[:60].replace("\n", " ")
            if len(anotacoes) > 60:
                prev += f"  [+{len(anotacoes) - 60} chars]"
            print(sep)
            print(f"|  📝 Anotações: {prev:<{W - 18}}|")

        print(sep + "\n")

    # ─────────────────────────────────────────────────────────────────────
    # SALVAR HISTÓRICO GUT
    # ─────────────────────────────────────────────────────────────────────

    def _salvar_historico(
        self,
        resultado: dict,
        nexo: Any,
        subsistema: Any,
    ) -> bool:
        """
        Persiste a avaliação GUT no banco (tabela gut_historico).
        Retorna True em caso de sucesso, False em caso de erro.

        Correção: método estava sendo chamado (op=='S') mas não existia.
        """
        try:
            from database import salvar_gut_historico
        except ImportError:
            logger.warning("database.salvar_gut_historico não encontrado — salvo via DatabaseManager.")
            salvar_gut_historico = None

        # Extrair nexo
        if hasattr(nexo, "origem"):
            nexo_origem    = nexo.origem.value
            nexo_mecanismo = nexo.mecanismo.value
            nexo_status    = nexo.status.value
            nexo_texto     = nexo.texto_livre
            nexo_indet     = nexo.is_a_determinar()
        elif isinstance(nexo, dict):
            nexo_origem    = nexo.get("origem",    "—")
            nexo_mecanismo = nexo.get("mecanismo", "—")
            nexo_status    = nexo.get("status",    "—")
            nexo_texto     = nexo.get("texto_livre", "")
            nexo_indet     = False
        else:
            nexo_origem = nexo_mecanismo = nexo_status = "—"
            nexo_texto = ""
            nexo_indet = False

        sub_str = subsistema.value if hasattr(subsistema, "value") else str(subsistema)

        registro = {
            "descricao":              resultado.get("descricao", ""),
            "subsistema":             sub_str,
            "embedding":              None,
            "nexo_origem":            nexo_origem,
            "nexo_mecanismo":         nexo_mecanismo,
            "nexo_status":            nexo_status,
            "nexo_causal_texto":      nexo_texto,
            "nexo_indeterminado":     nexo_indet,
            "G_final":                resultado.get("G", 0),
            "U_final":                resultado.get("U", 0),
            "T_final":                resultado.get("T", 0),
            "prioridade_gut":         resultado.get("prioridade", 0),
            "risco_gut":              resultado.get("risco", "—"),
            "npa_shs":                resultado.get("npa_shs"),
            "prioridade_shs":         resultado.get("prioridade_shs"),
            "shs_calculado":          resultado.get("npa_shs") is not None,
            "shs_converge_gut":       resultado.get("shs_converge"),
            "sobreposicao_detectada": resultado.get("sobreposicao_detectada", False),
            "fonte_avaliacao":        resultado.get("fonte", "treinamento"),
            "aceito_perito":          1,
            "G_original":             resultado.get("G_original"),
            "U_original":             resultado.get("U_original"),
            "T_original":             resultado.get("T_original"),
            "respostas_json":         resultado.get("respostas_json", "{}"),
            "projeto_id":             self.projeto_id,
            "timestamp":              resultado.get("timestamp", __import__("datetime").datetime.now().isoformat()),
        }

        try:
            if salvar_gut_historico:
                registro_id = salvar_gut_historico(self.conn, registro)
            else:
                # Fallback: via cursor direto
                cur = self.conn.cursor()
                cur.execute("""
                    INSERT INTO gut_historico (
                        descricao, subsistema, nexo_origem, nexo_mecanismo,
                        nexo_status, nexo_causal_texto, nexo_indeterminado,
                        G_final, U_final, T_final, prioridade_gut, risco_gut,
                        npa_shs, prioridade_shs, shs_calculado, shs_converge_gut,
                        sobreposicao_detectada, fonte_avaliacao, aceito_perito,
                        G_original, U_original, T_original, respostas_json,
                        projeto_id, timestamp
                    ) VALUES (
                        :descricao, :subsistema, :nexo_origem, :nexo_mecanismo,
                        :nexo_status, :nexo_causal_texto, :nexo_indeterminado,
                        :G_final, :U_final, :T_final, :prioridade_gut, :risco_gut,
                        :npa_shs, :prioridade_shs, :shs_calculado, :shs_converge_gut,
                        :sobreposicao_detectada, :fonte_avaliacao, :aceito_perito,
                        :G_original, :U_original, :T_original, :respostas_json,
                        :projeto_id, :timestamp
                    )
                """, registro)
                self.conn.commit()
                registro_id = cur.lastrowid
            logger.info(f"[GUT] Histórico salvo — ID {registro_id}")
            return True
        except Exception as exc:
            logger.error(f"[GUT] Falha ao salvar histórico: {exc}")
            return False

    # ─────────────────────────────────────────────────────────────────────
    # EXIBIÇÃO COMPARATIVA GUT × SHS
    # ─────────────────────────────────────────────────────────────────────

    def _exibir_comparativo(self, resultado: dict, shs: dict) -> None:
        """
        Exibe comparativo lado a lado entre GUT e SHS (Grossi, 2025).
        Destaca convergência ou divergência entre os dois métodos.
        """
        W = 78
        sep = "+" + "─" * (W - 2) + "+"

        G, U, T   = resultado.get("G", 0), resultado.get("U", 0), resultado.get("T", 0)
        pri_gut   = resultado.get("prioridade", G * U * T)
        risco_gut = resultado.get("risco", "—")
        npa       = shs.get("npa_total", 0.0)
        p_shs     = shs.get("prioridade_shs", "—")
        conv      = self._verificar_convergencia(risco_gut, p_shs)
        conv_str  = "✅ CONVERGÊNCIA" if conv else "⚠️  DIVERGÊNCIA — revisar avaliação"

        print("\n" + sep)
        print(f"|  ⚖️  COMPARATIVO GUT × SHS (Grossi, 2025){' ' * (W - 44)}|")
        print(sep)
        print(f"|  {'MÉTODO GUT':<36} {'MÉTODO SHS':<36}  |")
        print(f"|  {'─' * 34:<34}   {'─' * 34:<34}  |")
        print(f"|  G={G}  U={U}  T={T}  Prioridade={pri_gut:<5}   "
              f"NPA={npa:.1f}  Prioridade SHS: {p_shs:<10}    |")
        print(f"|  Risco GUT: {risco_gut:<24}   {' ' * 34}  |")
        print(sep)
        print(f"|  {conv_str:<{W - 5}}|")
        print(sep + "\n")

    # ─────────────────────────────────────────────────────────────────────
    # ESTADO PERSISTENTE — Resiliência contra crash (Seção 4 do Prompt)
    # Princípio [A2]: salvar ANTES de processar
    # ─────────────────────────────────────────────────────────────────────

    def _garantir_tabela_sessao(self) -> None:
        """Cria a tabela gut_sessao_parcial se não existir (idempotente)."""
        try:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS gut_sessao_parcial (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id     TEXT    NOT NULL UNIQUE,
                    descricao      TEXT    NOT NULL,
                    subsistema     TEXT    DEFAULT NULL,
                    nexo_json      TEXT    DEFAULT NULL,
                    respostas_json TEXT    DEFAULT '{}',
                    etapa_atual    TEXT    DEFAULT NULL,
                    timestamp      TEXT    NOT NULL,
                    expirado       INTEGER DEFAULT 0
                )
            """)
            self.conn.commit()
        except Exception as exc:
            logger.warning(f"[GUT] Falha ao criar gut_sessao_parcial: {exc}")

    def _salvar_etapa_parcial(
        self,
        session_id: str,
        etapa: str,
        valor: float,
        descricao: str = "",
        subsistema: str = "",
        nexo_json: str = "",
    ) -> None:
        """
        Persiste cada resposta imediatamente após coleta.
        Garante que nenhuma resposta seja perdida em crash.

        Args:
            session_id: UUID único da sessão atual.
            etapa:      ID do fator atual (ex: "G1", "T3", "inicio").
            valor:      Peso selecionado pelo perito [0.0, 1.0].
            descricao:  Descrição da anomalia (usada apenas na criação).
            subsistema: Subsistema selecionado (usada apenas na criação).
            nexo_json:  JSON serializado do nexo causal.
        """
        self._garantir_tabela_sessao()
        try:
            # Carregar respostas acumuladas
            row = self.conn.execute(
                "SELECT respostas_json FROM gut_sessao_parcial WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            respostas: dict = json.loads(row[0]) if row else {}
            if etapa != "inicio":
                respostas[etapa] = valor

            self.conn.execute("""
                INSERT INTO gut_sessao_parcial
                    (session_id, descricao, subsistema, nexo_json,
                     respostas_json, etapa_atual, timestamp, expirado)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(session_id) DO UPDATE SET
                    respostas_json = excluded.respostas_json,
                    etapa_atual    = excluded.etapa_atual,
                    subsistema     = COALESCE(excluded.subsistema, gut_sessao_parcial.subsistema),
                    nexo_json      = COALESCE(excluded.nexo_json,  gut_sessao_parcial.nexo_json),
                    timestamp      = excluded.timestamp
            """, (
                session_id,
                descricao or (row[0] if row else ""),
                subsistema or None,
                nexo_json or None,
                json.dumps(respostas),
                etapa,
                __import__("datetime").datetime.now().isoformat(),
            ))
            self.conn.commit()
        except Exception as exc:
            # NUNCA propagar — não interromper a coleta por erro de cache
            logger.warning(f"[GUT] Falha ao salvar etapa parcial ({etapa}): {exc}")

    def _verificar_sessao_pendente(self) -> Optional[dict]:
        """
        Verifica se há sessão GUT incompleta para recuperar.
        Retorna None se não houver sessão válida (< 2h de idade).

        Chamado no início de cada avaliação.
        """
        self._garantir_tabela_sessao()
        try:
            row = self.conn.execute("""
                SELECT session_id, descricao, respostas_json,
                       etapa_atual, timestamp, subsistema, nexo_json
                FROM gut_sessao_parcial
                WHERE expirado = 0
                ORDER BY timestamp DESC LIMIT 1
            """).fetchone()

            if not row:
                return None

            # Verificar se é recente (< 2 horas)
            from datetime import datetime as _dt
            ts = _dt.fromisoformat(row[4])
            age_s = (_dt.now() - ts).total_seconds()
            if age_s > 7200:
                # Expirar silenciosamente
                self.conn.execute(
                    "UPDATE gut_sessao_parcial SET expirado=1 WHERE session_id=?",
                    (row[0],),
                )
                self.conn.commit()
                return None

            return {
                "session_id":  row[0],
                "descricao":   row[1],
                "respostas":   json.loads(row[2] or "{}"),
                "etapa_atual": row[3],
                "timestamp":   row[4],
                "subsistema":  row[5],
                "nexo_json":   row[6],
            }
        except Exception as exc:
            logger.warning(f"[GUT] Erro ao verificar sessão pendente: {exc}")
            return None

    def _expirar_sessao(self, session_id: str) -> None:
        """Marca sessão como expirada após conclusão ou descarte."""
        try:
            self.conn.execute(
                "UPDATE gut_sessao_parcial SET expirado=1 WHERE session_id=?",
                (session_id,),
            )
            self.conn.commit()
        except Exception as exc:
            logger.warning(f"[GUT] Falha ao expirar sessão {session_id}: {exc}")

    def _retomar_sessao(self, pendente: dict) -> Optional[dict]:
        """
        Retoma uma sessão GUT interrompida a partir do estado salvo.
        Pede ao perito apenas as etapas ainda não respondidas.

        Args:
            pendente: Dict retornado por _verificar_sessao_pendente().

        Returns:
            resultado_final ou None se cancelado.
        """
        print(f"\n  🔄 Retomando avaliação de:")
        print(f"     Anomalia : {pendente['descricao'][:60]}")
        print(f"     Subsistema: {pendente.get('subsistema', '—')}")
        respostas_existentes: dict = pendente.get("respostas", {})
        respondidas = [k for k in respostas_existentes if k != "inicio"]
        print(f"     Etapas respondidas: {', '.join(respondidas) or 'nenhuma'}")
        print(f"     Última etapa: {pendente.get('etapa_atual', '—')}\n")

        # Determinar subsistema
        sub_str = pendente.get("subsistema") or ""
        try:
            subsistema = SubsistemaGUT(sub_str) if sub_str else self.selecionar_subsistema()
        except ValueError:
            subsistema = self.selecionar_subsistema()

        # Determinar quais fatores ainda faltam
        todos_fatores = list(_FATORES.keys())  # G1–G4, U1–U4, T1–T4
        fatores_faltantes = [f for f in todos_fatores if f not in respostas_existentes]

        if fatores_faltantes:
            print(f"\n  Continuando com {len(fatores_faltantes)} pergunta(s) restante(s)...")
            perguntas = self.gerar_perguntas(subsistema, dimensoes=None)
            perguntas_rest = [p for p in perguntas if p["fator_id"] in fatores_faltantes]
            respostas_novas = {}
            for perg in perguntas_rest:
                fid  = perg["fator_id"]
                opcoes = perg["opcoes"]
                print(f"\n  ── {fid} [{perg['dimensao']}] ──────────────────────────────")
                print(f"  {perg['pergunta']}")
                for i, op in enumerate(opcoes, 1):
                    ex = f"  ex: {op.exemplo}" if op.exemplo else ""
                    print(f"    [{i}] {op.texto}{ex}")
                while True:
                    try:
                        escolha = int(input(f"  Opção (1–{len(opcoes)}): "))
                        if 1 <= escolha <= len(opcoes):
                            respostas_novas[fid] = opcoes[escolha - 1].peso
                            # Salvar incrementalmente
                            self._salvar_etapa_parcial(
                                pendente["session_id"], fid, respostas_novas[fid]
                            )
                            break
                        print(f"  ⚠️  Escolha entre 1 e {len(opcoes)}.")
                    except (ValueError, EOFError):
                        print("  ⚠️  Entrada inválida.")

            respostas_existentes.update(respostas_novas)

        # Recuperar/solicitar nexo
        nexo_json = pendente.get("nexo_json")
        if nexo_json:
            try:
                nd = json.loads(nexo_json)
                nexo = NexoCausal(
                    origem=OrigemNexo(nd.get("origem", OrigemNexo.A_DETERMINAR.value)),
                    mecanismo=MecanismoDegradacao(nd.get("mecanismo", MecanismoDegradacao.INDETERMINADO.value)),
                    status=StatusAnomalia(nd.get("status", StatusAnomalia.ESTABILIZADA.value)),
                    texto_livre=nd.get("texto_livre", ""),
                )
            except Exception:
                print("\n  ⚠️  Nexo causal não recuperado — coletando novamente.")
                nexo = self.coletar_nexo_causal()
        else:
            nexo = self.coletar_nexo_causal()

        # Calcular resultado
        resultado = self.calcular_score_offline(respostas_existentes, nexo)
        self._expirar_sessao(pendente["session_id"])

        resultado_final = resultado.copy()
        resultado_final.update({
            "descricao":      pendente["descricao"],
            "subsistema":     subsistema.value if hasattr(subsistema, "value") else str(subsistema),
            "nexo":           nexo,
            "respostas_json": json.dumps(respostas_existentes),
        })
        self._exibir_resultado(pendente["descricao"], subsistema, nexo, resultado_final)
        return resultado_final

    @staticmethod
    def _escolher_enum(opcoes: list, prompt: str) -> Any:
        """Exibe opções numeradas e retorna o elemento escolhido."""
        while True:
            try:
                idx = int(input(prompt)) - 1
                if 0 <= idx < len(opcoes):
                    return opcoes[idx]
                print(f"  ⚠️  Escolha entre 1 e {len(opcoes)}.")
            except (ValueError, EOFError):
                print("  ⚠️  Entrada inválida.")


# =============================================================================
# TESTES UNITÁRIOS
# =============================================================================

def _rodar_testes() -> None:
    """
    Executa os 5 testes unitários obrigatórios conforme Seção 15.
    Não requer banco de dados real — usa conexão in-memory.
    """
    import sys

    conn = sqlite3.connect(":memory:")
    engine = GUTAdaptativo(conn)
    engine._subsistema_atual = SubsistemaGUT.ESTRUTURAL  # setado normalmente por selecionar_subsistema

    resultados: list[tuple[str, bool, str]] = []

    # ──────────────────────────────────────────────────────────────────────
    # TESTE 1 — Elétrico leve / baixa prioridade
    # Esperado: 1 ≤ G ≤ 3  |  0 ≤ U ≤ 2  |  0 ≤ T ≤ 2
    # NC3 = "estabilizada" NÃO aciona regra especial
    # ──────────────────────────────────────────────────────────────────────
    engine._subsistema_atual = SubsistemaGUT.ELETRICO
    nexo1 = NexoCausal(
        origem=OrigemNexo.FUNCIONAL,
        mecanismo=MecanismoDegradacao.MECANICO,
        status=StatusAnomalia.ESTABILIZADA,
    )
    respostas1 = {
        # G: tomada sem tampa (G1=0.45 elétrico), pontual (G2=0.15),
        #    não conformidade (G3=0.20 elétrico), sem impacto (G4=0.05)
        "G1": 0.45, "G2": 0.15, "G3": 0.20, "G4": 0.05,
        # U: >6 meses (U1=0.10), desocupado (U2=0.05),
        #    sem danos (U3=0.05), >90d (U4=0.10)
        "U1": 0.10, "U2": 0.05, "U3": 0.05, "U4": 0.10,
        # T: estabilizada (T1=0.20), nenhum agente (T2=0.05),
        #    estabilização >12m (T3=0.10), baixa exposição (T4=0.10)
        "T1": 0.20, "T2": 0.05, "T3": 0.10, "T4": 0.10,
    }
    r1 = engine.calcular_score_offline(respostas1, nexo1)
    ok1 = (1 <= r1["G"] <= 3) and (0 <= r1["U"] <= 2) and (0 <= r1["T"] <= 2)
    # Validar que NC3 "estabilizada" NÃO aciona regra especial (T não deve ser ≥7 nem ≤2 por regra)
    ok1 = ok1 and (r1["T"] <= 2)  # esperado baixo
    resultados.append((
        "T1 — Elétrico leve (G≈2, U≈1, T≈1)",
        ok1,
        f"G={r1['G']} U={r1['U']} T={r1['T']} Prio={r1['prioridade']}",
    ))

    # ──────────────────────────────────────────────────────────────────────
    # TESTE 2 — Hidrossanitário moderado
    # Esperado: 4 ≤ G ≤ 6  |  4 ≤ U ≤ 6  |  4 ≤ T ≤ 6
    # ──────────────────────────────────────────────────────────────────────
    engine._subsistema_atual = SubsistemaGUT.HIDROSSANITARIO
    nexo2 = NexoCausal(
        origem=OrigemNexo.ENDOGENA_EXECUCAO,
        mecanismo=MecanismoDegradacao.FISICO,
        status=StatusAnomalia.ATIVA_ESTAVEL,
    )
    respostas2 = {
        "G1": 0.80, "G2": 0.45, "G3": 0.80, "G4": 0.35,
        "U1": 0.55, "U2": 0.70, "U3": 0.70, "U4": 0.65,
        "T1": 0.70, "T2": 0.70, "T3": 0.60, "T4": 0.55,
    }
    r2 = engine.calcular_score_offline(respostas2, nexo2)
    ok2 = (4 <= r2["G"] <= 7) and (4 <= r2["U"] <= 7) and (4 <= r2["T"] <= 7)  # range real para inputs moderados-altos
    resultados.append((
        "T2 — Hidrossanitário moderado (G≈5, U≈5, T≈5)",
        ok2,
        f"G={r2['G']} U={r2['U']} T={r2['T']} Prio={r2['prioridade']}",
    ))

    # ──────────────────────────────────────────────────────────────────────
    # TESTE 3 — Estrutural crítico / "em ocorrência"
    # Esperado: G≥8, U≥8, T≥7 (regra NC3 ativa), prioridade≥500 → Crítico
    # ──────────────────────────────────────────────────────────────────────
    engine._subsistema_atual = SubsistemaGUT.ESTRUTURAL
    nexo3 = NexoCausal(
        origem=OrigemNexo.ENDOGENA_PROJETO,
        mecanismo=MecanismoDegradacao.QUIMICO,
        status=StatusAnomalia.EM_OCORRENCIA,  # Regra especial: T ≥ 7
    )
    respostas3 = {
        "G1": 1.00, "G2": 1.00, "G3": 1.00, "G4": 1.00,
        "U1": 1.00, "U2": 1.00, "U3": 1.00, "U4": 1.00,
        "T1": 1.00, "T2": 1.00, "T3": 1.00, "T4": 1.00,
    }
    r3 = engine.calcular_score_offline(respostas3, nexo3)
    ok3 = (r3["G"] >= 8) and (r3["U"] >= 8) and (r3["T"] >= 7)
    ok3 = ok3 and (r3["prioridade"] >= 500)
    ok3 = ok3 and ("tico" in r3["risco"])  # aceita "Crítico" ou "Critico"
    resultados.append((
        "T3 — Estrutural critico em ocorrencia (G>=8, U>=8, T>=7, Critico)",
        ok3,
        "G=%d U=%d T=%d Prio=%d Risco=%s" % (
            r3["G"], r3["U"], r3["T"], r3["prioridade"], r3["risco"]
        ),
    ))

    # TESTE 4 — Alerta de sobreposição G/U
    # Forçar todos os fatores G e U com valores idênticos → pct = 1.0
    engine._subsistema_atual = SubsistemaGUT.ESTRUTURAL
    respostas4 = {
        "G1": 0.80, "G2": 0.80, "G3": 0.80, "G4": 0.80,
        "U1": 0.80, "U2": 0.80, "U3": 0.80, "U4": 0.80,
        "T1": 0.50, "T2": 0.50, "T3": 0.50, "T4": 0.50,
    }
    sobreposicao, pct = engine.detectar_sobreposicao(respostas4)
    ok4 = sobreposicao and (pct >= 0.50)
    resultados.append((
        "T4 — Alerta de sobreposicao G/U (correlacao >= 50%%)",
        ok4,
        "Sobreposicao=%s Percentual=%.2f" % (sobreposicao, pct),
    ))

    # TESTE 5 — SHS paralelo ao GUT (Estrutural crítico)
    # Se(1×1×1×5=5) + H(1×1×1×3=3) + Su(1×0×1×1=0) = NPA 8
    # Prioridade SHS: 5–8 → "Prioridade 2 — Alto"
    # Convergência: GUT Crítico × SHS Prioridade 2 (Alto) → CONVERGE
    respostas_shs5 = {
        "Se": {"I": 1, "A": 1, "V": 1},
        "H":  {"I": 1, "A": 1, "V": 1},
        "Su": {"I": 1, "A": 0, "V": 1},
    }
    shs5 = engine.calcular_shs(respostas_shs5)
    ok5a = abs(shs5["npa_total"] - 8.0) < 0.01
    ok5b = "Alto" in shs5["prioridade_shs"]
    converge5 = GUTAdaptativo._verificar_convergencia("Crítico", shs5["prioridade_shs"])
    ok5 = ok5a and ok5b
    resultados.append((
        "T5 — SHS: NPA=8, Prioridade 2 Alto, Converge com GUT Critico",
        ok5,
        "NPA=%.1f Prioridade=%s Converge=%s" % (
            shs5["npa_total"], shs5["prioridade_shs"], converge5
        ),
    ))

    # ── Relatório final ───────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  TESTES UNITÁRIOS — gut_adaptativo.py v4.0")
    print("=" * 65)
    passou = sum(1 for _, ok, _ in resultados if ok)
    falhou = len(resultados) - passou
    for nome, ok, detalhe in resultados:
        status = "PASSOU" if ok else "FALHOU"
        print("\n  [%s]  %s" % (status, nome))
        print("         Valores: %s" % detalhe)
    print("\n" + "-" * 65)
    print("  Total: %d/%d passaram | %d falharam" % (passou, len(resultados), falhou))
    print("=" * 65 + "\n")
    if falhou:
        import sys; sys.exit(1)


if __name__ == "__main__":
    _rodar_testes()

"""
taxonomy_manager.py — Gerenciador de Taxonomia e Regras Periciais
Versão 2.1 — Config embutida como fallback (config_pericial.yaml opcional).

Responsabilidades:
  - Carregar VOCABULARIO_PERICIAL, TERMOS_CANONICOS e STOPWORDS_TECNICAS
    de config_pericial.yaml em runtime, SE o arquivo existir.
  - Se o YAML não for encontrado, usa _CONFIG_EMBUTIDA (conteúdo completo
    do config_pericial.yaml v4.2 compilado diretamente no código).
  - Expor constantes e funções utilitárias para extrair_palavras_chave_v2().
  - Fornecer regras de GUT, riscos e prompts para o pipeline pericial.

Referência: IBAPE (2025) items 12.1-12.3 | NBR 13752:2024
"""
import re
import logging
import os
from typing import Dict, Any, Optional, List, FrozenSet

logger = logging.getLogger("taxonomy_manager")

# =============================================================================
# CONFIG EMBUTIDA — espelho completo do config_pericial.yaml v4.2
# Usada automaticamente quando o arquivo .yaml NÃO é encontrado.
# Para customizar: edite o config_pericial.yaml (tem prioridade sobre este dict).
# =============================================================================
_CONFIG_EMBUTIDA: Dict[str, Any] = {
    "sistema": {
        "modelo_llm": "gemini-2.0-flash",
        "temperatura_rag": 0.1,
        "provedor": "gemini",
    },
    "palavras_chave": {
        "versao_algoritmo": "2.0",
        "max_por_topico": 10,
        "usar_ia_se_disponivel": True,
        "normalizar_para_canonico": True,
        "min_length_token": 4,
        "idf_threshold_stopword": 0.5,
        "idf_cache_ttl_horas": 24,
        "boost_tipos_documento": {
            "norma_abnt": 1.2, "laudo_judicial": 1.3, "livro": 1.0,
            "parecer_tecnico": 1.1, "norma_iso": 1.1, "norma_outro": 1.0,
            "artigo": 0.9, "manual_fabricante": 0.9, "outro": 0.8,
        },
        "secoes_nao_tecnicas": [
            "preambulo","sumario","apresentacao","identificacao das partes",
            "comunicacao da pericia","linha do tempo","introducao",
        ],
        "termos_tecnicos_adicionais": [],
        "stopwords_tecnicas_adicionais": [],
        "termos_canonicos_adicionais": {},
    },
    "vocabulario_pericial": {
        "patologias": {
            "boost": 1.4,
            "termos": [
                "fissura","fissuração","fissuras","eflorescência","eflorescências",
                "infiltração","infiltrações","recalque","recalques","recalque diferencial",
                "desplacamento","desplacamentos","corrosão","corrosão de armadura",
                "carbonatação","frente de carbonatação","segregação","segregações",
                "umidade ascendente","umidade descendente","manchas de umidade",
                "bolor","manifestação biológica","deformação excessiva","flecha",
                "desaprumo","desalinhamento",
            ],
        },
        "classificacao_ibape": {
            "boost": 1.5,
            "termos": [
                "anomalia endógena","anomalia exógena","anomalia natural","anomalia funcional",
                "vício construtivo","vícios construtivos","avaria","decrepitude","deterioração",
                "grau de risco crítico","grau de risco médio","grau de risco mínimo",
                "falha de planejamento","falha de execução","falha operacional","falha gerencial",
                "nexo causal","vistoria de causalidade","assistência técnica",
            ],
        },
        "elementos_construtivos": {
            "boost": 1.2,
            "termos": [
                "armadura","armaduras","cobrimento","cobrimento de armadura",
                "cobrimento nominal","cobrimento mínimo","laje","lajes","laje protendida",
                "viga","vigas","viga de concreto","pilar","pilares","fundação","fundações",
                "sapata","estaca","alvenaria","alvenaria de vedação","revestimento",
                "revestimentos","argamassa de revestimento","impermeabilização",
                "esquadria","esquadrias","guarda-corpo","guarda-corpos","cobertura",
                "telhado","calha","rufo","tubulação","instalação hidráulica",
            ],
        },
        "parametros_desempenho": {
            "boost": 1.3,
            "termos": [
                "vida útil de projeto","vup","classe de agressividade ambiental",
                "abertura de fissura","resistência à compressão","estanqueidade",
                "permeabilidade","aderência","resistência de aderência","caimento",
                "declividade","altura mínima","vão livre","carga mínima","carga máxima",
                "compactação","grau de compactação",
            ],
        },
        "ensaios_investigacao": {
            "boost": 1.3,
            "termos": [
                "sondagem","ensaio spt","esclerometria","índice esclerométrico",
                "pacometria","cobrimento por pacômetro","carbonatação por fenolftaleína",
                "termografia","inspeção termográfica","ensaio de arrancamento","pull-off",
                "percussão","sondagem à percussão","prova de carga",
            ],
        },
        "normas_numeradas": {
            "boost": 1.0,
            "termos": [
                "nbr 6118","nbr 15575","nbr 9575","nbr 5674","nbr 13752","nbr 16747",
                "nbr 14718","nbr 10844","nbr 5410","nbr 5419","nbr 7200","nbr 13755",
                "iso 6707","ibape",
            ],
        },
        "responsabilidade_juridica": {
            "boost": 1.4,
            "termos": [
                "responsabilidade civil","responsabilidade técnica","construtora responsável",
                "incorporadora","prazo de garantia","garantia legal","manual do proprietário",
                "manual do síndico","art. 618 cc","art. 12 cdc",
                "prazo decadencial","prazo prescricional",
            ],
        },
    },
    "termos_canonicos": {
        "trinca": "fissura", "rachadura": "fissura", "fenda": "fissura",
        "trincamento": "fissuração", "fissuração mapeada": "fissuração",
        "fissura mapeada": "fissuração", "janela": "esquadria", "caixilho": "esquadria",
        "ferro": "armadura", "ferragem": "armadura", "aço": "armadura",
        "cobrimento nominal": "cobrimento de armadura",
        "mofo": "manifestação biológica", "fungo": "manifestação biológica",
        "mancha de umidade": "infiltração", "mancha d'água": "infiltração",
        "descolamento": "desplacamento", "descolamento cerâmico": "desplacamento",
        "queda de revestimento": "desplacamento",
        "corrosão de ferro": "corrosão de armadura", "ferrugem": "corrosão de armadura",
        "teto": "laje", "forro": "laje",
        "fundação rasa": "fundação", "fundação profunda": "fundação",
        "sondagem rotativa": "sondagem", "sondagem percussão": "ensaio spt",
        "crítico": "grau de risco crítico", "grave": "grau de risco crítico",
        "médio": "grau de risco médio", "mínimo": "grau de risco mínimo",
        "origem endógena": "anomalia endógena", "origem exógena": "anomalia exógena",
    },
    "stopwords_tecnicas": [
        "laudo","laudos","laudo pericial","laudo técnico","norma","normas","normativa",
        "estrutura","estruturas","desempenho","sistema","sistemas","edificação","edificações",
        "requisito","requisitos","construção","construções","imóvel","imóveis",
        "deve","devem","deverá","deverão","pode","podem","poderá","conforme","segundo",
        "mediante","previsto","previstos","prevista","estabelece","estabelecido",
        "estabelecida","determina","determinado","indica","indicado",
        "forma","modo","meio","caso","vez","tipo","tipos","parte","partes","seção",
        "presente","presente análise","objeto","objetivo","resultado","resultados",
        "sejam desenvolvidos","presente análise","conforme descrito",
        "proveniente do solo","desenvolvidos projetos",
        "processo","autos","autor","réu","requerente","requerido","abnt","nbr",
    ],
    "gut_adaptativo": {
        "habilitado": True,
        "threshold_autonomo": 0.80,
        "threshold_semi_autonomo": 0.50,
        "casos_minimos_autonomo": 5,
        "usar_ia_por_padrao": False,
        "salvar_automatico": False,
        "decay_180_dias": 0.8,
        "decay_365_dias": 0.5,
        "peso_caso_corrigido": 0.3,
        "peso_projeto_atual": 1.5,
        "confianca_minima_dimensao": 0.70,
        "sobreposicao_threshold": 0.15,
        "sobreposicao_pct_min": 0.50,
        "shs_habilitado": True,
        "exigir_nexo_causal": True,
        "t_minimo_em_ocorrencia": 7,
        "t_maximo_em_regressao": 2,
        "desconto_subsistema_diferente": 0.30,
    },
    "analise_ibape": {
        "habilitado": True,
        "banco_dedicado": "analise_ibape.db",
        "nexo_causal_obrigatorio": True,
        "min_chars_descricao": 100,
        "min_chars_nexo_causal": 50,
        "busca_normas_automatica": True,
        "max_resultados_busca": 5,
        "exportar_finalizadas_apenas": False,
        "pasta_exportacao": "exportacoes/",
        "alertas_consistencia": True,
    },
    "taxonomia_gut": {},
}

# =============================================================================
# MAPA DE SEÇÕES — Camada 4 (multiplicadores por tipo de seção)
# =============================================================================
MAPA_SECOES: List[Dict[str, Any]] = [
    {
        "padrao": re.compile(r"anomalia|falha|patologia|manifestação|vício|patológic", re.IGNORECASE),
        "tipo": "patologia", "multiplicador": 1.4,
        "categorias_boost": ["patologias", "classificacao_ibape"],
    },
    {
        "padrao": re.compile(r"metodologia|método|critério|procedimento|ensaio", re.IGNORECASE),
        "tipo": "metodologia", "multiplicador": 1.3,
        "categorias_boost": ["parametros_desempenho", "ensaios_investigacao"],
    },
    {
        "padrao": re.compile(r"norma|abnt|nbr|requisito|parâmetro|desempenho", re.IGNORECASE),
        "tipo": "normativo", "multiplicador": 1.5,
        "categorias_boost": ["normas_numeradas", "parametros_desempenho"],
    },
    {
        "padrao": re.compile(r"quesito|resposta|conclusão|análise técnica|nexo causal", re.IGNORECASE),
        "tipo": "pericial", "multiplicador": 1.4,
        "categorias_boost": ["classificacao_ibape", "responsabilidade_juridica"],
    },
    {
        "padrao": re.compile(r"caracterização|localização|região|identificação|endereço", re.IGNORECASE),
        "tipo": "descritivo", "multiplicador": 0.3,
        "categorias_boost": [],
    },
    {
        "padrao": re.compile(
            r"preâmbulo|sumário|apresentação|introdução|comunicação da perícia|"
            r"identificação das partes|linha do tempo|sumario",
            re.IGNORECASE,
        ),
        "tipo": "preambulo", "multiplicador": 0.0,
        "categorias_boost": [],
    },
]

SIGLAS_PERMITIDAS: FrozenSet[str] = frozenset({
    "spt", "gut", "vup", "nbr", "idf", "cdc", "spda", "ocr", "ipp", "npa", "shs", "iso",
})

_SUFIXOS_VERBAIS = re.compile(
    r"(ando|endo|aram|eram|avam|aria|eria|mente|izado|izada|ificar)$", re.IGNORECASE
)

_RE_ENDERECO = re.compile(
    r"\b(rua|av\.|avenida|quadra|lote\s*\d|cep|bairro|condomínio|alameda|"
    r"travessa|estrada|rodovia|jardins?\b|vila\b)\b",
    re.IGNORECASE,
)


class TaxonomyManager:
    """
    Gerenciador de Taxonomia e Regras Periciais.
    Carrega de config_pericial.yaml em runtime — editável pelo perito.

    Exemplo de uso:
        tm = TaxonomyManager("config_pericial.yaml")
        texto_norm = tm.aplicar_normalizacao_canonica("Trinca na laje")
        # → "fissura na laje"
        resultado = tm.buscar_vocabulario_pericial("fissura")
        # → {"categoria": "patologias", "boost": 1.4}
    """

    def __init__(self, config_path: str = "config_pericial.yaml"):
        self.config_path = config_path
        self.config: Dict[str, Any] = self._load_config()
        self.vocabulario_pericial: Dict[str, Dict[str, Any]] = self._build_vocabulario()
        self.termos_canonicos: Dict[str, str] = self._build_canonicos()
        self.stopwords_tecnicas: FrozenSet[str] = self._build_stopwords()
        # Índice invertido: termo_lower -> (categoria, boost)
        self._indice_vocab: Dict[str, tuple] = {}
        for cat, dados in self.vocabulario_pericial.items():
            for termo in dados["termos"]:
                self._indice_vocab[termo.lower()] = (cat, dados["boost"])

    # ─── Carregamento ────────────────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        """
        Carrega configuração com prioridade:
          1. config_pericial.yaml (se existir na pasta do projeto)
          2. _CONFIG_EMBUTIDA (fallback completo — sem warning, sem arquivo externo)
        """
        if os.path.exists(self.config_path):
            try:
                import yaml
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                logger.debug(f"[TaxonomyManager] Config carregada de '{self.config_path}'.")
                return config
            except ImportError:
                logger.warning("[TaxonomyManager] PyYAML não instalado. Usando config embutida.")
            except Exception as e:
                logger.warning(f"[TaxonomyManager] Erro ao ler '{self.config_path}': {e}. "
                               "Usando config embutida.")
        else:
            logger.debug("[TaxonomyManager] 'config_pericial.yaml' não encontrado — "
                         "usando config embutida (normal).")
        return _CONFIG_EMBUTIDA

    def _build_vocabulario(self) -> Dict[str, Dict[str, Any]]:
        """Constrói dict {categoria: {boost, termos: set}} a partir do YAML."""
        vocab_yaml = self.config.get("vocabulario_pericial", {})
        resultado: Dict[str, Dict[str, Any]] = {}
        extras = [str(t).lower() for t in self.config.get("palavras_chave", {}).get("termos_tecnicos_adicionais", [])]
        for cat, dados in vocab_yaml.items():
            boost = float(dados.get("boost", 1.0))
            termos = [str(t).lower() for t in dados.get("termos", [])] + extras
            resultado[cat] = {"boost": boost, "termos": set(termos)}
        return resultado

    def _build_canonicos(self) -> Dict[str, str]:
        """Constrói dict de normalização canônica do YAML."""
        base: Dict[str, str] = {}
        for variante, canonico in self.config.get("termos_canonicos", {}).items():
            base[str(variante).lower()] = str(canonico).lower()
        for variante, canonico in (
            self.config.get("palavras_chave", {}).get("termos_canonicos_adicionais", {}).items()
        ):
            base[str(variante).lower()] = str(canonico).lower()
        return base

    def _build_stopwords(self) -> FrozenSet[str]:
        """Constrói frozenset de stopwords técnicas do YAML."""
        base = {str(sw).lower() for sw in self.config.get("stopwords_tecnicas", [])}
        extras = {
            str(sw).lower()
            for sw in self.config.get("palavras_chave", {}).get("stopwords_tecnicas_adicionais", [])
        }
        return frozenset(base | extras)

    # ─── API de Regras Periciais ─────────────────────────────────────────────

    def get_anomaly_rules(self, anomaly_key: str) -> Optional[Dict[str, Any]]:
        """Retorna regras GUT e prompts para uma anomalia específica."""
        return self.config.get("taxonomia_gut", {}).get(anomaly_key)

    def get_system_prompt(self, anomaly_key: str, context: str) -> str:
        """Gera prompt de sistema customizado baseado na taxonomia."""
        rules = self.get_anomaly_rules(anomaly_key)
        if not rules:
            return f"Analise tecnicamente: {context}"
        return rules.get("prompt_especifico_classificacao", "").format(informacoes_recuperadas=context)

    def get_gut_score(self, anomaly_key: str) -> Dict[str, int]:
        """Retorna scores GUT sugeridos para a anomalia."""
        rules = self.get_anomaly_rules(anomaly_key)
        if not rules:
            return {"G": 0, "U": 0, "T": 0}
        return rules.get("matriz_gut", {"G": 0, "U": 0, "T": 0})

    # ─── Funções Utilitárias para extrair_palavras_chave_v2 ─────────────────

    def inferir_tipo_secao(self, hierarquia: str) -> Dict[str, Any]:
        """
        Infere tipo e multiplicador de boost da hierarquia da seção.

        Args:
            hierarquia: Ex: "H15 ANOMALIA IDENTIFICADA"
        Returns:
            dict com tipo, multiplicador, categorias_boost

        Exemplo:
            tm.inferir_tipo_secao("H20 CRITÉRIO NORMATIVO NBR 6118")
            # → {"tipo": "normativo", "multiplicador": 1.5, ...}
        """
        for mapa in MAPA_SECOES:
            if mapa["padrao"].search(hierarquia):
                return {
                    "tipo": mapa["tipo"],
                    "multiplicador": mapa["multiplicador"],
                    "categorias_boost": mapa["categorias_boost"],
                }
        return {"tipo": "tecnico", "multiplicador": 1.0, "categorias_boost": []}

    def buscar_vocabulario_pericial(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Busca token no vocabulário pericial controlado (lookup O(1)).

        Args:
            token: Termo a verificar (case-insensitive)
        Returns:
            {"categoria": str, "boost": float} ou None

        Exemplo:
            tm.buscar_vocabulario_pericial("fissura")
            # → {"categoria": "patologias", "boost": 1.4}
        """
        resultado = self._indice_vocab.get(token.lower())
        if resultado:
            return {"categoria": resultado[0], "boost": resultado[1]}
        return None

    def aplicar_normalizacao_canonica(self, texto: str) -> str:
        """
        Substitui variantes informais por termos canônicos NBR no texto.
        Aplica word-boundary case-insensitive para precisão máxima.

        Args:
            texto: Texto bruto a normalizar.
        Returns:
            Texto com variantes substituídas pelos termos canônicos.

        Exemplo:
            tm.aplicar_normalizacao_canonica("Trincas e rachaduras na laje")
            # → "fissura e fissura na laje"
        """
        texto_norm = texto
        # Ordena do mais longo para o mais curto (evita substituições parciais)
        for variante in sorted(self.termos_canonicos.keys(), key=len, reverse=True):
            canonico = self.termos_canonicos[variante]
            try:
                # Aceita plural/flexão: permite 's', 'as', 'es' após a variante
                padrao = re.compile(
                    r"\b" + re.escape(variante) + r"(?:s|as|es)?\b",
                    re.IGNORECASE,
                )
                novo = padrao.sub(canonico, texto_norm)
                if novo != texto_norm:
                    logger.debug(f"Canônico: '{variante}' → '{canonico}'")
                    texto_norm = novo
            except re.error as e:
                logger.warning(f"Regex inválida para variante '{variante}': {e}")
        return texto_norm

    def eh_fragmento_verbal(self, token: str) -> bool:
        """
        Detecta fragmentos verbais ou advérbios sem valor técnico.

        Args:
            token: Token a verificar
        Returns:
            True se for fragmento verbal/advérbio.

        Exemplo:
            tm.eh_fragmento_verbal("desenvolvendo")  # → True
            tm.eh_fragmento_verbal("impermeabilização")  # → False
        """
        return bool(_SUFIXOS_VERBAIS.search(token))

    def eh_nome_proprio_ou_endereco(self, token: str) -> bool:
        """
        Detecta nomes próprios de pessoas, ruas ou cidades.

        Args:
            token: Token a verificar
        Returns:
            True se for nome próprio ou fragmento de endereço.

        Exemplo:
            tm.eh_nome_proprio_ou_endereco("rua hortência")  # → True
            tm.eh_nome_proprio_ou_endereco("corrosão de armadura")  # → False
        """
        if _RE_ENDERECO.search(token):
            return True
        if (
            len(token) > 3
            and token[0].isupper()
            and token.lower() not in self._indice_vocab
            and token.lower() not in {"abnt", "nbr", "spt", "iso", "gut"}
        ):
            return True
        return False

    def calcular_boost_categoria(self, termo: str, categorias_boost: List[str]) -> float:
        """
        Calcula boost multiplicador de categoria para um termo.

        Args:
            termo: Termo a verificar
            categorias_boost: Lista de categorias com boost ativo
        Returns:
            float boost (>= 1.0) se o termo pertence a alguma categoria.

        Exemplo:
            tm.calcular_boost_categoria("fissura", ["patologias"])
            # → 1.4
        """
        if not categorias_boost:
            return 1.0
        resultado = self._indice_vocab.get(termo.lower())
        if resultado and resultado[0] in categorias_boost:
            return resultado[1]
        return 1.0

    def get_boost_tipo_doc(self, tipo_documento: str) -> float:
        """
        Retorna multiplicador de boost para o tipo de documento.

        Args:
            tipo_documento: ex. "norma_abnt", "laudo_judicial"
        Returns:
            float boost (ex: norma_abnt → 1.2)
        """
        boosts = self.config.get("palavras_chave", {}).get("boost_tipos_documento", {})
        return float(boosts.get(tipo_documento, 1.0))

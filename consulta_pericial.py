"""
consulta_pericial.py — Processador de Consulta Pericial Estruturada v1.0
Sistema: Cérebro de Engenharia Diagnóstica v2.0

Função:
  Recebe FILTRO bruto (bagunçado/truncado/misto)
  → Normaliza e expande com sinônimos técnicos e NBRs
  → Executa busca híbrida no banco
  → Exibe tópicos segmentados e parseable (texto COMPLETO)
  → Reserva campo de interpretação para ciclo seguinte

Referência: PROMPT MESTRE — Processador de Consulta Pericial v1.0
"""
from __future__ import annotations

import re
import json
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# DICIONÁRIO DE EXPANSÃO PERICIAL
# Termo digitado → sinônimos técnicos + NBRs associadas
# ─────────────────────────────────────────────────────────────────────────────

_EXPANSAO_PERICIAL: Dict[str, Dict[str, List[str]]] = {
    # Esquadrias / Janelas
    "janela":        {"termos": ["esquadria", "caixilho", "vão de abertura", "folha móvel",
                                  "caixilharia", "janelas", "esquadrias"],
                      "nbrs":   ["NBR 10821", "NBR 7199", "NBR 10821-3"]},
    "janelas":       {"termos": ["esquadria", "caixilho", "vão de abertura", "caixilharia"],
                      "nbrs":   ["NBR 10821", "NBR 7199"]},
    "esquadria":     {"termos": ["janela", "caixilho", "vedação de fachada", "folha móvel",
                                  "caixilharia", "esquadrias"],
                      "nbrs":   ["NBR 10821", "NBR 7199", "NBR 10821-3"]},
    "caixilho":      {"termos": ["esquadria", "janela", "vão", "folha", "caixilharia"],
                      "nbrs":   ["NBR 10821", "NBR 7199"]},
    # Selantes / Calafetagem
    "selante":       {"termos": ["calafete", "calafetagem", "junta de dilatação", "vedação",
                                  "mástique", "silicone estrutural", "selagem", "selantes"],
                      "nbrs":   ["NBR 7542", "NBR 11578", "NBR 9286"]},
    "selantes":      {"termos": ["calafete", "calafetagem", "vedação", "junta", "silicone",
                                  "mástique", "selante"],
                      "nbrs":   ["NBR 7542", "NBR 11578"]},
    "calafete":      {"termos": ["selante", "calafetagem", "vedação", "junta"],
                      "nbrs":   ["NBR 7542"]},
    "calafetagem":   {"termos": ["selante", "calafete", "vedação de junta"],
                      "nbrs":   ["NBR 7542", "NBR 9286"]},
    # Peitoril / Soleira
    "peitoril":      {"termos": ["peitoris", "soleira", "contraverga", "rufo horizontal",
                                  "guarda-corpo baixo", "pingadeira"],
                      "nbrs":   ["NBR 14718", "NBR 15575-4"]},
    "peitoris":      {"termos": ["peitoril", "soleira", "contraverga", "pingadeira"],
                      "nbrs":   ["NBR 14718"]},
    "soleira":       {"termos": ["peitoril", "contraverga", "soleiras"],
                      "nbrs":   ["NBR 15575-4"]},
    # Infiltração / Estanqueidade
    "infiltracao":   {"termos": ["infiltração", "umidade", "estanqueidade", "permeabilidade",
                                  "manchas de umidade", "vazamento", "impermeabilização"],
                      "nbrs":   ["NBR 15575-4", "NBR 9575", "NBR 10821-3"]},
    "infiltração":   {"termos": ["umidade", "estanqueidade", "permeabilidade",
                                  "vazamento", "manchas de umidade", "impermeabilização"],
                      "nbrs":   ["NBR 15575-4", "NBR 9575", "NBR 10821-3"]},
    "umidade":       {"termos": ["infiltração", "estanqueidade", "umidade ascendente",
                                  "umidade descendente", "manchas", "bolor"],
                      "nbrs":   ["NBR 15575-4", "NBR 9575"]},
    "estanqueidade": {"termos": ["impermeabilidade", "vedação", "selagem",
                                  "lâmina d'água", "teste de estanqueidade", "infiltração"],
                      "nbrs":   ["NBR 15575-4", "NBR 9575", "NBR 13245"]},
    # Impermeabilização
    "impermeabilizacao": {"termos": ["impermeabilização", "manta asfáltica", "emulsão asfáltica",
                                      "estanqueidade", "membrana impermeabilizante"],
                           "nbrs":   ["NBR 9575", "NBR 15575-4"]},
    "impermeabilização":  {"termos": ["manta asfáltica", "emulsão", "estanqueidade",
                                       "membrana", "impermeabilizante"],
                           "nbrs":   ["NBR 9575", "NBR 15575-4"]},
    # Fissuras / Trincas
    "fissura":       {"termos": ["fissuração", "trinca", "rachadura", "fenda",
                                  "abertura de fissura", "fissurado"],
                      "nbrs":   ["NBR 6118", "NBR 15575-1", "NBR 16747"]},
    "trinca":        {"termos": ["fissura", "rachadura", "fissuração", "fenda"],
                      "nbrs":   ["NBR 6118", "NBR 15575-1"]},
    "fissuração":    {"termos": ["fissura", "trinca", "rachadura", "abertura"],
                      "nbrs":   ["NBR 6118", "NBR 15575-1"]},
    # Guarda-corpo
    "guarda-corpo":  {"termos": ["guarda corpo", "parapeito", "corrimão",
                                  "proteção lateral", "barreira de proteção",
                                  "gradil", "proteção de borda"],
                      "nbrs":   ["NBR 14718", "NBR 9050", "NBR 15575-1"]},
    "guarda_corpo":  {"termos": ["guarda-corpo", "parapeito", "corrimão",
                                  "proteção lateral"],
                      "nbrs":   ["NBR 14718", "NBR 9050"]},
    "parapeito":     {"termos": ["guarda-corpo", "proteção lateral", "barreira"],
                      "nbrs":   ["NBR 14718"]},
    # Fundação / Recalque
    "fundação":      {"termos": ["sapata", "estaca", "radier", "bloco", "tubulão",
                                  "fundações", "infraestrutura", "recalque"],
                      "nbrs":   ["NBR 6122", "NBR 6118", "NBR 8036"]},
    "recalque":      {"termos": ["afundamento", "cedência", "subsidência",
                                  "assentamento", "desnivelamento", "fundação"],
                      "nbrs":   ["NBR 6122", "NBR 6118"]},
    # Cobertura / Telhado
    "cobertura":     {"termos": ["telhado", "telha", "manta de cobertura", "impermeabilização",
                                  "rufo", "calha", "estrutura de telhado"],
                      "nbrs":   ["NBR 10844", "NBR 15575-5", "NBR 7190"]},
    "telhado":       {"termos": ["cobertura", "telha", "estrutura de telhado", "rufo", "calha"],
                      "nbrs":   ["NBR 10844", "NBR 15575-5"]},
    # Corrosão
    "corrosão":      {"termos": ["ferrugem", "oxidação", "armadura exposta",
                                  "carbonatação", "corroído", "cobrimento de armadura"],
                      "nbrs":   ["NBR 6118", "NBR 15575-1"]},
    "corrosao":      {"termos": ["corrosão", "ferrugem", "oxidação", "armadura exposta",
                                  "carbonatação", "cobrimento"],
                      "nbrs":   ["NBR 6118", "NBR 15575-1"]},
    # Desplacamento
    "desplacamento": {"termos": ["descolamento", "soltura", "estufamento",
                                  "queda de revestimento", "destaque cerâmico"],
                      "nbrs":   ["NBR 13755", "NBR 15575-4"]},
    "descolamento":  {"termos": ["desplacamento", "soltura", "estufamento"],
                      "nbrs":   ["NBR 13755"]},
    # Revestimento
    "revestimento":  {"termos": ["azulejo", "porcelanato", "cerâmica", "piso",
                                  "argamassa de revestimento", "reboco"],
                      "nbrs":   ["NBR 13755", "NBR 7200", "NBR 15575-4"]},
    "argamassa":     {"termos": ["reboco", "emboço", "chapisco", "massa",
                                  "argamassamento"],
                      "nbrs":   ["NBR 7200", "NBR 13281"]},
    # Vedação
    "vedação":       {"termos": ["vedação", "selagem", "junta", "calafetagem",
                                  "estanqueidade", "alvenaria de vedação"],
                      "nbrs":   ["NBR 7542", "NBR 15575-4", "NBR 10821"]},
    "vedacao":       {"termos": ["vedação", "selagem", "junta", "calafetagem"],
                      "nbrs":   ["NBR 7542", "NBR 15575-4"]},
    # Garantia
    "garantia":      {"termos": ["prazo de garantia", "garantia legal", "assistência técnica",
                                  "manual do proprietário", "prazos", "NBR 17170"],
                      "nbrs":   ["NBR 17170", "CDC art. 12"]},
    # Estrutura
    "estrutura":     {"termos": ["viga", "pilar", "laje", "concreto armado",
                                  "estrutural", "elemento estrutural"],
                      "nbrs":   ["NBR 6118", "NBR 15575-2", "NBR 8681"]},
    "laje":          {"termos": ["laje portante", "laje protendida", "forro", "teto",
                                  "laje de cobertura"],
                      "nbrs":   ["NBR 6118", "NBR 15575-2"]},
    "pilar":         {"termos": ["pilares", "coluna", "elemento de compressão"],
                      "nbrs":   ["NBR 6118"]},
    "viga":          {"termos": ["vigas", "viga de concreto", "viga metálica"],
                      "nbrs":   ["NBR 6118", "NBR 7190"]},
    # Patologia genérica
    "patologia":     {"termos": ["anomalia", "defeito", "falha", "dano",
                                  "manifestação patológica", "vício construtivo"],
                      "nbrs":   ["NBR 16747", "NBR 15575-1"]},
    "anomalia":      {"termos": ["patologia", "defeito", "falha", "vício construtivo",
                                  "grau de risco"],
                      "nbrs":   ["NBR 16747"]},
    # NBR abreviada
    "nbr":           {"termos": ["abnt", "norma", "normativo", "requisito"],
                      "nbrs":   []},
    # ── Termos faltantes em _EXPANSAO_PERICIAL (presentes em DICIONARIO_SINONIMOS) ──
    "eflorescência": {"termos": ["salitre", "floração", "depósito calcário",
                                  "mancha branca", "eflorescente",
                                  "eflorescencias", "cristalização salina"],
                      "nbrs":   ["NBR 13755", "NBR 15575-4"]},
    "eflorescencias":{"termos": ["eflorescência", "salitre", "depósito calcário",
                                  "mancha branca"],
                      "nbrs":   ["NBR 13755", "NBR 15575-4"]},
    "recalque diferencial": {
                      "termos": ["recalque", "afundamento diferencial", "subsidência",
                                  "assentamento diferencial", "desnivelamento de piso",
                                  "fissura diagonal", "fundação"],
                      "nbrs":   ["NBR 6122", "NBR 6118", "NBR 8036"]},
    "bolor":         {"termos": ["mofo", "fungo", "colonização biológica",
                                  "manchas escuras", "microorganismo",
                                  "umidade", "infiltração"],
                      "nbrs":   ["NBR 15575-1", "NBR 15575-4"]},
    "mofo":          {"termos": ["bolor", "fungo", "colonização biológica",
                                  "manchas escuras", "umidade"],
                      "nbrs":   ["NBR 15575-1"]},
    "carbonatação":  {"termos": ["carbonatacao", "corrosão de armadura",
                                  "ph concreto", "frente de carbonatação",
                                  "cobrimento insuficiente", "armadura exposta"],
                      "nbrs":   ["NBR 6118", "NBR 12655", "NBR 15575-2"]},
    "spalling":      {"termos": ["desplacamento de concreto", "lascamento",
                                  "cobrimento", "armadura exposta",
                                  "concreto fissurado", "destacamento"],
                      "nbrs":   ["NBR 6118", "NBR 15575-2"]},
    "junta de dilatação": {
                      "termos": ["junta de movimentação", "junta estrutural",
                                  "junta de dessolidarização", "selante",
                                  "calafetagem", "expansão térmica"],
                      "nbrs":   ["NBR 13755", "NBR 13753", "NBR 7542"]},
    "junta de movimentação": {
                      "termos": ["junta de dilatação", "junta estrutural",
                                  "junta de dessolidarização", "selante"],
                      "nbrs":   ["NBR 13753", "NBR 13755"]},
    "contrapiso":    {"termos": ["piso morto", "regularização", "argamassa de regularização",
                                  "espessura de contrapiso", "nivelamento"],
                      "nbrs":   ["NBR 13753", "NBR 15575-3"]},
    "emboço":        {"termos": ["reboco", "chapisco", "argamassa de emboço",
                                  "revestimento argamassado", "massa corrida"],
                      "nbrs":   ["NBR 7200", "NBR 13281"]},
    "aderência":     {"termos": ["resistência de aderência", "pull-off",
                                  "arrancamento", "descolamento", "aderência ao substrato",
                                  "argamassa colante", "0,3 mpa"],
                      "nbrs":   ["NBR 13753", "NBR 13755", "NBR 15575-4"]},
    "estanqueidade à água": {
                      "termos": ["lâmina d'água", "teste de estanqueidade",
                                  "impermeabilização", "vedação", "infiltração"],
                      "nbrs":   ["NBR 9575", "NBR 15575-4"]},
}

# Correções ortográficas (abreviações/erros comuns → termo correto)
_CORRECOES: Dict[str, str] = {
    "infilt":      "infiltração",
    "infiltracao": "infiltração",
    "calafte":     "calafete",
    "calafete":    "calafete",
    "vedaçao":     "vedação",
    "vedacao":     "vedação",
    "selan":       "selante",
    "selantr":     "selante",
    "selant":      "selante",
    "esquad":      "esquadria",
    "esquadr":     "esquadria",
    "imper":       "impermeabilização",
    "impermeab":   "impermeabilização",
    "impermeabilizacao": "impermeabilização",
    "fissur":      "fissura",
    "fissu":       "fissura",
    "guard":       "guarda-corpo",
    "guardc":      "guarda-corpo",
    "revestim":    "revestimento",
    "revestimet":  "revestimento",
    "corros":      "corrosão",
    "corrosao":    "corrosão",
    "recalqu":     "recalque",
    "fundac":      "fundação",
    "fundacao":    "fundação",
    "garantia":    "garantia",
    "permeab":     "permeabilidade",
    "estanq":      "estanqueidade",
    "argamas":     "argamassa",
    "patolog":     "patologia",
    "anomal":      "anomalia",
    # Novos (v1.1)
    "eflores":     "eflorescência",
    "efloresc":    "eflorescência",
    "carbonat":    "carbonatação",
    "carbonatac":  "carbonatação",
    "contrap":     "contrapiso",
    "contrapisso": "contrapiso",
    "aderenc":     "aderência",
    "adherencia":  "aderência",
    "spalling":    "spalling",
    "bolore":      "bolor",
    "mofo":        "bolor",
    "juntadil":    "junta de dilatação",
    "juntamov":    "junta de movimentação",
}

# Máximo de resultados antes de avisar sobre refinamento
MAX_RESULTADOS = 15


# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÕES UTILITÁRIAS
# ─────────────────────────────────────────────────────────────────────────────

def _remover_acentos(texto: str) -> str:
    """Normaliza para comparações sem acento."""
    return unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()


def _tokenizar_filtro(filtro: str) -> List[str]:
    """Separa filtro por espaço, vírgula, ponto e vírgula."""
    tokens = re.split(r"[,;\s]+", filtro.strip())
    return [t.strip().lower() for t in tokens if len(t.strip()) >= 2]


def _corrigir_token(token: str) -> str:
    """Aplica correções ortográficas ao token."""
    t = token.lower().strip()
    if t in _CORRECOES:
        return _CORRECOES[t]
    # Busca por prefixo (mín. 5 chars)
    if len(t) >= 5:
        for errado, correto in _CORRECOES.items():
            if t.startswith(errado[:5]) and len(errado) >= 5:
                return correto
    return t


def _extrair_nbrs_do_texto(texto: str) -> List[str]:
    """Extrai menções a NBRs diretamente do texto do tópico."""
    padrao = re.compile(r'\bNBR\s*[\d][\d\s\-:\.]*', re.IGNORECASE)
    encontradas = padrao.findall(texto)
    return sorted(set(n.strip().upper().replace("  ", " ") for n in encontradas))


# ─────────────────────────────────────────────────────────────────────────────
# PROCESSADOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class ConsultaPericialEstruturada:
    """
    Processador de consulta pericial conforme PROMPT MESTRE v1.0.

    Exemplo de uso:
        proc = ConsultaPericialEstruturada(db_manager)
        proc.processar("janelas selante peitoril infilt esquadria")
    """

    def __init__(self, db_manager: Any):
        """
        Args:
            db_manager: Instância de DatabaseManager com método busca_hibrida().
        """
        self.db = db_manager
        try:
            from processors import DICIONARIO_SINONIMOS
            self._sins = DICIONARIO_SINONIMOS
        except ImportError:
            self._sins = {}

    # ─── Entrada principal ────────────────────────────────────────────────────

    def processar(
        self,
        filtro_bruto: str,
        tipo_fonte: Optional[str] = None,
        n: int = MAX_RESULTADOS,
        modo_gui: bool = False,
    ) -> None:
        """
        Fluxo completo: normalizar → expandir → buscar → exibir → campo sistema.

        Args:
            filtro_bruto: Termos digitados pelo perito (aceita erros/abreviações).
            tipo_fonte:   "normas" | "laudos" | "livros" | None (todos).
            n:            Máximo de resultados a exibir (padrão 15).
            modo_gui:     Se True, suprime inputs interativos.
        """
        # ── CASO A: filtro muito curto ────────────────────────────────────
        if not filtro_bruto or len(filtro_bruto.strip()) < 3:
            print(
                "\n  ⚠️  Filtro insuficiente para busca técnica.\n"
                "  Forneça ao menos um termo técnico ou frase.\n"
                "  Exemplo: 'infiltração janela selante'"
            )
            return

        # ── Passo 1: Normalizar ───────────────────────────────────────────
        tokens_raw     = _tokenizar_filtro(filtro_bruto)
        tokens_corrig  = [_corrigir_token(t) for t in tokens_raw]

        # ── Passo 2: Expandir ─────────────────────────────────────────────
        expansao, termos_busca, nbrs_globais = self._expandir(tokens_corrig)

        # ── Passo 3: Exibir expansão ──────────────────────────────────────
        self._exibir_expansao(filtro_bruto, expansao, termos_busca)

        # ── Passo 4: Busca no banco ───────────────────────────────────────
        tipo_filtrado = self._resolver_tipo(tipo_fonte)
        resultados    = self._buscar(termos_busca, tipo_filtrado)

        if not resultados:
            sins_sug = self._sugerir_sinonimos(tokens_corrig)
            print(
                f"\n  ⚠️  Nenhum tópico encontrado para os termos expandidos.\n"
                f"  Sugestões:\n"
                f"  • Use termos mais genéricos\n"
                f"  • Verifique ortografia\n"
                f"  • Termos alternativos: {', '.join(sins_sug[:6]) or 'n/a'}"
            )
            return

        # ── CASO C: muitos resultados ─────────────────────────────────────
        total_real = len(resultados)
        if total_real > MAX_RESULTADOS:
            print(
                f"\n  ℹ️  {total_real} resultados encontrados. Exibindo top {MAX_RESULTADOS}.\n"
                f"  Para refinar: adicione termos mais específicos ou use filtro de fonte."
            )

        resultados_exib = resultados[:n]

        # ── CASO D: subsistemas distintos ─────────────────────────────────
        self._alertar_subsistemas(tokens_corrig, resultados_exib)

        # ── Passo 5: Exibir cabeçalho ─────────────────────────────────────
        self._exibir_cabecalho(filtro_bruto, len(termos_busca), len(resultados_exib), tipo_filtrado)

        # ── Passo 6: Exibir tópicos segmentados ──────────────────────────
        for i, doc in enumerate(resultados_exib, 1):
            self._exibir_topico(i, len(resultados_exib), doc, tokens_corrig)

        # ── Passo 7: Rodapé ───────────────────────────────────────────────
        self._exibir_rodape(len(resultados_exib), termos_busca)

        # ── Passo 8: Campo de interpretação ──────────────────────────────
        if not modo_gui:
            self._campo_interpretacao(resultados_exib, tokens_corrig)

    # ─── Normalização e Expansão ─────────────────────────────────────────────

    def _expandir(
        self, tokens: List[str]
    ) -> Tuple[Dict[str, Dict], List[str], List[str]]:
        """
        Expande cada token com sinônimos periciais e NBRs usando 4 camadas:
          L1 — _EXPANSAO_PERICIAL (dicionário estático curado)
          L2 — DICIONARIO_SINONIMOS de processors.py
          L3 — dicionario_pericial_sinonimos do banco de dados (dinâmico)
          L4 — busca por prefixo/substring nos dicionários L1/L2/L3

        Essa cadeia garante que qualquer termo técnico — mesmo que não
        esteja no dicionário estático — seja expandido via banco ou prefixo.

        Returns:
            expansao:     {token → {termos: [...], nbrs: [...]}}
            termos_busca: lista plana de todos os termos para a busca
            nbrs_globais: lista de NBRs identificadas
        """
        expansao: Dict[str, Dict] = {}
        termos_set: set = set(tokens)
        nbrs_globais: set = set()

        # ── Pré-carrega dicionário do banco (L3) ────────────────────────────
        sins_banco = self._carregar_sinonimos_banco()

        for token in tokens:
            entrada = None

            # L1 — dicionário estático curado (exato)
            entrada = _EXPANSAO_PERICIAL.get(token)

            # L2 — DICIONARIO_SINONIMOS de processors.py (exato)
            if not entrada:
                for conceito, sins in self._sins.items():
                    if token == conceito or token in sins:
                        entrada = {"termos": [conceito] + sins, "nbrs": []}
                        break

            # L3 — dicionário do banco de dados (exato)
            if not entrada:
                for conceito, dados in sins_banco.items():
                    sinonimos = dados.get("sinonimos", [])
                    if token == conceito or token in sinonimos:
                        entrada = {
                            "termos": [conceito] + sinonimos,
                            "nbrs": [],
                        }
                        break

            # L4 — busca por prefixo/substring (fallback genérico)
            # Cobre tokens abreviados, flexionados ou não normalizados
            if not entrada and len(token) >= 4:
                entrada = self._expandir_por_prefixo(token, sins_banco)

            if entrada:
                expansao[token] = entrada
                termos_set.update(t for t in entrada["termos"] if t)
                nbrs_globais.update(entrada.get("nbrs", []))
            else:
                # Nenhuma expansão encontrada — o token vai para a busca como está
                expansao[token] = {"termos": [], "nbrs": []}

        # Adicionar NBRs mencionadas diretamente no filtro
        for t in tokens:
            if re.match(r"nbr\s*\d+", t, re.IGNORECASE):
                nbrs_globais.add(t.upper())

        return expansao, sorted(termos_set), sorted(nbrs_globais)

    def _carregar_sinonimos_banco(self) -> Dict[str, Dict]:
        """
        Carrega o dicionário pericial do banco de dados (tabela
        dicionario_pericial_sinonimos criada em migrations.py).
        Retorna dict {conceito: {sinonimos: [...], categoria: str}}.
        Falha silenciosamente — nunca bloqueia a consulta.
        """
        resultado: Dict[str, Dict] = {}
        try:
            conn = self.db.get_connection()
            rows = conn.execute(
                "SELECT conceito, sinonimos, categoria FROM dicionario_pericial_sinonimos"
            ).fetchall()
            conn.close()
            for conceito, sins_json, categoria in rows:
                try:
                    sins = json.loads(sins_json) if isinstance(sins_json, str) else (sins_json or [])
                except Exception:
                    sins = []
                resultado[conceito.lower()] = {
                    "sinonimos": [s.lower() for s in sins],
                    "categoria": categoria or "",
                }
        except Exception:
            pass  # banco sem a tabela ou sem conexão — degradar para L1/L2
        return resultado

    def _expandir_por_prefixo(
        self, token: str, sins_banco: Dict[str, Dict]
    ) -> Optional[Dict]:
        """
        Busca expansão por prefixo/substring quando o token não foi encontrado
        nos dicionários exatos. Combina L1 + L2 + L3 numa varredura por prefixo.

        Regras:
          - Prefixo: o token precisa ter pelo menos 4 chars e ser prefixo do
            conceito/sinônimo, ou o conceito ser prefixo do token.
          - Substring bidirecional para tokens com 6+ chars.

        Retorna a primeira entrada encontrada, ou None.
        """
        t = token.lower()
        min_len = max(4, len(t) - 2)  # tolera variações de flexão

        # Varrer L1 — _EXPANSAO_PERICIAL
        for conceito, dados in _EXPANSAO_PERICIAL.items():
            candidatos = [conceito] + dados.get("termos", [])
            for c in candidatos:
                c = c.lower()
                if (c.startswith(t[:min_len]) or t.startswith(c[:min_len])):
                    return dados
                if len(t) >= 6 and (t in c or c in t):
                    return dados

        # Varrer L2 — DICIONARIO_SINONIMOS
        for conceito, sins in self._sins.items():
            candidatos = [conceito] + sins
            for c in candidatos:
                c = c.lower()
                if (c.startswith(t[:min_len]) or t.startswith(c[:min_len])):
                    return {"termos": [conceito] + sins, "nbrs": []}
                if len(t) >= 6 and (t in c or c in t):
                    return {"termos": [conceito] + sins, "nbrs": []}

        # Varrer L3 — banco
        for conceito, dados in sins_banco.items():
            candidatos = [conceito] + dados.get("sinonimos", [])
            for c in candidatos:
                if (c.startswith(t[:min_len]) or t.startswith(c[:min_len])):
                    return {"termos": [conceito] + dados["sinonimos"], "nbrs": []}
                if len(t) >= 6 and (t in c or c in t):
                    return {"termos": [conceito] + dados["sinonimos"], "nbrs": []}

        return None

    def _buscar(self, termos: List[str], tipo_fonte: Optional[str]) -> List[Dict]:
        """
        Executa busca híbrida e retorna resultados ordenados por score.

        Tenta gerar embedding da query para ativar a busca vetorial semântica.
        Se o AIEngine não estiver disponível, degrada para busca textual pura
        sem quebrar o fluxo.
        """
        embedding_query: Optional[List[float]] = self._gerar_embedding_query(termos)
        try:
            resultados = self.db.busca_hibrida(
                termos=termos,
                embedding_query=embedding_query,
                tipo_fonte=tipo_fonte,
                n=MAX_RESULTADOS * 2,
            )
        except Exception:
            try:
                resultados = self.db.busca_textual(termos, tipo_fonte=tipo_fonte)
            except Exception as exc:
                print(f"\n  ❌ Erro na busca: {exc}")
                return []
        return resultados or []

    def _gerar_embedding_query(self, termos: List[str]) -> Optional[List[float]]:
        """
        Gera embedding da query expandida usando o AIEngine, se disponível.
        Retorna None silenciosamente em qualquer falha — nunca bloqueia a consulta.
        """
        try:
            ai = getattr(self.db, "_ai_engine", None)
            if ai is None:
                from ai_engine import AIEngine
                ai = AIEngine()
            if ai and getattr(ai, "ia_disponivel", False):
                texto_query = " ".join(termos[:20])
                return ai.gerar_embedding(texto_query)
        except Exception:
            pass
        return None

    def _resolver_tipo(self, tipo_fonte: Optional[str]) -> Optional[str]:
        """Converte alias amigável para chave interna."""
        mapa = {
            "normas":  "norma_abnt",
            "laudos":  "laudo_judicial",
            "livros":  "livro",
            "todos":   None,
        }
        return mapa.get(tipo_fonte, tipo_fonte)

    def _sugerir_sinonimos(self, tokens: List[str]) -> List[str]:
        """Retorna sugestões de termos alternativos quando não há resultados."""
        sugestoes: set = set()
        for t in tokens:
            for conceito, sins in self._sins.items():
                if t in conceito:
                    sugestoes.update(sins[:3])
        return sorted(sugestoes)[:8]

    # ─── Exibição ─────────────────────────────────────────────────────────────

    def _exibir_expansao(
        self,
        filtro_original: str,
        expansao: Dict[str, Dict],
        termos_busca: List[str],
    ) -> None:
        L = 54
        borda = "│"
        print(f"\n┌{'─' * (L + 2)}┐")
        print(f"{borda}  🔍 FILTRO RECEBIDO: {filtro_original[:35]:<35}{borda}")
        print(f"├{'─' * (L + 2)}┤")
        print(f"{borda}  TERMOS EXPANDIDOS:{' ' * (L - 17)}{borda}")
        for token, dados in expansao.items():
            termos_str = ", ".join(dados["termos"][:4])
            nbrs_str   = ", ".join(dados.get("nbrs", [])[:2])
            expandido  = f"{termos_str}" + (f" | {nbrs_str}" if nbrs_str else "")
            linha = f"  • {token} → {expandido}"
            print(f"{borda}  {linha[:L - 2]:<{L - 2}}{borda}")
        print(f"│{' ' * (L + 2)}│")
        print(f"{borda}  Total termos na busca: {len(termos_busca):<{L - 24}}{borda}")
        print(f"└{'─' * (L + 2)}┘")

    def _exibir_cabecalho(
        self,
        filtro: str,
        n_termos: int,
        total: int,
        tipo_filtrado: Optional[str],
    ) -> None:
        tipo_label = tipo_filtrado or "todas"
        data_hora  = datetime.now().strftime("%d/%m/%Y %H:%M")
        L = 56
        b = "║"
        print(f"\n╔{'═' * (L + 2)}╗")
        print(f"{b}  CONSULTA PERICIAL — RESULTADOS SEGMENTADOS{' ' * (L - 43)}{b}")
        print(f"╠{'═' * (L + 2)}╣")
        print(f"{b}  Filtro original:  {filtro[:35]:<{L - 19}}{b}")
        print(f"{b}  Termos na busca:  {n_termos:<{L - 19}}{b}")
        print(f"{b}  Resultados:       {total:<{L - 19}}{b}")
        print(f"{b}  Fonte filtrada:   {tipo_label:<{L - 19}}{b}")
        print(f"{b}  Data:             {data_hora:<{L - 19}}{b}")
        print(f"╚{'═' * (L + 2)}╝\n")

    def _exibir_topico(
        self,
        n: int,
        total: int,
        doc: Dict[str, Any],
        tokens_originais: List[str],
    ) -> None:
        # Metadados
        fonte    = doc.get("nome_arquivo", "—")
        tipo_raw = doc.get("tipo_fonte", "outro")
        tipo     = tipo_raw
        secao    = doc.get("hierarquia", doc.get("titulo_topico", "—"))
        num      = doc.get("numero_topico", "")
        if num and secao and num not in secao:
            secao = f"{num} {secao}"
        score    = doc.get("score", doc.get("similarity", 0))
        score_str = f"{int(score * 100)}%" if isinstance(score, float) and score <= 1 \
                    else f"{int(score)}%"
        texto    = doc.get("texto_original", doc.get("texto_reescrito", ""))
        # NBRs
        nbrs_encontradas = _extrair_nbrs_do_texto(texto)
        nbrs_str = ", ".join(nbrs_encontradas[:6]) or "—"
        # Termos do filtro encontrados
        termos_no_texto = [
            t for t in tokens_originais
            if t.lower() in texto.lower()
        ]
        termos_str = ", ".join(termos_no_texto) or "—"

        SEP1 = "═" * 60
        SEP2 = "─" * 60

        print(SEP1)
        print(f"TÓPICO [{n}] de [{total}]")
        print(SEP1)
        print(f"FONTE:      {fonte}")
        print(f"TIPO:       {tipo}")
        print(f"SEÇÃO:      {secao}")
        print(f"SCORE:      {score_str}")
        print(f"NBRs:       {nbrs_str}")
        print(f"TERMOS:     {termos_str}")
        print(SEP2)
        print("TEXTO COMPLETO:\n")
        print(texto)        # ← texto NA ÍNTEGRA, sem truncamento
        print(f"\n{SEP1}\n")

    def _exibir_rodape(self, total: int, termos_busca: List[str]) -> None:
        sep = "─" * 60
        print(sep)
        print(f"FIM DOS RESULTADOS — {total} tópico(s) exibido(s)")
        print(f"Filtro expandido: {', '.join(termos_busca)}")
        print(sep)

    def _alertar_subsistemas(
        self, tokens: List[str], resultados: List[Dict]
    ) -> None:
        """Avisa quando o filtro abrange subsistemas distintos (Caso D)."""
        MAPA_SUB = {
            "estrutural": ["viga", "pilar", "laje", "fundação", "estrutura", "recalque",
                           "fissura", "trinca", "corrosão"],
            "elétrico":   ["elétrico", "fiação", "aterramento", "spda", "quadro", "disjuntor"],
            "hidrossanitário": ["infiltração", "umidade", "impermeabilização", "calha",
                                "tubulação", "esgoto", "água", "selante", "peitoril",
                                "esquadria", "janela", "calafete", "vedação"],
            "cobertura":  ["telhado", "cobertura", "telha", "rufo", "manta"],
            "acabamento": ["revestimento", "argamassa", "cerâmica", "piso", "desplacamento"],
        }
        subs_detectados: Dict[str, List[str]] = {}
        for token in tokens:
            for sub, kws in MAPA_SUB.items():
                if token in kws:
                    subs_detectados.setdefault(sub, []).append(token)

        if len(subs_detectados) > 2:
            print(f"\n  ℹ️  Filtro abrange {len(subs_detectados)} subsistemas distintos:")
            for sub, tks in subs_detectados.items():
                print(f"     [{sub.upper()}] → {', '.join(tks)}")
            print()

    # ─── Campo de Interpretação ───────────────────────────────────────────────

    def _campo_interpretacao(
        self,
        resultados: List[Dict],
        tokens: List[str],
    ) -> None:
        """
        Exibe o bloco de campo de interpretação e processa a entrada do usuário
        se preenchida.
        """
        L = 56
        b = "║"
        print(f"\n╔{'═' * (L + 2)}╗")
        print(f"{b}{'':^{L + 2}}{b}")
        print(f"{b}  CAMPO DE INTERPRETAÇÃO — TEXTO DO SISTEMA{' ' * (L - 42)}{b}")
        print(f"{b}{'':^{L + 2}}{b}")
        print(f"╠{'═' * (L + 2)}╣")
        print(f"{b}  Insira texto para cruzamento com os tópicos acima.{' ' * (L - 51)}{b}")
        print(f"{b}  Aceita: descrição do caso, quesitos, contexto,    {' ' * (L - 52)}{b}")
        print(f"{b}  instruções de análise ou texto técnico livre.      {' ' * (L - 52)}{b}")
        print(f"{b}{'':^{L + 2}}{b}")
        print(f"╠{'═' * (L + 2)}╣")
        print(f"{b}  TEXTO DO SISTEMA (ENTER em branco para pular):     {' ' * (L - 52)}{b}")
        print(f"{b}{'':^{L + 2}}{b}")
        print(f"╚{'═' * (L + 2)}╝")

        linhas: List[str] = []
        print("  (Digite o texto abaixo. Linha em branco encerra a entrada.)")
        while True:
            try:
                linha = input("  > ")
            except (EOFError, KeyboardInterrupt):
                break
            if linha.strip() == "":
                break
            linhas.append(linha)

        texto_sistema = "\n".join(linhas).strip()
        if not texto_sistema:
            return

        # ── Processar texto do sistema ────────────────────────────────────
        self._processar_texto_sistema(texto_sistema, resultados, tokens)

    def _processar_texto_sistema(
        self,
        texto_sistema: str,
        resultados: List[Dict],
        tokens: List[str],
    ) -> None:
        """
        Ação 1-4: cruzamento, resposta orientada, output adicional.
        Conforme Seção 5 do PROMPT MESTRE.
        """
        # ── AÇÃO 1 — Identificar tópicos relevantes ────────────────────
        palavras_sistema = set(re.findall(r'\w{4,}', texto_sistema.lower()))
        relevantes: List[Tuple[int, Dict, float]] = []

        for i, doc in enumerate(resultados, 1):
            texto_doc = (
                doc.get("texto_original", "") + " " +
                doc.get("titulo_topico", "") + " " +
                doc.get("hierarquia", "")
            ).lower()
            # Score de relevância: interseção de palavras
            palavras_doc = set(re.findall(r'\w{4,}', texto_doc))
            intersecao = palavras_sistema & palavras_doc
            if intersecao:
                score_rel = len(intersecao) / max(len(palavras_sistema), 1)
                relevantes.append((i, doc, score_rel))

        relevantes.sort(key=lambda x: x[2], reverse=True)
        top_relevantes = relevantes[:5]

        # ── AÇÃO 4 — Output final ──────────────────────────────────────
        L = 56
        b = "║"
        nbrs_usadas: set = set()
        for _, doc, _ in top_relevantes:
            nbrs_usadas.update(_extrair_nbrs_do_texto(
                doc.get("texto_original", doc.get("texto_reescrito", ""))
            ))

        ids_relevantes = [str(i) for i, _, _ in top_relevantes]

        print(f"\n╔{'═' * (L + 2)}╗")
        print(f"{b}  INTERPRETAÇÃO — BASE NOS TÓPICOS RECUPERADOS{' ' * (L - 46)}{b}")
        print(f"╠{'═' * (L + 2)}╣")
        print(f"{b}  Tópicos utilizados: {', '.join(ids_relevantes) or 'nenhum':<{L - 21}}{b}")
        nbrs_str = ', '.join(sorted(nbrs_usadas)[:6]) or '—'
        print(f"{b}  Normas identificadas: {nbrs_str:<{L - 23}}{b}")
        print(f"╠{'═' * (L + 2)}╣")

        # ── AÇÃO 2 — Resposta orientada ────────────────────────────────
        if top_relevantes:
            print(f"{b}  ANÁLISE COM BASE NOS TÓPICOS ENCONTRADOS:{' ' * (L - 43)}{b}")
            print(f"{b}{'':^{L + 2}}{b}")
            for i, doc, score in top_relevantes:
                fonte   = doc.get("nome_arquivo", "—")
                secao   = doc.get("titulo_topico", doc.get("hierarquia", "—"))
                trecho  = doc.get("texto_original", "")[:200].replace("\n", " ")
                print(f"{b}  ⭐ Tópico [{i}] — {fonte[:20]} — {secao[:25]}{' ' * 2}{b}")
                print(f"{b}     \"{trecho}...\"{' ' * max(0, L - len(trecho[:40]) - 6)}{b}")
                print(f"{b}{'':^{L + 2}}{b}")
        else:
            print(f"{b}  Nenhum tópico com correspondência direta ao texto.{' ' * (L - 51)}{b}")
            print(f"{b}  Refine o filtro ou forneça mais contexto.{' ' * (L - 42)}{b}")

        print(f"╠{'═' * (L + 2)}╣")
        print(f"{b}  TÓPICOS MAIS RELEVANTES PARA O CASO:{' ' * (L - 38)}{b}")
        for i, doc, score in top_relevantes[:3]:
            fonte  = doc.get("nome_arquivo", "—")[:25]
            secao  = doc.get("titulo_topico", "—")[:20]
            print(f"{b}  ⭐ Tópico [{i}] — {fonte} — {secao}{' ' * 4}{b}")
        print(f"╚{'═' * (L + 2)}╝\n")


# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÃO DE ENTRADA (usada por main.py)
# ─────────────────────────────────────────────────────────────────────────────

def consulta_pericial_cli(
    db_manager: Any,
    filtro_inicial: str = "",
    tipo_fonte: Optional[str] = None,
    n: int = MAX_RESULTADOS,
) -> None:
    """
    Ponto de entrada CLI para o Processador de Consulta Pericial.

    Args:
        db_manager:    Instância de DatabaseManager.
        filtro_inicial: Filtro pré-preenchido (opcional — vem do comando da linha).
        tipo_fonte:    "normas" | "laudos" | "livros" | None (todos).
        n:             Máximo de resultados.
    """
    proc = ConsultaPericialEstruturada(db_manager)

    if filtro_inicial:
        filtro = filtro_inicial
    else:
        print("\n" + "═" * 62)
        print("  🔬 CONSULTA PERICIAL ESTRUTURADA v1.0")
        print("  Aceita termos bagunçados, truncados ou com erros")
        print("═" * 62)
        print("  📌 SEPARAÇÃO DE TERMOS:")
        print("  ─────────────────────────────────────────────────────")
        print("  Use espaço, vírgula ou ponto e vírgula — são equivalentes:")
        print("    inclinação escoamento caimento piso")
        print("    inclinação, escoamento, caimento, piso")
        print("    inclinação; escoamento; caimento; piso")
        print()
        print("  Aspas duplas buscam a frase exata (sem expansão de sinônimos):")
        print("    \"caimento mínimo de piso\"")
        print()
        print("  Abreviações e erros são corrigidos automaticamente:")
        print("    infiltracao  →  infiltração")
        print("    guarda corp  →  guarda-corpo")
        print("    infilt       →  infiltração")
        print("  ─────────────────────────────────────────────────────")
        print("  Filtro de fonte (opcional): [1] Normas  [2] Laudos  [3] Todos")
        escolha_tipo = input("  Fonte [ENTER=todos]: ").strip()
        tipo_fonte = {"1": "normas", "2": "laudos", "3": None}.get(escolha_tipo, tipo_fonte)

        filtro = input("\n  FILTRO: ").strip()

    if not filtro:
        print("  ⚠️  Nenhum filtro informado.")
        return

    proc.processar(filtro, tipo_fonte=tipo_fonte, n=n)

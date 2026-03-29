"""
ai_engine.py — Motor de IA do Cérebro de Engenharia Diagnóstica
Versão 2.1 — Suporte a contexto de sessão acumulado, fallback gracioso,
             modo offline, prompts especializados, AIHealthMonitor e
             EmbeddingCache L1/L2 (cache persistente de embeddings).
             O sistema funciona SEM IA — todos os módulos têm fallback.
"""
import os
import yaml
import json
import requests
from typing import List, Dict, Any, Optional

try:
    from google import genai as _genai_new
    from google.genai import types as _genai_types
    # Novo SDK (google-genai >= 1.0)
    GEMINI_DISPONIVEL = True
    _GENAI_SDK = "new"
except ImportError:
    try:
        import google.generativeai as _genai_legacy
        GEMINI_DISPONIVEL = True
        _GENAI_SDK = "legacy"
    except ImportError:
        print("⚠️  SDK Gemini nao encontrado. Execute: pip install google-genai")
        GEMINI_DISPONIVEL = False
        _GENAI_SDK = None

# Fallback offline: sentence_transformers multilingual (768 dims, sem API)
_SBERT_MODEL = None
_SBERT_DIM   = 768
try:
    import os as _os, logging as _log_st
    # Suprimir avisos do HuggingFace Hub e logs internos do sentence-transformers
    _os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    _os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    _os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    _os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    _log_st.getLogger("sentence_transformers").setLevel(_log_st.ERROR)
    _log_st.getLogger("transformers").setLevel(_log_st.ERROR)
    _log_st.getLogger("huggingface_hub").setLevel(_log_st.ERROR)

    from sentence_transformers import SentenceTransformer as _SentenceTransformer
    _SBERT_MODEL = _SentenceTransformer(
        "paraphrase-multilingual-mpnet-base-v2",
        tokenizer_kwargs={"clean_up_tokenization_spaces": True},
    )
    _SBERT_DIM = _SBERT_MODEL.get_sentence_embedding_dimension()
except Exception:
    pass  # Modelo offline não disponível — vetor nulo como último recurso

# Fallback LLM local: Ollama (sem API, requer servidor local em localhost:11434)
try:
    from ollama_engine import OllamaEngine as _OllamaEngine
    _OLLAMA_DISPONIVEL = True
except ImportError:
    _OllamaEngine = None  # type: ignore
    _OLLAMA_DISPONIVEL = False


class SemIAError(Exception):
    """Levantada quando a IA está indisponível ou retorna erro."""
    pass


class AIEngine:
    """
    Motor de IA compatível com Google Gemini e Groq (via API REST).
    Focado em Rigor Pericial, Reranking e Grounding.

    IMPORTANTE: O sistema foi projetado para funcionar sem IA.
    Quando a IA está indisponível, todos os métodos retornam
    valores seguros ou levantam SemIAError para que o chamador
    use o fallback de evidências brutas.
    """

    def __init__(self, api_key: str = '', config_path: str = "config_pericial.yaml"):
        self.config     = self._load_config(config_path)
        self.api_key    = api_key
        self.provider   = self.config.get("sistema", {}).get("provedor", "gemini").lower()
        self.modelo_llm = self.config.get("sistema", {}).get("modelo_llm", "gemini-2.0-flash")
        self.temp_rag   = self.config.get("sistema", {}).get("temperatura_rag", 0.1)
        self.model      = None

        # Modelos em ordem de preferência (fallback automático)
        self._modelos_fallback = [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash-latest",
            "gemini-1.5-flash-001",
            "gemini-1.5-flash",
            "gemini-pro",
        ]

        if self.provider == "gemini" and api_key and GEMINI_DISPONIVEL:
            try:
                if _GENAI_SDK == "new":
                    # Forçar api_version="v1" — corrige erro "not found for API version v1beta"
                    try:
                        self._genai_client = _genai_new.Client(
                            api_key=api_key,
                            http_options={"api_version": "v1"},
                        )
                    except TypeError:
                        # Versões antigas do SDK não aceitam http_options
                        self._genai_client = _genai_new.Client(api_key=api_key)
                    self.model = self.modelo_llm
                else:
                    _genai_legacy.configure(api_key=api_key)
                    self.model = _genai_legacy.GenerativeModel(self.modelo_llm)
                    self._genai_client = None
            except Exception as e:
                print(f"⚠️  Erro ao inicializar Gemini: {e}")

        self.groq_url     = "https://api.groq.com/openai/v1/chat/completions"
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")

    def _load_config(self, path: str) -> Dict[str, Any]:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        return {}

    @property
    def ia_disponivel(self) -> bool:
        if (self.model is not None) or bool(self.groq_api_key):
            return True
        # Verificar Ollama como provedor alternativo (resultado cacheado por sessão)
        if not hasattr(self, '_ollama_ok'):
            try:
                self._ollama_ok = (
                    _OLLAMA_DISPONIVEL
                    and _OllamaEngine is not None
                    and _OllamaEngine().disponivel
                )
            except Exception:
                self._ollama_ok = False
        return self._ollama_ok

    # ─────────────────────────────────────────────────────────────────────────
    #  EMBEDDINGS
    # ─────────────────────────────────────────────────────────────────────────

    def gerar_embedding(self, texto: str) -> List[float]:
        """
        Gera vetor semântico via Gemini text-embedding-004.
        Usa EmbeddingCache L1/L2 para evitar chamadas redundantes de API.
        Retorna vetor nulo se IA indisponível (busca degrada para textual pura).

        Ref: Princípio [A4] — Cache Inteligente.
        """
        # Verificar cache primeiro (L1 → L2)
        cache = getattr(self, "_embedding_cache", None)
        if cache is not None:
            cached = cache.obter(texto)
            if cached:
                return cached

        # Verificar disponibilidade via health monitor
        monitor = getattr(self, "_health_monitor", None)
        if monitor is not None and not monitor.eh_online():
            import logging as _log
            _log.getLogger(__name__).debug(
                "[Embedding] IA offline — retornando vetor nulo (busca textual ativa)"
            )
            return [0.0] * 768

        if self.provider == "gemini" and self.api_key and GEMINI_DISPONIVEL:
            try:
                if _GENAI_SDK == "new":
                    result = self._genai_client.models.embed_content(
                        model="text-embedding-004",
                        contents=texto,
                    )
                    vetor = result.embeddings[0].values
                else:
                    result = _genai_legacy.embed_content(
                        model="models/text-embedding-004",
                        content=texto,
                        task_type="retrieval_document"
                    )
                    vetor = result['embedding']

                # Salvar no cache
                if cache is not None:
                    cache.salvar(texto, vetor)
                return vetor

            except Exception as e:
                print(f"   ⚠️  Embedding Gemini indisponível: {e}")

        # Fallback 1: sentence_transformers offline (paraphrase-multilingual-mpnet-base-v2)
        if _SBERT_MODEL is not None:
            try:
                import logging as _log_mod
                _log_mod.getLogger(__name__).info(
                    "[Embedding] Usando fallback offline (sentence_transformers)"
                )
                vetor = _SBERT_MODEL.encode(texto, normalize_embeddings=True).tolist()
                if cache is not None:
                    cache.salvar(texto, vetor)
                return vetor
            except Exception as e2:
                print(f"   ⚠️  Embedding offline falhou: {e2}")

        # Fallback 2: vetor nulo — busca degrada para textual pura
        return [0.0] * _SBERT_DIM

    def configurar_cache(self, conn) -> None:
        """
        Configura o EmbeddingCache L1/L2 usando uma conexão SQLite.
        Deve ser chamado após inicialização quando a conexão estiver disponível.

        Args:
            conn: Conexão sqlite3 aberta com o banco principal.
        """
        try:
            from ai_health_monitor import EmbeddingCache
            self._embedding_cache = EmbeddingCache(conn)
            self._embedding_cache.limpar_expirados()
        except ImportError:
            import logging as _log
            _log.getLogger(__name__).warning(
                "ai_health_monitor.py não encontrado — cache de embeddings desativado."
            )

    def configurar_health_monitor(self, monitor) -> None:
        """
        Injeta AIHealthMonitor para decisões de disponibilidade offline.

        Args:
            monitor: Instância de AIHealthMonitor.
        """
        self._health_monitor = monitor

    # ─────────────────────────────────────────────────────────────────────────
    #  CONSULTA PRINCIPAL (com contexto de sessão)
    # ─────────────────────────────────────────────────────────────────────────

    def consultar_base(self, query: str, chunks: List[Dict[str, Any]],
                       contexto_sessao: str = '') -> str:
        """
        Gera resposta fundamentada com citações a partir dos chunks recuperados.

        chunks: lista de dicts com chaves:
            - titulo (str)
            - texto  (str)
            - numero (str)
            - metadata: dict com 'page', 'tipo_fonte', 'hierarquia'
            - similarity (float)

        contexto_sessao: histórico das últimas trocas da sessão (opcional).
        """
        if not self.ia_disponivel:
            raise SemIAError("Nenhum provedor de IA configurado.")

        # Monta contexto técnico
        contexto_list = []
        for i, c in enumerate(chunks[:6]):
            meta  = c.get('metadata', {})
            hier  = meta.get('hierarquia', '')
            tipo  = meta.get('tipo_fonte', '')
            ref   = (f"REF_{i+1}: {c.get('titulo','')}"
                     f" | Item: {c.get('numero','-')}"
                     f" | Pág: {meta.get('page','-')}")
            if hier: ref += f" | Hierarquia: {hier}"
            if tipo: ref += f" | Tipo: {tipo}"
            contexto_list.append(f"[{ref}]\n{c.get('texto','')}")

        contexto_final = "\n---\n".join(contexto_list)

        # Contexto acumulado da sessão
        bloco_sessao = ""
        if contexto_sessao:
            bloco_sessao = f"\n[CONTEXTO DA SESSÃO ATUAL]\n{contexto_sessao}\n"

        system_prompt = f"""Você é um Assistente Técnico Pericial de Engenharia, especializado em \
patologia das construções, inspeção predial, normas técnicas (ABNT/NBR) e laudos periciais.

Sua tarefa é responder à [DÚVIDA] baseando-se ESTRITAMENTE no [CONTEXTO TÉCNICO] fornecido.

REGRAS OBRIGATÓRIAS:
1. RASTREABILIDADE: Toda afirmação técnica deve ter citação no formato [REF_X].
2. INTEGRIDADE: Se a informação não estiver no contexto, declare: "INSUFICIÊNCIA DE EVIDÊNCIAS \
no banco atual para fundamentar este ponto."
3. NÃO INVENTE: Não cite normas, itens ou valores que não estejam no contexto.
4. HIERARQUIA DE FONTES: Normas ABNT > Normas ISO > Laudos Judiciais > Livros.
5. LINGUAGEM TÉCNICA: Use terminologia pericial adequada.
6. FORMATO DA RESPOSTA:
   a) Fundamento Normativo (se houver normas no contexto)
   b) Análise Técnica
   c) Referências utilizadas (lista numerada)
{bloco_sessao}
[CONTEXTO TÉCNICO]:
{contexto_final}
"""

        return self._chamar_llm(system_prompt, f"[DÚVIDA]: {query}")

    # ─────────────────────────────────────────────────────────────────────────
    #  CHAMADA AO LLM
    # ─────────────────────────────────────────────────────────────────────────

    def _chamar_llm(self, system_prompt: str, user_message: str) -> str:
        import logging as _log_llm
        _logger = _log_llm.getLogger(__name__)

        if self.provider == "gemini" and self.model:
            try:
                if _GENAI_SDK == "new":
                    resp = self._genai_client.models.generate_content(
                        model=self.model,
                        contents=f"{system_prompt}\n\n{user_message}",
                        config=_genai_types.GenerateContentConfig(
                            temperature=self.temp_rag,
                            max_output_tokens=2048,
                        ),
                    )
                    return resp.text
                else:
                    response = self.model.generate_content(
                        f"{system_prompt}\n\n{user_message}",
                        generation_config=_genai_legacy.types.GenerationConfig(
                            temperature=self.temp_rag,
                            max_output_tokens=2048,
                        )
                    )
                    return response.text
            except Exception as e:
                _logger.warning("[LLM] Gemini indisponível: %s — tentando Ollama.", e)
                print(f"   ⚠️  Gemini indisponível — tentando Ollama local...")

        elif self.provider == "groq" and self.groq_api_key:
            try:
                headers = {
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": self.modelo_llm,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_message}
                    ],
                    "temperature": self.temp_rag,
                    "max_tokens": 2048,
                }
                resp = requests.post(self.groq_url, headers=headers,
                                     json=payload, timeout=30)
                return resp.json()['choices'][0]['message']['content']
            except Exception as e:
                _logger.warning("[LLM] Groq indisponível: %s — tentando Ollama.", e)
                print(f"   ⚠️  Groq indisponível — tentando Ollama local...")

        # Fallback: Ollama local (sem necessidade de API)
        if _OLLAMA_DISPONIVEL and _OllamaEngine is not None:
            try:
                _ollama = _OllamaEngine()
                if _ollama.disponivel:
                    print("   🔄  Usando Ollama local para gerar resposta...")
                    resposta = _ollama.gerar_qualidade(
                        user_message, sistema=system_prompt, max_tokens=2048
                    )
                    if resposta:
                        return resposta
                    _logger.warning("[LLM] Ollama retornou resposta vazia.")
            except Exception as e:
                _logger.warning("[LLM] Ollama falhou: %s", e)

        raise SemIAError("Nenhum provedor de IA ativo (Gemini/Groq/Ollama).")

    # ─────────────────────────────────────────────────────────────────────────
    #  EXTRAÇÃO DE QUESITOS
    # ─────────────────────────────────────────────────────────────────────────

    def extrair_quesitos(self, texto: str) -> List[Dict[str, str]]:
        """
        Extrai pares pergunta/resposta de seções de quesitos.
        Retorna lista vazia se IA indisponível (sem falha crítica).
        """
        if not self.ia_disponivel:
            return []
        prompt = (
            "Extraia os quesitos (perguntas e respostas) do texto técnico-pericial abaixo.\n"
            "Retorne APENAS um JSON puro, sem markdown, no formato:\n"
            '{"quesitos": [{"pergunta": "...", "resposta": "..."}]}\n\n'
            f"Texto:\n{texto[:8000]}"
        )
        try:
            raw = self._chamar_llm("Você é um extrator de quesitos periciais.", prompt)
            limpo = raw.strip().replace('```json', '').replace('```', '').strip()
            return json.loads(limpo).get('quesitos', [])
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────────────────────
    #  PROCESSAMENTO DE TEXTO
    # ─────────────────────────────────────────────────────────────────────────

    def processar_texto(self, texto: str, titulo: str) -> str:
        """
        Gera resumo técnico de um trecho para indexação.
        Retorna "MODO_OFFLINE" se IA indisponível (sinal para fallback local).
        """
        if not self.ia_disponivel:
            return "MODO_OFFLINE"
        prompt = (
            f"Você é um especialista em engenharia pericial.\n"
            f"Resuma tecnicamente o trecho abaixo em até 5 frases, "
            f"destacando: anomalia/patologia, critério normativo, método de verificação "
            f"e recomendação. Título do tópico: '{titulo}'.\n\n{texto[:3000]}"
        )
        try:
            return self._chamar_llm("Especialista em engenharia pericial.", prompt)
        except SemIAError:
            return "MODO_OFFLINE"

    # ─────────────────────────────────────────────────────────────────────────
    #  RERANKING (fallback quando não há cross-encoder)
    # ─────────────────────────────────────────────────────────────────────────

    def rerank_results(self, query: str,
                       chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Reordenação técnica por fluxo lógico pericial:
        Causa → Mecanismo → Critério Normativo → Método → Conclusão.
        Funciona SEM IA (baseado em palavras-chave).
        """
        def score(chunk):
            text = (chunk.get('texto', '') + ' ' + chunk.get('titulo', '')).lower()
            query_terms = query.lower().split()
            ts = sum(2 for t in query_terms if t in text)
            ps = 0
            if any(k in text for k in ["causa", "origem", "etiologia"]):            ps += 8
            if any(k in text for k in ["mecanismo", "fenômeno", "patologia"]):      ps += 6
            if any(k in text for k in ["critério", "norma", "nbr", "abnt"]):        ps += 15
            if any(k in text for k in ["método", "ensaio", "verificação"]):         ps += 5
            if any(k in text for k in ["conclusão", "recomendação", "reparo"]):     ps += 4
            vs = chunk.get('similarity', 0) * 20
            return ts + ps + vs

        return sorted(chunks, key=score, reverse=True)

    # ─────────────────────────────────────────────────────────────────────────
    #  IMAGENS (stubs — implementar conforme necessidade)
    # ─────────────────────────────────────────────────────────────────────────

    def processar_imagem_norma(self, caminho: str) -> str:
        """Transcreve imagem de norma via Gemini Vision."""
        if not self.ia_disponivel:
            return "[OCR indisponível — IA não configurada]"
        # Implementação futura com Gemini Vision
        return f"[Imagem {os.path.basename(caminho)} aguarda processamento OCR]"

    def processar_imagem_patologia(self, caminho: str) -> dict:
        """Analisa imagem de patologia e retorna risco/GUT/texto."""
        if not self.ia_disponivel:
            return {'risco': 'Não analisado (IA offline)', 'gut': '-',
                    'criterio': '-', 'texto': '[IA indisponível]'}
        return {'risco': 'Pendente', 'gut': 'G:-, U:-, T:-',
                'criterio': 'Verificar manualmente', 'texto': ''}

    def _chamar_llm_com_imagem(
        self,
        prompt: str,
        imagem_base64: str,
        mime_type: str = "image/jpeg",
        max_tokens: int = 800,
    ) -> str:
        """
        Chama o modelo com suporte multimodal (texto + imagem).

        Usado pelo analise_imagem.py para obter a descrição visual inicial
        antes do GUT Adaptativo e da Análise IBAPE.

        A chamada é sempre no formato:
          [imagem] + [prompt de descrição]
        O modelo descreve o que vê — NÃO classifica risco ou GUT.

        Args:
            prompt:        Texto da solicitação ao modelo.
            imagem_base64: Imagem codificada em base64.
            mime_type:     Tipo MIME da imagem (default: image/jpeg).
            max_tokens:    Máximo de tokens na resposta.

        Returns:
            Texto da resposta do modelo, ou string vazia em caso de falha.
        """
        if not self.ia_disponivel:
            return ""

        try:
            if _GENAI_SDK == "new" and hasattr(self, "_genai_client") and self._genai_client:
                from google.genai import types as _types
                import base64 as _b64

                # Montar conteúdo multimodal: imagem + texto
                conteudo = [
                    _types.Part.from_bytes(
                        data=_b64.b64decode(imagem_base64),
                        mime_type=mime_type,
                    ),
                    _types.Part.from_text(prompt),
                ]
                resp = self._genai_client.models.generate_content(
                    model=self.modelo_llm,
                    contents=conteudo,
                    config=_types.GenerateContentConfig(
                        max_output_tokens=max_tokens,
                        temperature=0.1,
                    ),
                )
                return resp.text if resp and resp.text else ""

            elif _GENAI_SDK == "legacy" and self.model:
                import base64 as _b64
                import google.generativeai as _genai_leg
                # SDK legado: usar PIL ou bytes inline
                img_part = {
                    "mime_type": mime_type,
                    "data": _b64.b64decode(imagem_base64),
                }
                resp = self.model.generate_content(
                    [img_part, prompt],
                    generation_config={"max_output_tokens": max_tokens, "temperature": 0.1},
                )
                return resp.text if resp and resp.text else ""

        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).warning(
                "Chamada multimodal falhou: %s", e
            )
        return ""

    def processar_texto_avulso(self, texto: str, titulo: str) -> str:
        return self.processar_texto(texto, titulo)


# =============================================================================
# EXTRAÇÃO DE PALAVRAS-CHAVE VIA IA — Palavras-Chave v2.0
# Camada de enriquecimento — usada APENAS quando offline retornou < 5 termos.
# Referência: Seção 5.4 da especificação | IBAPE (2025) items 12.1-12.3
# =============================================================================

PROMPT_PALAVRAS_CHAVE_IA = """
Você é especialista em indexação de documentos técnicos de engenharia civil e
perícias judiciais brasileiras, com domínio das normativas ABNT NBR e IBAPE.

Analise o tópico abaixo e extraia palavras-chave técnicas para indexação em um
sistema de busca pericial judicial.

SEÇÃO DO DOCUMENTO: {hierarquia}
TIPO DE DOCUMENTO:  {tipo_documento}
PALAVRAS-CHAVE JÁ IDENTIFICADAS OFFLINE: {existentes}

TEXTO DO TÓPICO:
{texto}

REGRAS OBRIGATÓRIAS — PRIORIDADE MÁXIMA:
[R1] Incluir SEMPRE: números de NBR com número
     ex: "NBR 6118", "NBR 15575-1:2024"
[R2] Incluir SEMPRE: patologias específicas identificadas
     ex: "fissuração", "eflorescência", "recalque"
[R3] Incluir SEMPRE: classificações IBAPE items 12.1-12.3
     ex: "anomalia endógena", "vício construtivo",
         "grau de risco crítico", "nexo causal"
[R4] Incluir SEMPRE: parâmetros com unidade física
     ex: "cobrimento mínimo 25 mm", "0,3 mm abertura"

PROIBIÇÕES ABSOLUTAS — NUNCA INCLUIR:
[P1] "laudo", "norma", "estrutura", "desempenho",
     "edificação", "sistema", "requisito" — ubíquos
[P2] Fragmentos de frases: "conforme descrito",
     "deve atender", "são previstos", "sejam desenvolvidos"
[P3] Nomes próprios de pessoas, ruas ou cidades
[P4] Verbos conjugados ou gerúndios
[P5] Termos não presentes no texto (não inventar)

NORMALIZAÇÃO OBRIGATÓRIA:
"trinca" → "fissura" | "janela" → "esquadria"
"ferro" → "armadura"  | "mofo" → "manifestação biológica"
"descolamento" → "desplacamento"

QUANTIDADE: Entre 5 e {max_palavras} palavras-chave.
ORDEM: Da mais específica e discriminante para a mais geral.
FORMATO: apenas os termos separados por vírgula.
         Sem numeração, sem explicação, sem texto adicional.

EXEMPLO CORRETO:
"NBR 6118, cobrimento de armadura, corrosão de armadura,
 carbonatação, classe de agressividade, 25 mm"

EXEMPLO INCORRETO (nunca fazer):
"laudo, norma, estrutura, desempenho, conforme descrito"
"""


def extrair_palavras_chave_ia(
    self,
    texto: str,
    hierarquia: str,
    tipo_documento: str,
    existentes: List[str],
    max_palavras: int = 10,
) -> List[str]:
    """
    Enriquece extração offline com Gemini 1.5 Flash.
    Chamado APENAS quando camadas offline retornaram < 5 termos.
    Fallback gracioso: retorna 'existentes' se IA indisponível.

    Args:
        texto:          Texto do tópico (truncado a 3000 chars).
        hierarquia:     Hierarquia da seção.
        tipo_documento: Tipo do documento (ex: "norma_abnt").
        existentes:     Lista de termos já identificados offline.
        max_palavras:   Máximo de termos a retornar.

    Returns:
        list[str] com palavras-chave enriquecidas.

    Exemplo de uso:
        ai = AIEngine(api_key="...")
        termos = ai.extrair_palavras_chave_ia(
            "Cobrimento insuficiente em pilar P3. NBR 6118.",
            "H20 ANOMALIA", "laudo_judicial", [], 10
        )
        # → ["nbr 6118", "cobrimento de armadura", "pilar", ...]
    """
    if not self.ia_disponivel:
        return existentes

    try:
        prompt = PROMPT_PALAVRAS_CHAVE_IA.format(
            hierarquia=hierarquia,
            tipo_documento=tipo_documento,
            existentes=", ".join(existentes) if existentes else "nenhuma",
            texto=texto[:3000],
            max_palavras=max_palavras,
        )
        resposta = self._chamar_llm(
            "Você é especialista em indexação técnico-pericial de engenharia civil.",
            prompt,
        )
        # Registra uso de tokens se método disponível
        if hasattr(self, "registrar_uso_tokens"):
            try:
                self.registrar_uso_tokens(
                    tokens_entrada=len(prompt.split()),
                    tokens_saida=len(resposta.split()),
                    operacao="extracao_palavras_chave",
                )
            except Exception:
                pass

        termos = [
            t.strip().lower()
            for t in resposta.split(",")
            if len(t.strip()) >= 4
        ]
        return termos[:max_palavras]

    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).warning(
            f"IA indisponível para extração de palavras-chave: {e}"
        )
        return existentes  # fallback gracioso


# Injeta o método na classe AIEngine
AIEngine.extrair_palavras_chave_ia = extrair_palavras_chave_ia

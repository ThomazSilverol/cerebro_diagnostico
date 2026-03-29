"""
ia_integrator.py â€” Integrador de IA para Reprocessamento (Fases 1 e 3)
Sistema: CÃ©rebro de Engenharia DiagnÃ³stica â€” Reprocessamento Inteligente v1.0

Responsabilidades:
  â€¢ Verificar disponibilidade da IA (via AIHealthMonitor)
  â€¢ Fase 1 com IA: enriquecimento de tÃ³picos (fallback offline se falhar)
  â€¢ Fase 3: refinamento semÃ¢ntico, classificaÃ§Ã£o de risco, nexo causal
  â€¢ Retry com backoff exponencial (mÃ¡x 5 tentativas)
  â€¢ Cache de respostas para evitar chamadas redundantes
  â€¢ Rate limiting para respeitar limites da API

ReferÃªncia: Componente IntegradorIA, SeÃ§Ã£o 4.1 e Regras 1/3 do prompt.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

_DIR_PROJETO = os.path.dirname(os.path.abspath(__file__))
_DB_PADRAO   = os.path.join(_DIR_PROJETO, 'banco_pericial.db')

from log_manager import GerenciadorLog

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# ImportaÃ§Ãµes opcionais do SDK Gemini
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

try:
    from google import genai as _genai_new
    _SDK = "new"
except ImportError:
    try:
        import google.generativeai as _genai_legacy
        _SDK = "legacy"
    except ImportError:
        _SDK = None

try:
    from ollama_engine import OllamaEngine as _OllamaEngine
    _OLLAMA_OK = True
except ImportError:
    _OllamaEngine = None  # type: ignore[assignment,misc]
    _OLLAMA_OK = False

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Constantes
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Constantes
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Lista de modelos em ordem de preferÃªncia â€” o primeiro disponÃ­vel Ã© usado.
# gemini-2.0-flash Ã© o modelo atual (funciona em v1 e v1beta).
# gemini-1.5-flash-latest Ã© fallback para contas sem acesso ao 2.0.
MODELOS_FALLBACK = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash",
    "gemini-pro",
]

MODELO_PADRAO    = "gemini-2.0-flash"
MAX_TENTATIVAS   = 5
BACKOFF_BASE     = 10   # segundos (10, 20, 40, 80, 160)
RATE_LIMIT_PAUSA = 1.5  # segundos entre chamadas (evita 429)
MAX_TOKENS       = 1024
FASE2_MAX_TOKENS_PADRAO = 500
FASE2_TEXTO_MAX_PADRAO = 900
FASE2_COMMIT_LOTE_PADRAO = 15


def _env_int(nome: str, padrao: int) -> int:
    try:
        valor = int(os.getenv(nome, str(padrao)))
        return valor if valor > 0 else padrao
    except Exception:
        return padrao


FASE2_MAX_TOKENS = _env_int("IA_FASE2_MAX_TOKENS", FASE2_MAX_TOKENS_PADRAO)
FASE2_TEXTO_MAX = _env_int("IA_FASE2_TEXTO_MAX_CHARS", FASE2_TEXTO_MAX_PADRAO)
FASE2_COMMIT_LOTE = _env_int("IA_FASE2_COMMIT_LOTE", FASE2_COMMIT_LOTE_PADRAO)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _str_lista(lst) -> list:
    """Normaliza lista que pode conter strings ou dicts para lista de strings simples.

    Ollama Ã s vezes retorna [{"nome": "NBR 5410"}] em vez de ["NBR 5410"].
    Esta funÃ§Ã£o garante que sempre retornamos strings, independente do formato.
    """
    resultado = []
    for item in (lst or []):
        if isinstance(item, str):
            s = item.strip()
        elif isinstance(item, dict):
            # Procura a primeira string nÃ£o-vazia em chaves semÃ¢nticas comuns
            s = next(
                (v.strip() for v in item.values() if isinstance(v, str) and v.strip()),
                ""
            )
        elif item is not None:
            s = str(item).strip()
        else:
            s = ""
        if s:
            resultado.append(s)
    return resultado


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# IntegradorIA
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class IntegradorIA:
    """
    Gerencia comunicaÃ§Ã£o com a IA para Fase 1 (opcional) e Fase 3 (bloqueadora).

    Uso bÃ¡sico:
        integrador = IntegradorIA(api_key="...", db_path="banco_pericial.db")

        # Verificar disponibilidade
        if integrador.is_available():
            integrador.processar_fase1(doc_dict, laudo_id)

        # Fase 3 (bloqueadora â€” usar dentro de retry loop do orquestrador)
        integrador.processar_fase3()
    """

    def __init__(
        self,
        api_key: str = "",
        db_path: str = "",
        modelo: str = MODELO_PADRAO,
        log: Optional[GerenciadorLog] = None,
        ollama_url: str = "http://localhost:11434",
        modelo_fase1: str = "llama3.2:3b",
        modelo_fase2: str = "mistral:7b",
    ):
        self.api_key      = api_key
        self.db_path      = os.path.abspath(db_path) if db_path else _DB_PADRAO
        self.modelo       = modelo
        self.log          = log or GerenciadorLog.obter_instancia()
        self.ollama_url   = ollama_url
        self.modelo_fase1 = modelo_fase1
        self.modelo_fase2 = modelo_fase2
        self._ultimo_call = 0.0
        self._client: Any = None
        self._ollama: Any = None
        self._inicializar_cliente()

    # â”€â”€â”€ InicializaÃ§Ã£o â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _inicializar_cliente(self) -> None:
        # â”€â”€ Gemini (API externa) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if self.api_key and _SDK:
            try:
                if _SDK == "new":
                    # ForÃ§ar api_version="v1" evita o erro
                    # "not found for API version v1beta" que ocorre com
                    # gemini-1.5-flash no SDK google-genai >= 1.0
                    try:
                        self._client = _genai_new.Client(
                            api_key=self.api_key,
                            http_options={"api_version": "v1"},
                        )
                    except TypeError:
                        # VersÃµes antigas do SDK nÃ£o aceitam http_options
                        self._client = _genai_new.Client(api_key=self.api_key)
                    # Detectar modelo disponÃ­vel automaticamente
                    self.modelo = self._detectar_modelo()
                else:
                    _genai_legacy.configure(api_key=self.api_key)
                    self._client = _genai_legacy.GenerativeModel(self.modelo)
            except Exception as e:
                self.log.warning(f"[IntegradorIA] Falha ao inicializar Gemini: {e}")
                self._client = None

        # â”€â”€ Ollama (IA local, sem API) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if _OLLAMA_OK:
            try:
                engine = _OllamaEngine(url=self.ollama_url)
                if engine.disponivel and engine.modelo:
                    self._ollama = engine
                    self.log.info(
                        f"[IntegradorIA] Ollama disponivel: {engine.modelo}"
                    )
                else:
                    self.log.info(
                        f"[IntegradorIA] Ollama nao encontrado em {self.ollama_url}"
                    )
            except Exception as e:
                self.log.warning(f"[IntegradorIA] Erro ao inicializar Ollama: {e}")

    def _detectar_modelo(self) -> str:
        """
        Testa os modelos da lista MODELOS_FALLBACK e retorna o primeiro
        que responder com sucesso. Evita o erro 404 por nome de modelo errado.
        """
        if not self._client:
            return MODELO_PADRAO
        for modelo in MODELOS_FALLBACK:
            try:
                if _SDK == "new":
                    from google.genai import types as _t
                    self._client.models.generate_content(
                        model=modelo,
                        contents="ok",
                        config=_t.GenerateContentConfig(max_output_tokens=1),
                    )
                else:
                    m = _genai_legacy.GenerativeModel(modelo)
                    m.generate_content(
                        "ok",
                        generation_config={"max_output_tokens": 1},
                    )
                self.log.info(f"[IntegradorIA] Modelo selecionado: {modelo}")
                return modelo
            except Exception:
                continue
        self.log.warning(
            f"[IntegradorIA] Nenhum modelo do fallback respondeu. "
            f"Usando '{MODELO_PADRAO}' mesmo assim."
        )
        return MODELO_PADRAO

    # â”€â”€â”€ VerificaÃ§Ã£o de disponibilidade â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def is_available(self) -> bool:
        """
        Verifica se algum provedor de IA estÃ¡ disponÃ­vel (Gemini ou Ollama local).

        Testa Gemini primeiro (se api_key configurada), depois Ollama.

        Returns:
            True se pelo menos um provedor respondeu com sucesso.
        """
        # Verificar Gemini (API externa)
        if self.api_key and self._client:
            try:
                resposta = self._chamar_ia("ok", max_tokens=5)
                if resposta is not None:
                    return True
            except Exception:
                pass

        # Verificar Ollama (IA local)
        if self._ollama is not None:
            return self._ollama.disponivel and bool(self._ollama.modelo)

        return False

    # â”€â”€â”€ UtilitÃ¡rios de erro â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _extrair_retry_delay(msg_erro: str) -> int:
        """
        Extrai o retryDelay sugerido pela API Gemini em erros 429.
        Exemplo: 'Please retry in 36.396059883s.' â†’ 37

        Returns:
            Segundos a aguardar (mÃ­nimo 5, mÃ¡ximo 120). PadrÃ£o 30 se nÃ£o encontrado.
        """
        import re as _re
        m = _re.search(r"retry[^\d]*(\d+(?:\.\d+)?)\s*s", msg_erro, _re.IGNORECASE)
        if m:
            return min(120, max(5, int(float(m.group(1))) + 1))
        return 30

    @staticmethod
    def _eh_quota_esgotada(msg_erro: str) -> bool:
        """Retorna True para erros 429 RESOURCE_EXHAUSTED (cota esgotada)."""
        return "429" in msg_erro or "RESOURCE_EXHAUSTED" in msg_erro

    @staticmethod
    def _eh_modelo_invalido(msg_erro: str) -> bool:
        """Retorna True para erros 404 NOT_FOUND (modelo nÃ£o existe)."""
        return "404" in msg_erro or "NOT_FOUND" in msg_erro

    # â”€â”€â”€ Chamada base Ã  IA (com rate limit e troca de modelo) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _chamar_ia(
        self,
        prompt: str,
        sistema: str = "",
        max_tokens: int = MAX_TOKENS,
    ) -> Optional[str]:
        """
        Executa uma chamada Ã  IA com rate limiting.
        Em caso de 429 (cota), espera o retryDelay da API e tenta o prÃ³ximo modelo.
        Em caso de 404 (modelo invÃ¡lido), troca de modelo imediatamente.

        Returns:
            Texto da resposta ou None em caso de erro irrecuperÃ¡vel.
        """
        # Rate limiting
        agora = time.time()
        delta = agora - self._ultimo_call
        if delta < RATE_LIMIT_PAUSA:
            time.sleep(RATE_LIMIT_PAUSA - delta)
        self._ultimo_call = time.time()

        conteudo = f"{sistema}\n\n{prompt}" if sistema else prompt

        try:
            if _SDK == "new" and self._client:
                from google.genai import types as _types
                resp = self._client.models.generate_content(
                    model=self.modelo,
                    contents=conteudo,
                    config=_types.GenerateContentConfig(
                        max_output_tokens=max_tokens,
                        temperature=0.1,
                    ),
                )
                return resp.text if resp and resp.text else None

            elif _SDK == "legacy" and self._client:
                resp = self._client.generate_content(
                    conteudo,
                    generation_config={"max_output_tokens": max_tokens, "temperature": 0.1},
                )
                return resp.text if resp and resp.text else None

        except Exception as e:
            msg = str(e)

            # 429 â€” cota esgotada: respeitar retryDelay da API e tentar prÃ³ximo modelo
            if self._eh_quota_esgotada(msg):
                delay = self._extrair_retry_delay(msg)
                self.log.warning(
                    f"[IntegradorIA] Cota esgotada para '{self.modelo}'. "
                    f"Aguardando {delay}s sugeridos pela API..."
                )
                time.sleep(delay)
                # Tentar prÃ³ximo modelo disponÃ­vel
                proximo = self._proximo_modelo()
                if proximo:
                    self.log.info(
                        f"[IntegradorIA] Trocando modelo: '{self.modelo}' â†’ '{proximo}'"
                    )
                    self.modelo = proximo
                return None  # sinaliza para _chamar_com_retry tentar novamente

            # 404 â€” modelo nÃ£o existe: trocar imediatamente, sem espera
            if self._eh_modelo_invalido(msg):
                proximo = self._proximo_modelo()
                if proximo:
                    self.log.warning(
                        f"[IntegradorIA] Modelo '{self.modelo}' nÃ£o encontrado. "
                        f"Trocando para '{proximo}'."
                    )
                    self.modelo = proximo
                else:
                    self.log.error("[IntegradorIA] Nenhum modelo alternativo disponÃ­vel.")
                return None

            # Outros erros
            self.log.warning(f"[IntegradorIA] Falha na chamada Ã  IA: {msg[:200]}")
            return None

        # â”€â”€ Fallback: Ollama local â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if self._ollama is not None:
            resultado = self._ollama.gerar(prompt=conteudo, max_tokens=max_tokens)
            if resultado:
                return resultado

        return None

    def _proximo_modelo(self) -> Optional[str]:
        """
        Retorna o prÃ³ximo modelo da lista MODELOS_FALLBACK apÃ³s o atual.
        Retorna None se jÃ¡ estiver no Ãºltimo.
        """
        try:
            idx = MODELOS_FALLBACK.index(self.modelo)
            if idx + 1 < len(MODELOS_FALLBACK):
                return MODELOS_FALLBACK[idx + 1]
        except ValueError:
            # Modelo atual nÃ£o estÃ¡ na lista â€” comeÃ§a do inÃ­cio
            if MODELOS_FALLBACK:
                return MODELOS_FALLBACK[0]
        return None

    def _chamar_com_retry(
        self,
        prompt: str,
        sistema: str = "",
        max_tokens: int = MAX_TOKENS,
        max_tentativas: int = MAX_TENTATIVAS,
    ) -> Optional[str]:
        """
        Chamada Ã  IA com retry inteligente:
          - 429 (cota): aguarda retryDelay da API + troca modelo automaticamente
          - 404 (modelo): troca modelo imediatamente
          - Outros: backoff exponencial (10s â†’ 20s â†’ 40s â†’ 80s â†’ 160s)

        Returns:
            Texto da resposta ou None apÃ³s todas as tentativas.
        """
        for tentativa in range(1, max_tentativas + 1):
            modelo_antes = self.modelo
            resposta = self._chamar_ia(prompt, sistema, max_tokens)

            if resposta:
                return resposta

            # Se trocou de modelo, nÃ£o conta como tentativa extra
            if self.modelo != modelo_antes:
                self.log.info(
                    f"[IntegradorIA] Modelo trocado para '{self.modelo}'. "
                    f"Tentativa {tentativa}/{max_tentativas} continua."
                )
                # Tentar imediatamente com o novo modelo (sem espera adicional)
                resposta = self._chamar_ia(prompt, sistema, max_tokens)
                if resposta:
                    return resposta

            # Backoff exponencial para outros erros
            if tentativa < max_tentativas:
                espera = min(BACKOFF_BASE * (2 ** (tentativa - 1)), 120)
                self.log.warning(
                    f"[IntegradorIA] Tentativa {tentativa}/{max_tentativas} falhou. "
                    f"Aguardando {espera}s."
                )
                time.sleep(espera)

        self.log.error(
            f"[IntegradorIA] Todas as {max_tentativas} tentativas falharam. "
            f"Ãšltimo modelo tentado: '{self.modelo}'."
        )
        return None

    # â”€â”€â”€ Fase 1 com IA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def processar_fase1(
        self,
        doc: Dict[str, str],
        laudo_id: int,
        topicos_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        Enriquece tÃ³picos da Fase 1 com anÃ¡lise IA.
        Se a IA falhar, registra para reprocessamento futuro (nÃ£o bloqueia).

        Args:
            doc: Dict do documento {'nome', 'caminho', 'tipo'}
            laudo_id: FK laudos.id
            topicos_ids: IDs especÃ­ficos para enriquecer (None = todos do laudo)

        Returns:
            Dict com contadores de sucesso e falha.
        """
        stats = {
            "enriquecidos": 0,
            "irrelevantes": 0,
            "revisao": 0,
            "falhas_ia": 0,
            "fallback_offline": 0,
            "prompts_refinamento": [],
        }

        if not self.is_available():
            self.log.warning("[IntegradorIA] Fase 1 IA: serviÃ§o indisponÃ­vel. Usando fallback.")
            stats["fallback_offline"] += 1
            return stats

        conn = self._conn()
        try:
            if topicos_ids:
                query = f"SELECT id, texto_original, palavras_chave FROM topicos WHERE id IN ({','.join('?'*len(topicos_ids))})"
                topicos = conn.execute(query, topicos_ids).fetchall()
            else:
                # Busca tÃ³picos que ainda NÃƒO foram processados pelo llama (Fase 1 IA).
                # Usa NOT EXISTS em laudos_estruturado para ser independente do status_processamento
                # legado (fase_3_ia, completo, etc. do sistema antigo).
                try:
                    topicos = conn.execute(
                        """SELECT t.id, t.texto_original, t.palavras_chave
                           FROM topicos t
                           WHERE t.laudo_id = ?
                           AND t.texto_original IS NOT NULL
                           AND length(t.texto_original) > 30
                           AND NOT EXISTS (
                               SELECT 1 FROM laudos_estruturado le
                               WHERE le.topico_id = t.id
                               AND le.processado_fase1 = 1
                           )
                           LIMIT 50""",
                        (laudo_id,)
                    ).fetchall()
                except Exception:
                    # Fallback: laudos_estruturado pode nÃ£o existir ainda
                    topicos = conn.execute(
                        """SELECT id, texto_original, palavras_chave
                           FROM topicos WHERE laudo_id = ?
                           AND texto_original IS NOT NULL
                           AND length(texto_original) > 30
                           LIMIT 50""",
                        (laudo_id,)
                    ).fetchall()
        finally:
            conn.close()

        conn2 = self._conn()
        try:
            topicos_com_hier = []
            for tid, texto, palavras in topicos:
                row_hier = conn2.execute(
                    "SELECT hierarquia FROM topicos WHERE id=?", (tid,)
                ).fetchone()
                hier = row_hier[0] if row_hier and row_hier[0] else ""
                topicos_com_hier.append((tid, texto, palavras, hier))
        finally:
            conn2.close()

        tipo_doc = doc.get("tipo", "") if isinstance(doc, dict) else ""
        total = len(topicos_com_hier)
        self.log.info(f"[IntegradorIA] Fase 1: laudo_id={laudo_id}, {total} tÃ³pico(s) para processar.")
        print(f"\n  [llama] Laudo ID {laudo_id} â€” {total} tÃ³pico(s) para anÃ¡lise IA")

        for idx, (tid, texto, palavras, hierarquia) in enumerate(topicos_com_hier, 1):
            # RÃ³tulo curto para exibiÃ§Ã£o (hierarquia ou inÃ­cio do texto)
            label = (hierarquia or texto or "")[:60].replace("\n", " ").strip()
            print(f"  [llama] {idx}/{total} | {label}")
            try:
                resultado = self._enriquecer_topico_fase1(texto or "", hierarquia, tipo_doc)
                if not resultado:
                    self._marcar_fallback(tid, "fase_1_offline")
                    stats["fallback_offline"] += 1
                    print(f"         â†’ ERRO (sem resposta IA)")
                    continue

                # â”€â”€ Mapear resultado do mÃ³dulo de controle de qualidade â”€â”€â”€â”€â”€â”€
                class_final  = resultado.get("classificacao_final", "")
                class_texto  = resultado.get("classificacao_texto", "")
                score_final  = float(resultado.get("score_final", 0.0))
                justificativa = resultado.get("justificativa", "")
                sugestao     = resultado.get("sugestao_uso", "")
                patologias   = resultado.get("patologias", [])
                normas       = resultado.get("normas", [])

                # DecisÃ£o de relevÃ¢ncia baseada no score e classificaÃ§Ã£o
                nao_utilizavel = (
                    class_final == "nao_utilizavel"
                    or class_texto == "inadequado"
                    or (class_texto == "introducao_generica" and score_final < 6)
                    or score_final < 4
                )

                if nao_utilizavel:
                    motivo = justificativa or f"{class_texto} (score={score_final:.1f})"
                    self._marcar_irrelevante(tid, motivo)
                    stats["irrelevantes"] += 1
                    print(f"         â†’ DESCARTADO [{class_texto}] score={score_final:.1f} | {motivo[:50]}")
                elif score_final < 7.5:
                    # uso_limitado ou uso_complementar â†’ salva com flag de revisÃ£o
                    self._salvar_enriquecimento_fase1(tid, laudo_id, resultado, status_override="fase_1_revisao")
                    stats["revisao"] += 1
                    if sugestao and "[descartar]" not in sugestao.lower():
                        stats["prompts_refinamento"].append({"topico_id": tid, "prompt": sugestao[:200]})
                    print(f"         â†’ REVISAO [{class_final}] score={score_final:.1f} | {class_texto}")
                else:
                    # uso_recomendado ou uso_essencial
                    self._salvar_enriquecimento_fase1(tid, laudo_id, resultado)
                    stats["enriquecidos"] += 1
                    print(f"         â†’ OK [{class_final}] score={score_final:.1f} | "
                          f"patologias={patologias[:2]} | normas={normas[:2]}")

            except Exception as e:
                self.log.error(f"[IntegradorIA] Erro Fase 1 tÃ³pico {tid}: {e}", exc_info=True)
                self._marcar_fallback(tid, "fase_1_offline")
                stats["falhas_ia"] += 1
                print(f"         â†’ ERRO: {str(e)[:60]}")

        return stats

    def _enriquecer_topico_fase1(self, texto: str, hierarquia: str = "", tipo_doc: str = "") -> Optional[Dict]:
        """
        VerificaÃ§Ã£o integrada de relevÃ¢ncia + qualidade + extraÃ§Ã£o estruturada (llama3.2:3b).

        O modelo decide em uma Ãºnica chamada:
          1. Se o texto Ã‰ RELEVANTE para o banco pericial
          2. Se a qualidade da extraÃ§Ã£o Ã© OK / PARCIAL / RUIM
          3. Extrai as entidades tÃ©cnicas (se relevante)
          4. Gera prompt de consulta para tÃ³picos com qualidade < OK

        Retorna dict com campo 'relevante' (bool) e 'qualidade' (str).
        Quando relevante=False â†’ chamador marca status 'fase_1_irrelevante'.
        Quando qualidade != OK â†’ chamador salva com prompt_refinamento preenchido.
        """
        if len(texto.strip()) < 30:
            return None

        # Limite ampliado para 2000 chars â€” suficiente para julgar o conteÃºdo
        # tÃ©cnico completo sem truncar a parte relevante do tÃ³pico
        texto_trunc = texto[:2000]
        hier_label  = hierarquia[:120] if hierarquia else "nao informado"
        tipo_label  = tipo_doc or "nao informado"

        # â”€â”€ MÃ“DULO DE CONTROLE DE QUALIDADE TEXTUAL E CLASSIFICAÃ‡ÃƒO TÃ‰CNICA â”€â”€
        # Regra crÃ­tica: texto original NÃƒO Ã© modificado.
        # AnÃ¡lise retorna APENAS metadados de qualidade + entidades extraÃ­das.
        prompt = (
            f"DOC: {tipo_label} | SECAO: {hier_label}\n"
            f"TEXTO:\n{texto_trunc}\n\n"
            f"Retorne APENAS o JSON abaixo preenchido, sem texto antes ou depois:\n"
            f'{{"classificacao_texto":"","qualidade_tecnica":0,"grau_fundamentacao":0,'
            f'"aplicabilidade_pericial":0,"classificacao_final":"","score_final":0.0,'
            f'"justificativa":"","sugestao_uso":"",'
            f'"patologias":[],"estruturas":[],"materiais":[],"locais":[],'
            f'"normas":[],"palavras_chave_primarias":[],"palavras_chave_secundarias":[],'
            f'"titulo_sugerido":""}}\n\n'
            f"classificacao_texto: introducao_generica|conceitual|descritivo|tecnico_explicativo|normativo|metodologico|inadequado\n"
            f"qualidade_tecnica/grau_fundamentacao/aplicabilidade_pericial: 0-10\n"
            f"score_final=(0.4*aplicabilidade)+(0.3*fundamentacao)+(0.3*qualidade)\n"
            f"classificacao_final: <4=nao_utilizavel|4-6=uso_limitado|6-7.5=uso_complementar|7.5-9=uso_recomendado|>9=uso_essencial\n"
            f"Se introducao_generica ou inadequado E score<6: nao_utilizavel\n"
            f"patologias/estruturas/materiais/locais/normas: listas de strings simples extraidas do texto (ex: [\"fissura\",\"NBR 6118\"]) â€” NUNCA objetos JSON\n"
            f"palavras_chave_primarias: 3-5 strings simples em portugues (ex: [\"impermeabilizacao\",\"laje\"]) â€” NUNCA objetos\n"
            f"titulo_sugerido: max 60 chars em portugues"
        )

        sistema = (
            "VocÃª Ã© um especialista em engenharia civil e perÃ­cia tÃ©cnica brasileira. "
            "Analise o trecho tÃ©cnico fornecido e responda EXCLUSIVAMENTE em portuguÃªs brasileiro. "
            "Retorne APENAS um JSON vÃ¡lido, sem texto antes ou depois, sem markdown, sem explicaÃ§Ãµes."
        )

        if self._ollama:
            resposta = self._ollama.gerar_rapido(prompt, sistema, max_tokens=350)
        else:
            resposta = self._chamar_ia(prompt, sistema, max_tokens=350)

        if not resposta:
            return None

        return self._parsear_json(resposta, "Fase 1 verificacao+extracao")

    def _salvar_enriquecimento_fase1(
        self, topico_id: int, laudo_id: int, dados: Dict, status_override: str = ""
    ) -> None:
        """
        Salva extraÃ§Ã£o completa da Fase 1:
        - topicos: palavras-chave, titulo, sumÃ¡rio, status
        - laudos_estruturado: registro estruturado completo
        """
        conn = self._conn()
        modelo_f1 = self._ollama.modelo_rapido if self._ollama else self.modelo_fase1
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        try:
            # â”€â”€ Atualizar topicos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            pks_primarias   = _str_lista(dados.get("palavras_chave_primarias", []))
            pks_secundarias = _str_lista(dados.get("palavras_chave_secundarias", []))
            todas_pks = list(dict.fromkeys(pks_primarias + pks_secundarias))  # deduplica

            status_proc  = status_override if status_override else "fase_1_ia"
            score_final  = float(dados.get("score_final", 0.0))
            # Mapeamento score â†’ ia_score_confianca (0.0-1.0)
            ia_score = min(1.0, score_final / 10.0)
            updates: Dict[str, Any] = {
                "status_processamento": status_proc,
                "ia_score_confianca":   ia_score,
                "ia_modelo":   modelo_f1,
                "ia_timestamp": ts,
            }
            if dados.get("titulo_sugerido"):
                updates["titulo_topico"] = dados["titulo_sugerido"][:500]
            # INTEGRIDADE: NÃƒO sobrescrever texto_reescrito â€” preserva conteÃºdo original
            if todas_pks:
                existente = conn.execute(
                    "SELECT palavras_chave FROM topicos WHERE id=?", (topico_id,)
                ).fetchone()
                base = existente[0] if existente and existente[0] else ""
                novo = ", ".join(todas_pks[:15])
                updates["palavras_chave"] = f"{base}, {novo}".strip(", ") if base else novo

            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn.execute(f"UPDATE topicos SET {set_clause} WHERE id=?",
                         list(updates.values()) + [topico_id])

            # â”€â”€ Inserir/atualizar laudos_estruturado â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            existente_est = conn.execute(
                "SELECT id FROM laudos_estruturado WHERE topico_id=?", (topico_id,)
            ).fetchone()

            campos = {
                "laudo_id":                 laudo_id,
                "topico_id":                topico_id,
                "patologias":               json.dumps(_str_lista(dados.get("patologias", [])),    ensure_ascii=False),
                "estruturas":               json.dumps(_str_lista(dados.get("estruturas", [])),    ensure_ascii=False),
                "materiais":                json.dumps(_str_lista(dados.get("materiais", [])),     ensure_ascii=False),
                "locais":                   json.dumps(_str_lista(dados.get("locais", [])),        ensure_ascii=False),
                "normas_identificadas":     json.dumps(_str_lista(dados.get("normas", [])),        ensure_ascii=False),
                "palavras_chave_primarias": json.dumps(pks_primarias,                  ensure_ascii=False),
                "palavras_chave_secundarias": json.dumps(pks_secundarias,              ensure_ascii=False),
                "titulo_sugerido":          dados.get("titulo_sugerido", ""),
                "sumario":                  dados.get("justificativa", ""),  # anÃ¡lise tÃ©cnica, nÃ£o reescrita
                # Campos do mÃ³dulo de controle de qualidade
                "classificacao_texto":      dados.get("classificacao_texto", ""),
                "score_qualidade":          float(dados.get("qualidade_tecnica", 0)),
                "score_fundamentacao":      float(dados.get("grau_fundamentacao", 0)),
                "score_aplicabilidade":     float(dados.get("aplicabilidade_pericial", 0)),
                "classificacao_uso":        dados.get("classificacao_final", ""),
                "justificativa_qualidade":  dados.get("justificativa", ""),
                "sugestao_uso":             dados.get("sugestao_uso", ""),
                # Mapeamento legado
                "confianca_extracao":       (
                    "ALTA"  if score_final >= 7.5 else
                    "MEDIA" if score_final >= 4.0 else "BAIXA"
                ),
                "status_relevancia":        status_proc,
                "motivo_irrelevancia":      dados.get("justificativa", "") if status_proc == "fase_1_revisao" else "",
                "prompt_refinamento":       dados.get("sugestao_uso", ""),
                "modelo_fase1":             modelo_f1,
                "processado_fase1":         1,
                "timestamp_fase1":          ts,
            }

            if existente_est:
                set_cl = ", ".join(f"{k}=?" for k in campos if k not in ("laudo_id","topico_id"))
                vals   = [v for k, v in campos.items() if k not in ("laudo_id","topico_id")]
                conn.execute(
                    f"UPDATE laudos_estruturado SET {set_cl} WHERE topico_id=?",
                    vals + [topico_id]
                )
            else:
                cols = ", ".join(campos.keys())
                phs  = ", ".join("?" * len(campos))
                conn.execute(f"INSERT INTO laudos_estruturado ({cols}) VALUES ({phs})",
                             list(campos.values()))

            # â”€â”€ Registrar normas em contextos_normativos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            for norma in _str_lista(dados.get("normas", []))[:5]:
                norma = norma.strip()
                if len(norma) >= 3:
                    existe = conn.execute(
                        "SELECT id FROM contextos_normativos WHERE norma=? AND laudo_origem_id=?",
                        (norma, laudo_id)
                    ).fetchone()
                    if not existe:
                        conn.execute(
                            "INSERT INTO contextos_normativos (norma, descricao, laudo_origem_id, confianca) "
                            "VALUES (?,?,?,?)",
                            (norma, f"Referenciada em tÃ³pico: {dados.get('titulo_sugerido','')}", laudo_id, "MEDIA")
                        )

            conn.commit()
        except Exception as e:
            self.log.error(f"[IntegradorIA] Falha ao salvar enriquecimento Fase 1: {e}")
            conn.rollback()
        finally:
            conn.close()

    # â”€â”€â”€ Fase 2 com IA (mistral:7b) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def processar_fase2_ia(
        self,
        limite: int = 100,
    ) -> Dict[str, Any]:
        """
        Fase 2 IA: refinamento semÃ¢ntico com mistral:7b.

        Reanalisa itens com confianÃ§a < ALTA, valida normas, detecta causas
        raiz, mapeia relaÃ§Ãµes entre patologias e gera score de risco.

        Returns:
            Dict com contadores refinados, falhas e confianÃ§a mÃ©dia.
        """
        if not self.is_available():
            raise RuntimeError("[IntegradorIA] Fase 2 IA requer Ollama disponÃ­vel.")

        self.log.info("[IntegradorIA] Fase 2 IA: refinamento com mistral iniciado.")
        stats: Dict[str, Any] = {"refinados": 0, "falhas": 0, "confiancas": []}
        inicio = time.perf_counter()
        lote_commit = max(1, FASE2_COMMIT_LOTE)

        conn = self._conn()
        try:
            # Buscar itens com confianÃ§a nÃ£o-ALTA ou sem processamento fase 2
            rows = conn.execute(
                """SELECT le.id, le.topico_id, le.laudo_id,
                          le.patologias, le.estruturas, le.normas_identificadas,
                          le.sumario, le.confianca_extracao,
                          t.texto_original, t.hierarquia
                   FROM laudos_estruturado le
                   JOIN topicos t ON t.id = le.topico_id
                   WHERE le.processado_fase1 = 1
                     AND le.processado_fase2 = 0
                     AND (le.confianca_extracao != 'ALTA' OR le.score_risco = '')
                   ORDER BY
                     CASE le.confianca_extracao
                       WHEN 'BAIXA'  THEN 1
                       WHEN 'MEDIA'  THEN 2
                       ELSE 3
                     END
                   LIMIT ?""",
                (limite,)
            ).fetchall()

            total = len(rows)
            self.log.info(
                "[IntegradorIA] Fase 2 IA: %s tÃ³pico(s) para refinar. "
                "tokens=%s texto_max=%s commit_lote=%s",
                total,
                FASE2_MAX_TOKENS,
                FASE2_TEXTO_MAX,
                lote_commit,
            )
            if total == 0:
                stats["confianca_media"] = 0.0
                stats["duracao_s"] = round(time.perf_counter() - inicio, 2)
                return stats

            laudo_ids = sorted({int(row[2]) for row in rows if row[2] is not None})
            normas_cache = self._carregar_normas_cache(conn, laudo_ids)

            for idx, row in enumerate(rows, 1):
                est_id, topico_id, laudo_id, patologias_j, estruturas_j, normas_j, \
                    sumario, confianca, texto, hierarquia = row
                try:
                    resultado = self._refinar_topico_fase2(
                        texto or "", hierarquia or "", sumario or "",
                        patologias_j, normas_j, confianca
                    )
                    if resultado:
                        conn.execute("SAVEPOINT f2_item")
                        try:
                            self._salvar_refinamento_fase2_conn(
                                conn=conn,
                                est_id=est_id,
                                topico_id=topico_id,
                                laudo_id=laudo_id,
                                dados=resultado,
                                normas_cache=normas_cache,
                            )
                            conn.execute("RELEASE SAVEPOINT f2_item")
                            stats["refinados"] += 1
                            stats["confiancas"].append(resultado.get("confianca_refinada", 0.0))
                        except Exception:
                            conn.execute("ROLLBACK TO SAVEPOINT f2_item")
                            conn.execute("RELEASE SAVEPOINT f2_item")
                            raise
                    else:
                        stats["falhas"] += 1
                except Exception as e:
                    self.log.error(f"[IntegradorIA] Fase 2 IA erro tÃ³pico {topico_id}: {e}")
                    stats["falhas"] += 1

                if idx % lote_commit == 0:
                    conn.commit()

                if idx == total or idx % 10 == 0:
                    decorrido = time.perf_counter() - inicio
                    media_item = decorrido / idx
                    eta = max(0.0, media_item * (total - idx))
                    self.log.info(
                        "[IntegradorIA] Fase 2 progresso: %s/%s | refinados=%s | falhas=%s | "
                        "decorrido=%.1fs | eta=%.1fs",
                        idx,
                        total,
                        stats["refinados"],
                        stats["falhas"],
                        decorrido,
                        eta,
                    )

            conn.commit()
        finally:
            conn.close()

        stats["confianca_media"] = (
            sum(stats["confiancas"]) / len(stats["confiancas"])
            if stats["confiancas"] else 0.0
        )
        stats["duracao_s"] = round(time.perf_counter() - inicio, 2)
        self.log.info(
            f"[IntegradorIA] Fase 2 IA concluÃ­da. "
            f"Refinados: {stats['refinados']} | Falhas: {stats['falhas']} | "
            f"Conf.mÃ©dia: {stats['confianca_media']:.2f} | "
            f"DuraÃ§Ã£o: {stats['duracao_s']:.1f}s"
        )
        return stats

    def _refinar_topico_fase2(
        self,
        texto: str,
        hierarquia: str,
        sumario_fase1: str,
        patologias_json: str,
        normas_json: str,
        confianca_fase1: str,
    ) -> Optional[Dict]:
        """
        Refinamento semÃ¢ntico profundo com mistral:7b.
        Valida normas, detecta causa raiz, mapeia relaÃ§Ãµes, gera score de risco.
        """
        if len(texto.strip()) < 30:
            return None

        try:
            patologias = json.loads(patologias_json or "[]")
            normas     = json.loads(normas_json or "[]")
        except Exception:
            patologias, normas = [], []

        prompt = (
            f"Refine a anÃ¡lise tÃ©cnica pericial do tÃ³pico abaixo.\n\n"
            f"HIERARQUIA: {hierarquia}\n"
            f"CONFIANÃ‡A FASE 1: {confianca_fase1}\n"
            f"PATOLOGIAS IDENTIFICADAS: {', '.join(patologias) or 'nenhuma'}\n"
            f"NORMAS IDENTIFICADAS: {', '.join(normas) or 'nenhuma'}\n"
            f"SUMÃRIO FASE 1: {sumario_fase1}\n\n"
            f"TEXTO COMPLETO:\n{texto[:FASE2_TEXTO_MAX]}\n\n"
            f"Exemplo de resposta correta:\n"
            f'{{"causa_raiz":"CarbonataÃ§Ã£o do concreto com reduÃ§Ã£o do pH abaixo de 9,5",'
            f'"nexo_causal":"A carbonataÃ§Ã£o despassivou a armadura, iniciando processo '
            f'corrosivo que gerou expansÃ£o das barras e fissuraÃ§Ã£o do cobrimento.",'
            f'"relacoes_patologicas":["desplacamento de cobrimento","manchas de ferrugem"],'
            f'"score_risco":"ALTO","normas_validadas":["NBR 6118","NBR 6209"],'
            f'"recomendacao":"Remover concreto carbonatado, tratar armadura com inibidor '
            f'e aplicar concreto de reparo com fck >= 30 MPa.",'
            f'"confianca_refinada":0.85,"enriquecimento":"Vida Ãºtil de reparo: 15-20 anos"}}\n\n'
            f"Retorne APENAS o JSON vÃ¡lido preenchido, sem markdown, sem texto antes ou depois:\n"
            f'{{"causa_raiz":"","nexo_causal":"",'
            f'"relacoes_patologicas":[],"score_risco":"BAIXO",'
            f'"normas_validadas":[],"recomendacao":"",'
            f'"confianca_refinada":0.0,"enriquecimento":""}}\n\n'
            f"DefiniÃ§Ãµes:\n"
            f"- causa_raiz: causa tÃ©cnica principal objetiva em portuguÃªs (1 frase)\n"
            f"- nexo_causal: explicaÃ§Ã£o do mecanismo de dano em portuguÃªs (2-3 frases)\n"
            f"- relacoes_patologicas: outras anomalias relacionadas ex: ['recalque','fissura']\n"
            f"- score_risco: BAIXO/MEDIO/ALTO/CRITICO (impacto estrutural/seguranÃ§a)\n"
            f"- normas_validadas: normas ABNT/NBR confirmadas ou novas ex: ['NBR 6118']\n"
            f"- recomendacao: aÃ§Ã£o corretiva tÃ©cnica em portuguÃªs (2-3 frases)\n"
            f"- confianca_refinada: 0.0-1.0 (0.8=alta confianÃ§a, 0.5=mÃ©dia)\n"
            f"- enriquecimento: informaÃ§Ã£o adicional sobre prazos/custos/tÃ©cnicas em portuguÃªs"
        )

        sistema = (
            "VocÃª Ã© um engenheiro perito judicial especialista em patologias construtivas, "
            "normas ABNT/NBR e IBAPE 2025. Realize refinamento semÃ¢ntico profundo. "
            "Responda EXCLUSIVAMENTE em portuguÃªs brasileiro. "
            "Retorne APENAS JSON vÃ¡lido, sem texto fora do JSON."
        )

        if self._ollama:
            resposta = self._ollama.gerar_qualidade(prompt, sistema, max_tokens=FASE2_MAX_TOKENS)
        else:
            resposta = self._chamar_ia(prompt, sistema, max_tokens=FASE2_MAX_TOKENS)

        if not resposta:
            return None

        return self._parsear_json(resposta, "Fase 2 refinamento")

    def _carregar_normas_cache(
        self,
        conn: sqlite3.Connection,
        laudo_ids: List[int],
    ) -> Dict[int, set[str]]:
        cache: Dict[int, set[str]] = {}
        if not laudo_ids:
            return cache

        placeholders = ",".join("?" for _ in laudo_ids)
        rows = conn.execute(
            f"SELECT laudo_origem_id, norma FROM contextos_normativos "
            f"WHERE laudo_origem_id IN ({placeholders})",
            laudo_ids,
        ).fetchall()
        for lid, norma in rows:
            if lid is None:
                continue
            chave = (norma or "").strip().lower()
            if not chave:
                continue
            if lid not in cache:
                cache[lid] = set()
            cache[lid].add(chave)
        return cache

    def _salvar_refinamento_fase2_conn(
        self,
        conn: sqlite3.Connection,
        est_id: int,
        topico_id: int,
        laudo_id: int,
        dados: Dict,
        normas_cache: Optional[Dict[int, set[str]]] = None,
    ) -> None:
        """Persiste refinamento da Fase 2 reutilizando conexao ja aberta."""
        modelo_f2 = self._ollama.modelo_qualidade if self._ollama else self.modelo_fase2
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        updates_est: Dict[str, Any] = {
            "causa_raiz":          dados.get("causa_raiz", ""),
            "nexo_causal":         dados.get("nexo_causal", ""),
            "relacoes_patologicas": json.dumps(dados.get("relacoes_patologicas", []), ensure_ascii=False),
            "score_risco":         dados.get("score_risco", "BAIXO"),
            "recomendacao":        dados.get("recomendacao", ""),
            "confianca_refinada":  float(dados.get("confianca_refinada", 0.0)),
            "modelo_fase2":        modelo_f2,
            "processado_fase2":    1,
            "timestamp_fase2":     ts,
        }

        normas_val = _str_lista(dados.get("normas_validadas", []))
        if normas_val:
            updates_est["normas_identificadas"] = json.dumps(normas_val, ensure_ascii=False)

        set_cl = ", ".join(f"{k}=?" for k in updates_est)
        conn.execute(
            f"UPDATE laudos_estruturado SET {set_cl} WHERE id=?",
            list(updates_est.values()) + [est_id],
        )

        updates_top: Dict[str, Any] = {
            "status_processamento": "fase_3_ia",
            "ia_score_confianca":   float(dados.get("confianca_refinada", 0.0)),
            "ia_modelo":            modelo_f2,
            "ia_timestamp":         ts,
        }
        if dados.get("nexo_causal"):
            updates_top["gut_nexo_json"] = json.dumps(
                {
                    "nexo_causal": dados["nexo_causal"],
                    "causa_raiz": dados.get("causa_raiz", ""),
                },
                ensure_ascii=False,
            )
        if dados.get("recomendacao"):
            atual = conn.execute(
                "SELECT texto_reescrito FROM topicos WHERE id=?",
                (topico_id,),
            ).fetchone()
            base = atual[0] if atual and atual[0] else ""
            updates_top["texto_reescrito"] = (
                f"{base}\n\nRecomendacao: {dados['recomendacao']}".strip()
            )

        set_cl2 = ", ".join(f"{k}=?" for k in updates_top)
        conn.execute(
            f"UPDATE topicos SET {set_cl2} WHERE id=?",
            list(updates_top.values()) + [topico_id],
        )

        if normas_cache is None:
            normas_cache = {}
        cache_laudo = normas_cache.setdefault(int(laudo_id), set())
        for norma in normas_val[:5]:
            norma = (norma or "").strip()
            if len(norma) < 3:
                continue
            chave_norma = norma.lower()
            if chave_norma in cache_laudo:
                continue
            conn.execute(
                "INSERT INTO contextos_normativos "
                "(norma, descricao, aplicacao, laudo_origem_id, confianca) "
                "VALUES (?,?,?,?,?)",
                (norma, dados.get("nexo_causal", ""), dados.get("recomendacao", ""), laudo_id, "ALTA"),
            )
            cache_laudo.add(chave_norma)

    def _salvar_refinamento_fase2(
        self, est_id: int, topico_id: int, laudo_id: int, dados: Dict
    ) -> None:
        """Mantem compatibilidade: salva refinamento Fase 2 em conexao dedicada."""
        conn = self._conn()
        try:
            self._salvar_refinamento_fase2_conn(
                conn=conn,
                est_id=est_id,
                topico_id=topico_id,
                laudo_id=laudo_id,
                dados=dados,
                normas_cache=None,
            )
            conn.commit()
        except Exception as e:
            self.log.error(f"[IntegradorIA] Falha ao salvar refinamento Fase 2: {e}")
            conn.rollback()
        finally:
            conn.close()

    def _parsear_json(self, resposta: str, contexto: str) -> Optional[Dict]:
        """
        Parseia JSON da resposta da IA com trÃªs tentativas progressivas:
        1. json.loads direto apÃ³s limpeza de markdown
        2. ExtraÃ§Ã£o do bloco { ... } mais externo
        3. ReconstruÃ§Ã£o campo a campo via regex (Ãºltimo recurso)
        Retorna None apenas se nenhuma tentativa extrair qualquer dado Ãºtil.
        """
        if not resposta or not resposta.strip():
            return None

        limpa = resposta.strip()

        # Tentativa 1: remover blocos markdown e parsear
        if "```" in limpa:
            partes = limpa.split("```")
            for p in partes:
                p = p.strip()
                if p.startswith("json"):
                    p = p[4:]
                p = p.strip()
                if p.startswith("{"):
                    limpa = p
                    break

        inicio = limpa.find("{")
        fim    = limpa.rfind("}")
        if inicio != -1 and fim != -1:
            candidato = limpa[inicio:fim + 1]
            try:
                return json.loads(candidato)
            except json.JSONDecodeError:
                # Tentativa 2: consertar JSON truncado adicionando chaves/colchetes faltando
                try:
                    abertos_ch = candidato.count("{") - candidato.count("}")
                    abertos_col = candidato.count("[") - candidato.count("]")
                    reparado = candidato + ("]" * max(0, abertos_col)) + ("}" * max(0, abertos_ch))
                    return json.loads(reparado)
                except json.JSONDecodeError:
                    pass

        # Tentativa 3: reconstruÃ§Ã£o campo a campo via regex
        campos_extraidos: Dict[str, Any] = {}
        # Strings: "chave": "valor"
        for m in re.finditer(r'"(\w+)"\s*:\s*"([^"]*)"', limpa):
            campos_extraidos[m.group(1)] = m.group(2)
        # NÃºmeros: "chave": 7.5
        for m in re.finditer(r'"(\w+)"\s*:\s*(-?\d+(?:\.\d+)?)', limpa):
            if m.group(1) not in campos_extraidos:
                try:
                    campos_extraidos[m.group(1)] = float(m.group(2))
                except ValueError:
                    pass
        # Listas simples: "chave": ["a","b"]
        for m in re.finditer(r'"(\w+)"\s*:\s*\[([^\]]*)\]', limpa):
            if m.group(1) not in campos_extraidos:
                itens = re.findall(r'"([^"]+)"', m.group(2))
                campos_extraidos[m.group(1)] = itens

        if campos_extraidos:
            campos_extraidos["parse_falhou"] = True
            self.log.warning(
                f"[IntegradorIA] JSON parcial ({contexto}): {list(campos_extraidos.keys())} | "
                f"resp: {resposta[:80]}"
            )
            return campos_extraidos

        self.log.warning(
            f"[IntegradorIA] JSON invÃ¡lido ({contexto}) â€” sem campos recuperÃ¡veis | "
            f"resp: {resposta[:100]}"
        )
        return None

    # â”€â”€â”€ Fase 3 com IA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def processar_fase3(
        self,
        analisador=None,
        validador=None,
        limite_por_chamada: int = 10,
    ) -> Dict[str, Any]:
        """
        Fase 3: Refinamento semÃ¢ntico completo com IA (BLOQUEADORA).
        Processa tÃ³picos prioritÃ¡rios identificados pelo AnalisadorCompletude.

        Args:
            analisador: InstÃ¢ncia de AnalisadorCompletude (opcional)
            validador:  InstÃ¢ncia de ValidadorDados (opcional)
            limite_por_chamada: TÃ³picos por lote de chamada IA

        Returns:
            Dict com contadores de refinamentos e confianÃ§a mÃ©dia.

        Raises:
            RuntimeError: Se IA estiver completamente indisponÃ­vel.
        """
        if not self.is_available():
            raise RuntimeError(
                "[IntegradorIA] Fase 3 requer IA disponÃ­vel â€” indisponÃ­vel no momento."
            )

        self.log.info("[IntegradorIA] Fase 3: Refinamento semÃ¢ntico com IA iniciado.")
        stats = {
            "topicos_refinados": 0,
            "classificacoes": 0,
            "falhas": 0,
            "confiancas": [],
        }

        # Obter lista de tÃ³picos prioritÃ¡rios
        if analisador:
            topico_ids = analisador.topicos_prioritarios_ia(limite=200)
        else:
            topico_ids = self._listar_topicos_fase3()

        self.log.info(f"[IntegradorIA] Fase 3: {len(topico_ids)} tÃ³pico(s) para refinar.")

        # Processar em lotes
        for i in range(0, len(topico_ids), limite_por_chamada):
            lote = topico_ids[i:i + limite_por_chamada]
            for tid in lote:
                try:
                    resultado = self._refinar_topico_fase3(tid)
                    if resultado:
                        self._salvar_refinamento_fase3(tid, resultado)
                        stats["topicos_refinados"] += 1
                        stats["classificacoes"] += 1
                        conf = resultado.get("confianca", 0.0)
                        stats["confiancas"].append(conf)
                    else:
                        stats["falhas"] += 1
                except Exception as e:
                    self.log.error(
                        f"[IntegradorIA] Erro Fase 3 tÃ³pico {tid}: {e}", exc_info=True
                    )
                    stats["falhas"] += 1

        # Calcular confianÃ§a mÃ©dia
        if stats["confiancas"]:
            stats["confianca_media"] = sum(stats["confiancas"]) / len(stats["confiancas"])
        else:
            stats["confianca_media"] = 0.0

        self.log.info(
            "[IntegradorIA] Fase 3 concluÃ­da.",
            refinados=str(stats["topicos_refinados"]),
            falhas=str(stats["falhas"]),
            confianca=f"{stats.get('confianca_media', 0):.2f}",
        )
        return stats

    def _refinar_topico_fase3(self, topico_id: int) -> Optional[Dict]:
        """
        Refinamento semÃ¢ntico profundo de um Ãºnico tÃ³pico via IA.

        IMPORTANTE: Esta fase realiza enriquecimento semÃ¢ntico do texto
        (sumÃ¡rio, nexo causal, normas relacionadas) para melhorar a recuperaÃ§Ã£o
        no banco de dados. ClassificaÃ§Ã£o de grau_risco, tipo_anomalia e
        origem_patologica NÃƒO Ã© realizada aqui â€” sÃ£o responsabilidade exclusiva
        das anÃ¡lises de imagem, GUT e IBAPE realizadas pelo perito.
        """
        conn = self._conn()
        try:
            row = conn.execute(
                """SELECT texto_original, titulo_topico, hierarquia, palavras_chave
                   FROM topicos WHERE id=?""",
                (topico_id,)
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return None

        texto, titulo, hierarquia, palavras = row
        texto_base = texto or titulo or ""
        if len(texto_base.strip()) < 30:
            return None

        prompt = (
            f"Analise o trecho tÃ©cnico pericial abaixo. Contexto: '{hierarquia}'.\n\n"
            f"TEXTO:\n{texto_base[:1000]}\n\n"
            f"Responda SOMENTE com JSON (sem markdown):\n"
            f'{{"nexo_causal":"","recomendacao_tecnica":"",'
            f'"normas_relacionadas":[],"palavras_chave":[],'
            f'"sumario_executivo":"","confianca":0.0}}\n\n'
            f"InstruÃ§Ãµes:\n"
            f"- nexo_causal: causa raiz tÃ©cnica objetiva (1 frase)\n"
            f"- recomendacao_tecnica: aÃ§Ã£o corretiva recomendada (1-2 frases)\n"
            f"- normas_relacionadas: normas ABNT/IBAPE aplicÃ¡veis ex. ['NBR 6118']\n"
            f"- palavras_chave: 5-10 termos tÃ©cnicos adicionais para indexaÃ§Ã£o\n"
            f"- sumario_executivo: 2-3 frases descritivas para o relatÃ³rio\n"
            f"- confianca: 0.0 a 1.0 (certeza na anÃ¡lise)"
        )

        sistema = (
            "VocÃª Ã© um engenheiro perito judicial especialista em patologias "
            "construtivas, NBR/ABNT e IBAPE. Seu papel Ã© enriquecer o conteÃºdo "
            "tÃ©cnico para recuperaÃ§Ã£o no banco de dados. "
            "Retorne APENAS JSON vÃ¡lido, sem classificar gravidade ou risco."
        )

        resposta = self._chamar_com_retry(prompt, sistema, max_tokens=500)
        if not resposta:
            return None

        try:
            limpa = resposta.strip()
            if limpa.startswith("```"):
                limpa = limpa.split("```")[1]
                if limpa.startswith("json"):
                    limpa = limpa[4:]
            return json.loads(limpa.strip())
        except json.JSONDecodeError:
            self.log.warning(
                f"[IntegradorIA] JSON invÃ¡lido Fase 3 tÃ³pico {topico_id}: {resposta[:100]}"
            )
            return None

    def _salvar_refinamento_fase3(self, topico_id: int, dados: Dict) -> None:
        """
        Persiste refinamento semÃ¢ntico da Fase 3 no banco.

        Apenas sumÃ¡rio, palavras-chave adicionais e referÃªncias normativas
        sÃ£o gravados. Campos de classificaÃ§Ã£o (grau_risco, tipo_anomalia,
        origem_patologica, mecanismo) sÃ£o preservados como estÃ£o â€” nÃ£o sÃ£o
        alterados pelo reprocessamento automÃ¡tico.
        """
        conn = self._conn()
        try:
            updates: Dict[str, Any] = {
                "status_processamento": "fase_3_ia",
                "ia_score_confianca":   float(dados.get("confianca", 0.0)),
                "ia_modelo":            self.modelo,
                "ia_timestamp":         time.strftime("%Y-%m-%d %H:%M:%S"),
            }

            # Enriquecer sumÃ¡rio executivo (texto_reescrito)
            if dados.get("sumario_executivo"):
                updates["texto_reescrito"] = dados["sumario_executivo"]

            # Enriquecer palavras-chave acumulando as existentes
            if dados.get("palavras_chave"):
                pks_novas = ", ".join(dados["palavras_chave"][:10])
                pks_existente = conn.execute(
                    "SELECT palavras_chave FROM topicos WHERE id=?", (topico_id,)
                ).fetchone()
                if pks_existente and pks_existente[0]:
                    updates["palavras_chave"] = pks_existente[0] + ", " + pks_novas
                else:
                    updates["palavras_chave"] = pks_novas

            set_clause = ", ".join(f"{k}=?" for k in updates)
            vals = list(updates.values()) + [topico_id]
            conn.execute(f"UPDATE topicos SET {set_clause} WHERE id=?", vals)

            # Salvar normas e recomendaÃ§Ã£o em parametros_normativos
            laudo_id = conn.execute(
                "SELECT laudo_id FROM topicos WHERE id=?", (topico_id,)
            ).fetchone()
            if laudo_id:
                lid = laudo_id[0]
                for norma in dados.get("normas_relacionadas", [])[:5]:
                    conn.execute(
                        """INSERT OR IGNORE INTO parametros_normativos
                           (laudo_id, topico_id, parametro, valor, contexto)
                           VALUES (?,?,?,?,?)""",
                        (lid, topico_id, "norma_ref", norma,
                         dados.get("recomendacao_tecnica", ""))
                    )

            conn.commit()
        except Exception as e:
            self.log.error(f"[IntegradorIA] Falha ao salvar refinamento Fase 3: {e}")
        finally:
            conn.close()

    def _listar_topicos_fase3(self, limite: int = 200) -> List[int]:
        """Lista tÃ³picos que ainda nÃ£o passaram pela Fase 3."""
        conn = self._conn()
        try:
            rows = conn.execute(
                """SELECT id FROM topicos
                   WHERE status_processamento NOT IN ('fase_3_ia', 'completo')
                     AND texto_original IS NOT NULL
                     AND length(texto_original) > 50
                   ORDER BY id LIMIT ?""",
                (limite,)
            ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []
        finally:
            conn.close()

    def _marcar_fallback(self, topico_id: int, status: str) -> None:
        """Marca tÃ³pico como fallback offline (IA falhou)."""
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE topicos SET status_processamento=?, ia_score_confianca=0.0 WHERE id=?",
                (status, topico_id)
            )
            # Insere sentinela em laudos_estruturado para que o NOT EXISTS
            # da prÃ³xima iteraÃ§Ã£o exclua este tÃ³pico e evite loop infinito
            conn.execute("""
                INSERT INTO laudos_estruturado
                    (topico_id, laudo_id, processado_fase1, confianca_extracao, status_relevancia)
                SELECT ?, laudo_id, 1, 'FALLBACK', ?
                FROM topicos WHERE id=?
                  AND NOT EXISTS (
                      SELECT 1 FROM laudos_estruturado WHERE topico_id=?
                  )
            """, (topico_id, status, topico_id, topico_id))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def _marcar_irrelevante(self, topico_id: int, motivo: str) -> None:
        """Marca tÃ³pico como irrelevante (filtrado pela IA na Fase 1)."""
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE topicos SET status_processamento='fase_1_irrelevante', "
                "ia_score_confianca=0.0 WHERE id=?",
                (topico_id,)
            )
            # Insere sentinela em laudos_estruturado para que o NOT EXISTS
            # da prÃ³xima iteraÃ§Ã£o exclua este tÃ³pico e evite loop infinito
            conn.execute("""
                INSERT INTO laudos_estruturado
                    (topico_id, laudo_id, processado_fase1, confianca_extracao, status_relevancia)
                SELECT ?, laudo_id, 1, 'IRRELEVANTE', 'fase_1_irrelevante'
                FROM topicos WHERE id=?
                  AND NOT EXISTS (
                      SELECT 1 FROM laudos_estruturado WHERE topico_id=?
                  )
            """, (topico_id, topico_id, topico_id))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    # â”€â”€â”€ UtilitÃ¡rios â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


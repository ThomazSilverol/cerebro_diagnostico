"""
ollama_engine.py — Motor de IA Local via Ollama
Sistema: Cérebro de Engenharia Diagnóstica

Suporte a dois modelos especializados:
  • MODELO_RAPIDO  (padrão: llama3.2:3b) — Fase 1, extração inicial, rápido
  • MODELO_QUALIDADE (padrão: mistral:7b) — Fase 2, refinamento semântico, preciso

Inclui geração de embeddings locais para busca semântica.
"""

import json
import logging
from typing import List, Optional

import requests

_log = logging.getLogger(__name__)

OLLAMA_URL_PADRAO    = "http://localhost:11434"
TIMEOUT_GERAR        = 90    # llama3.2:3b ~10-25s por chamada | mistral:7b ~40-60s
TIMEOUT_EMBEDDING    = 60
TIMEOUT_CHECK        = 3

# Atribuição de modelos por papel
MODELO_RAPIDO_PADRAO    = "llama3.2:3b"   # Fase 1 — extração rápida
MODELO_QUALIDADE_PADRAO = "mistral:7b"    # Fase 2 — refinamento semântico

# Fallback automático se o modelo preferido não estiver instalado
MODELOS_PREFERIDOS_RAPIDO = ["llama3.2", "phi3", "phi4", "llama3.1", "gemma2"]
MODELOS_PREFERIDOS_QUALIDADE = ["mistral", "llama3.1", "qwen2.5", "gemma2", "llama3.2"]


class OllamaEngine:
    """
    Cliente para modelos locais via Ollama com suporte a dois modelos especializados.

    modelo_rapido    → Fase 1 (extração inicial, llama3.2:3b por padrão)
    modelo_qualidade → Fase 2 (refinamento semântico, mistral:7b por padrão)

    Uso:
        engine = OllamaEngine()
        if engine.disponivel:
            # Fase 1 — rápido
            resp = engine.gerar_rapido("Analise: ...")
            # Fase 2 — qualidade
            resp = engine.gerar_qualidade("Refine: ...")
            # Embedding local
            vetor = engine.gerar_embedding("texto para vetorizar")
    """

    def __init__(
        self,
        url: str = OLLAMA_URL_PADRAO,
        modelo: str = "",                           # compatibilidade legada
        modelo_rapido: str = MODELO_RAPIDO_PADRAO,
        modelo_qualidade: str = MODELO_QUALIDADE_PADRAO,
    ):
        self.url = url.rstrip("/")
        self._modelo_solicitado   = modelo          # legado
        self._modelo_rapido_cfg   = modelo_rapido
        self._modelo_qualidade_cfg = modelo_qualidade
        self._modelo_rapido_ativo:    str = ""
        self._modelo_qualidade_ativo: str = ""
        self._disponivel: Optional[bool] = None

    # ─── Disponibilidade ──────────────────────────────────────────────────────

    @property
    def disponivel(self) -> bool:
        if self._disponivel is None:
            self._disponivel = self._verificar_servidor()
        return self._disponivel

    # Legado — usa modelo rápido por padrão
    @property
    def modelo(self) -> str:
        return self.modelo_rapido

    @property
    def modelo_rapido(self) -> str:
        if not self._modelo_rapido_ativo:
            self._modelo_rapido_ativo = self._resolver_modelo(
                self._modelo_rapido_cfg, MODELOS_PREFERIDOS_RAPIDO
            )
        return self._modelo_rapido_ativo

    @property
    def modelo_qualidade(self) -> str:
        if not self._modelo_qualidade_ativo:
            self._modelo_qualidade_ativo = self._resolver_modelo(
                self._modelo_qualidade_cfg, MODELOS_PREFERIDOS_QUALIDADE
            )
        return self._modelo_qualidade_ativo

    # ─── Verificação ──────────────────────────────────────────────────────────

    def _verificar_servidor(self) -> bool:
        try:
            resp = requests.get(f"{self.url}/api/tags", timeout=TIMEOUT_CHECK)
            return resp.status_code == 200
        except Exception:
            return False

    def listar_modelos(self) -> List[str]:
        try:
            resp = requests.get(f"{self.url}/api/tags", timeout=TIMEOUT_CHECK)
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []

    def _resolver_modelo(self, preferido: str, ordem_fallback: List[str]) -> str:
        """Resolve o modelo a usar: preferido → fallback por ordem → primeiro instalado."""
        instalados = self.listar_modelos()
        if not instalados:
            return ""
        # Tentar o modelo configurado exatamente
        for inst in instalados:
            if preferido.split(":")[0] in inst.lower():
                _log.info("[OllamaEngine] Modelo resolvido: %s -> %s", preferido, inst)
                return inst
        # Fallback por lista de preferência
        for pref in ordem_fallback:
            for inst in instalados:
                if pref in inst.lower():
                    _log.info("[OllamaEngine] Fallback: %s -> %s", preferido, inst)
                    return inst
        return instalados[0]

    def invalidar_cache(self) -> None:
        self._disponivel = None
        self._modelo_rapido_ativo = ""
        self._modelo_qualidade_ativo = ""

    # ─── Geração de texto ─────────────────────────────────────────────────────

    def gerar(
        self,
        prompt: str,
        sistema: str = "",
        max_tokens: int = 1024,
        modelo: str = "",
    ) -> Optional[str]:
        """Gera texto com o modelo especificado (ou o rápido por padrão)."""
        modelo_usar = modelo or self.modelo_rapido
        return self._chamar_generate(modelo_usar, prompt, sistema, max_tokens)

    def gerar_rapido(self, prompt: str, sistema: str = "", max_tokens: int = 1024) -> Optional[str]:
        """Gera texto com o modelo rápido (Fase 1 — llama3.2:3b).
        temperature=0.0: respostas determinísticas para extração estruturada.
        """
        return self._chamar_generate(
            self.modelo_rapido, prompt, sistema, max_tokens,
            temperature=0.0, num_ctx=4096
        )

    def gerar_qualidade(self, prompt: str, sistema: str = "", max_tokens: int = 1500) -> Optional[str]:
        """Gera texto com o modelo de qualidade (Fase 2 — mistral:7b).
        temperature=0.1: leve variabilidade para refinamento semântico mais rico.
        repeat_penalty=1.15: reduz repetição de termos.
        """
        return self._chamar_generate(
            self.modelo_qualidade, prompt, sistema, max_tokens,
            temperature=0.1, num_ctx=8192, repeat_penalty=1.15
        )

    def _chamar_generate(
        self,
        modelo: str,
        prompt: str,
        sistema: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.0,
        num_ctx: int = 4096,
        repeat_penalty: float = 1.0,
    ) -> Optional[str]:
        if not self.disponivel or not modelo:
            return None

        conteudo = f"{sistema}\n\n{prompt}" if sistema else prompt
        try:
            options: dict = {
                "num_predict": max_tokens,
                "num_ctx": num_ctx,   # Corrigido: era 1024 (insuficiente para textos técnicos)
                "temperature": temperature,
                "top_p": 0.9,
            }
            if repeat_penalty != 1.0:
                options["repeat_penalty"] = repeat_penalty

            payload = {
                "model": modelo,
                "prompt": conteudo,
                "stream": False,
                "options": options,
            }
            resp = requests.post(
                f"{self.url}/api/generate", json=payload, timeout=TIMEOUT_GERAR
            )
            if resp.status_code == 200:
                resultado = resp.json().get("response", "").strip()
                return resultado if resultado else None
            _log.warning("[OllamaEngine] HTTP %s com '%s': %s", resp.status_code, modelo, resp.text[:120])
        except requests.exceptions.Timeout:
            _log.warning("[OllamaEngine] Timeout com '%s' (%ss)", modelo, TIMEOUT_GERAR)
        except Exception as e:
            _log.warning("[OllamaEngine] Erro ao gerar com '%s': %s", modelo, e)
        return None

    # ─── Embeddings locais ────────────────────────────────────────────────────

    def gerar_embedding(self, texto: str, modelo: str = "") -> List[float]:
        """
        Gera vetor de embedding local via Ollama.

        Usa o modelo rápido por padrão (llama3.2:3b).
        Retorna lista vazia se falhar.
        """
        modelo_usar = modelo or self.modelo_rapido
        if not self.disponivel or not modelo_usar:
            return []
        try:
            payload = {"model": modelo_usar, "prompt": texto[:2000]}
            resp = requests.post(
                f"{self.url}/api/embeddings", json=payload, timeout=TIMEOUT_EMBEDDING
            )
            if resp.status_code == 200:
                return resp.json().get("embedding", [])
        except Exception as e:
            _log.warning("[OllamaEngine] Embedding falhou com '%s': %s", modelo_usar, e)
        return []

    # ─── Informações ──────────────────────────────────────────────────────────

    def instrucoes_instalacao(self) -> str:
        return (
            "\n"
            "  Ollama nao encontrado em http://localhost:11434\n"
            "  Para usar IA local:\n\n"
            "  1. Baixe: https://ollama.com/download\n"
            "  2. Execute:\n"
            "     ollama pull llama3.2:3b   (Fase 1 - rapido)\n"
            "     ollama pull mistral:7b    (Fase 2 - qualidade)\n"
            "  3. Reinicie o programa.\n"
        )

    def resumo(self) -> str:
        if not self.disponivel:
            return "Ollama: indisponivel"
        return (
            f"Ollama: disponivel | "
            f"F1={self.modelo_rapido} | "
            f"F2={self.modelo_qualidade} | "
            f"modelos={len(self.listar_modelos())}"
        )

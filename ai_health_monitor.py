"""
ai_health_monitor.py — Monitor de Saúde da IA e Cache de Embeddings
Sistema: Cérebro de Engenharia Diagnóstica v2.0
Versão: 1.0 — Tolerância a Falhas + Modo Offline Garantido

Componentes:
  • AIHealthMonitor  — Verificação proativa de disponibilidade da IA
  • EmbeddingCache   — Cache L1 (memória) + L2 (SQLite), TTL 24h

Referência: Seções 3–5 do Prompt de Arquitetura Resiliente Offline-First v1.0
Princípio: "Nunca parar. Sempre degradar graciosamente."
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("ai_health_monitor")

# Silenciar libs externas barulhentas (httpx, google SDK) — logs vão para arquivo, não terminal
for _lib_noisy in ("httpx", "httpcore", "google", "google.generativeai", "urllib3"):
    logging.getLogger(_lib_noisy).setLevel(logging.WARNING)


# =============================================================================
# SINGLETON GLOBAL — acessível por todos os módulos via import
# =============================================================================
_MONITOR_GLOBAL: Optional["AIHealthMonitor"] = None


def obter_monitor() -> Optional["AIHealthMonitor"]:
    """Retorna a instância global do AIHealthMonitor (None se não inicializado)."""
    return _MONITOR_GLOBAL


def inicializar_monitor(config: Dict[str, Any]) -> "AIHealthMonitor":
    """
    Inicializa (ou reinicializa) o monitor global.
    Deve ser chamado uma vez na startup do sistema.
    """
    global _MONITOR_GLOBAL
    _MONITOR_GLOBAL = AIHealthMonitor(config)
    return _MONITOR_GLOBAL


# =============================================================================
# AIHealthMonitor
# =============================================================================

class AIHealthMonitor:
    """
    Monitor de saúde da IA — verificação proativa e contínua.
    Usado por todos os módulos para decidir o modo de operação.

    Ref: Princípio [A3] — saber antes de precisar.

    Exemplo de uso:
        monitor = AIHealthMonitor({"gemini_api_key": os.getenv("GEMINI_API_KEY")})
        status  = monitor.verificar_saude()
        if monitor.eh_online():
            # modo completo
        else:
            # modo offline
    """

    TTL_CHECK_SEGUNDOS = 300  # re-verificar a cada 5 minutos

    def __init__(self, config: Dict[str, Any]):
        self.api_key: str = config.get("gemini_api_key", "") or ""
        self._ultimo_check: Optional[float] = None
        self._status_atual: str = "desconhecido"
        self._cache: Dict[str, Any] = {}
        self._lock = threading.Lock()

    # ─── API Pública ─────────────────────────────────────────────────────────

    def verificar_saude(self, forcar: bool = False) -> Dict[str, Any]:
        """
        Verifica disponibilidade da IA de forma não-bloqueante.
        Resultado cacheado por TTL para evitar latência repetida.

        Args:
            forcar: Se True, ignora cache e força nova verificação.

        Returns:
            {
                "disponivel":  bool,
                "modo":        "completo" | "offline",
                "motivo":      str,
                "latencia_ms": int | None
            }
        """
        with self._lock:
            agora = time.time()
            cache_valido = (
                not forcar
                and self._ultimo_check is not None
                and (agora - self._ultimo_check) < self.TTL_CHECK_SEGUNDOS
            )
            if cache_valido:
                return self._cache.get("ultimo_resultado", self._resultado_offline("cache válido"))

            resultado = self._executar_check()
            self._ultimo_check = agora
            self._cache["ultimo_resultado"] = resultado
            self._status_atual = resultado["modo"]
            logger.info(
                f"[HealthCheck] Modo: {resultado['modo']} | Motivo: {resultado['motivo']}"
            )
            return resultado

    def eh_online(self) -> bool:
        """Atalho booleano — uso rápido nos módulos."""
        return self.verificar_saude()["disponivel"]

    def aguardar_recuperacao(
        self,
        callback: Callable[[Dict[str, Any]], None],
        intervalo: int = 120,
    ) -> None:
        """
        Verifica periodicamente se a IA voltou online.
        Executa em thread daemon — não bloqueia o sistema.

        Args:
            callback: Chamado com o dict de status quando IA recuperar.
            intervalo: Segundos entre verificações (padrão: 120).
        """
        def _loop() -> None:
            while True:
                time.sleep(intervalo)
                resultado = self.verificar_saude(forcar=True)
                if resultado["disponivel"]:
                    logger.info("[HealthCheck] IA recuperada — modo completo ativo.")
                    try:
                        callback(resultado)
                    except Exception as exc:
                        logger.warning(f"Callback de recuperação falhou: {exc}")
                    break  # encerra o loop após recuperação

        thread = threading.Thread(target=_loop, daemon=True, name="HealthMonitor")
        thread.start()

    def exibir_status_startup(self) -> None:
        """
        Exibe status da IA UMA VEZ na inicialização do sistema.
        Verifica Gemini (API) e Ollama (local) separadamente.
        Só exibe aviso de "indisponível" se AMBOS estiverem inacessíveis.
        """
        status_gemini = self.verificar_saude()

        # Verificar Ollama separadamente
        ollama_info = ""
        try:
            from ollama_engine import OllamaEngine as _OllamaEngine
            _ol = _OllamaEngine()
            if _ol.disponivel:
                ollama_info = f"llama={_ol.modelo_rapido} | mistral={_ol.modelo_qualidade}"
        except Exception:
            pass

        if status_gemini["disponivel"]:
            lat = status_gemini.get("latencia_ms")
            lat_str = f" — latência: {lat}ms" if lat else ""
            print(f"  Gemini: configurado{lat_str}")
            if ollama_info:
                print(f"  Ollama: {ollama_info}")
        elif ollama_info:
            # Gemini ausente mas Ollama disponível — situação normal para uso local
            print(f"  Gemini: sem API key (opcional)")
            print(f"  Ollama: {ollama_info}")

            def _ao_recuperar(s: Dict[str, Any]) -> None:
                print(f"\n  Gemini recuperado. Digite [status] para confirmar.")

            self.aguardar_recuperacao(_ao_recuperar, intervalo=120)
        else:
            # Nem Gemini nem Ollama disponíveis
            print(f"  IA: indisponivel — {status_gemini['motivo']}")
            print(f"     Ollama: nao encontrado em localhost:11434")
            print(f"     Todas as funcoes offline continuam ativas.")
            print(f"     Para IA local: instale Ollama e execute 'ollama pull llama3.2:3b'")

            def _ao_recuperar(s: Dict[str, Any]) -> None:
                print(f"\n  IA recuperada. Digite [status] para confirmar.")

            self.aguardar_recuperacao(_ao_recuperar, intervalo=120)

    # ─── Privados ────────────────────────────────────────────────────────────

    def _executar_check(self) -> Dict[str, Any]:
        """Testa API com chamada mínima (1 token), tentando múltiplos modelos."""
        inicio = time.time()

        # Verificação 1: chave presente
        if not self.api_key or len(self.api_key.strip()) < 10:
            return self._resultado_offline("API key ausente ou muito curta")

        # Modelos a tentar, em ordem de preferência
        _modelos = [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash-latest",
            "gemini-1.5-flash-001",
            "gemini-1.5-flash",
            "gemini-pro",
        ]

        # Verificação 2: SDK disponível + teste real
        try:
            # Tentar SDK novo (google-genai >= 1.0)
            try:
                from google import genai as _genai_new
                from google.genai import types as _gt

                # Forçar api_version="v1" — evita erro "not found for API version v1beta"
                try:
                    client = _genai_new.Client(
                        api_key=self.api_key,
                        http_options={"api_version": "v1"},
                    )
                except TypeError:
                    client = _genai_new.Client(api_key=self.api_key)

                modelo_ok = None
                for modelo in _modelos:
                    try:
                        client.models.generate_content(
                            model=modelo,
                            contents="ok",
                            config=_gt.GenerateContentConfig(max_output_tokens=1),
                        )
                        modelo_ok = modelo
                        break
                    except Exception:
                        continue

                if modelo_ok:
                    latencia = int((time.time() - inicio) * 1000)
                    return {
                        "disponivel":  True,
                        "modo":        "completo",
                        "motivo":      f"API respondeu com sucesso (modelo: {modelo_ok})",
                        "latencia_ms": latencia,
                        "modelo":      modelo_ok,
                    }
                raise Exception("Nenhum modelo disponível no SDK novo.")

            except ImportError:
                pass  # Tentar SDK legado

            import google.generativeai as _genai_leg
            _genai_leg.configure(api_key=self.api_key)
            modelo_ok = None
            for modelo in _modelos:
                try:
                    m = _genai_leg.GenerativeModel(modelo)
                    m.generate_content("ok", generation_config={"max_output_tokens": 1})
                    modelo_ok = modelo
                    break
                except Exception:
                    continue

            if modelo_ok:
                latencia = int((time.time() - inicio) * 1000)
                return {
                    "disponivel":  True,
                    "modo":        "completo",
                    "motivo":      f"API respondeu (SDK legado, modelo: {modelo_ok})",
                    "latencia_ms": latencia,
                    "modelo":      modelo_ok,
                }
            raise Exception("Nenhum modelo disponível no SDK legado.")

        except Exception as exc:
            msg = str(exc)
            codigo = self._extrair_codigo_erro(msg)
            motivos = {
                "API_KEY_INVALID":   "Chave de API inválida ou expirada",
                "QUOTA_EXCEEDED":    "Cota de API excedida",
                "UNAVAILABLE":       "Serviço Gemini temporariamente indisponível",
                "PERMISSION_DENIED": "Permissão negada — verifique a chave",
            }
            motivo = motivos.get(codigo, f"Erro: {msg[:120]}")
            return self._resultado_offline(motivo)

    @staticmethod
    def _resultado_offline(motivo: str) -> Dict[str, Any]:
        return {
            "disponivel":  False,
            "modo":        "offline",
            "motivo":      motivo,
            "latencia_ms": None,
        }

    @staticmethod
    def _extrair_codigo_erro(mensagem: str) -> str:
        """Extrai código de erro estruturado da resposta da API."""
        # 429 tem prioridade — é diferente de chave inválida
        if "429" in mensagem or "RESOURCE_EXHAUSTED" in mensagem:
            return "QUOTA_EXCEEDED"
        match = re.search(r"'reason':\s*'([A-Z_]+)'", mensagem)
        if match:
            return match.group(1)
        for codigo in ("API_KEY_INVALID", "UNAVAILABLE", "PERMISSION_DENIED"):
            if codigo in mensagem.upper():
                return codigo
        return "UNKNOWN"


# =============================================================================
# EmbeddingCache — Cache em Dois Níveis
# =============================================================================

class EmbeddingCache:
    """
    Cache de embeddings em dois níveis:
      L1 — memória (dict, TTL 1h por sessão, invalidado ao reiniciar)
      L2 — SQLite  (tabela embedding_cache, TTL 24h, persiste entre sessões)

    Ref: Princípio [A4] — reduzir dependência de API.

    Exemplo de uso:
        cache = EmbeddingCache(conn)
        vetor = cache.obter("fissura estrutural")
        if vetor is None:
            vetor = ai_engine.gerar_embedding("fissura estrutural")
            cache.salvar("fissura estrutural", vetor)
    """

    TTL_L2_SEGUNDOS = 86400  # 24 horas

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._l1: Dict[str, List[float]] = {}
        self._inicializar_tabela()

    # ─── API Pública ─────────────────────────────────────────────────────────

    def obter(self, texto: str) -> Optional[List[float]]:
        """
        Busca embedding: L1 → L2 → None (cache miss).

        Em caso de miss, o chamador deve gerar e chamar salvar().
        """
        chave = self._hash(texto)

        # L1: memória
        if chave in self._l1:
            return self._l1[chave]

        # L2: banco SQLite
        try:
            row = self.conn.execute(
                "SELECT embedding_json, timestamp FROM embedding_cache "
                "WHERE query_hash = ?",
                (chave,),
            ).fetchone()

            if row:
                ts = datetime.fromisoformat(row[1])
                if (datetime.now() - ts).total_seconds() < self.TTL_L2_SEGUNDOS:
                    vetor: List[float] = json.loads(row[0])
                    self._l1[chave] = vetor  # promover para L1
                    try:
                        self.conn.execute(
                            "UPDATE embedding_cache SET hits = hits + 1 WHERE query_hash = ?",
                            (chave,),
                        )
                        self.conn.commit()
                    except Exception:
                        pass
                    return vetor
        except Exception as exc:
            logger.warning(f"[EmbeddingCache] Erro ao buscar L2: {exc}")

        return None  # cache miss

    def salvar(self, texto: str, vetor: List[float]) -> None:
        """Salva embedding nos dois níveis (L1 + L2)."""
        if not vetor:
            return
        chave = self._hash(texto)
        self._l1[chave] = vetor
        try:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO embedding_cache
                    (query_hash, query_texto, embedding_json, timestamp, hits)
                VALUES (?, ?, ?, ?, 0)
                """,
                (chave, texto[:500], json.dumps(vetor), datetime.now().isoformat()),
            )
            self.conn.commit()
        except Exception as exc:
            logger.warning(f"[EmbeddingCache] Erro ao salvar L2: {exc}")

    def limpar_expirados(self) -> int:
        """Remove entradas com TTL expirado (> 24h). Executar na startup."""
        try:
            cur = self.conn.execute(
                "DELETE FROM embedding_cache "
                "WHERE datetime(timestamp) < datetime('now', '-24 hours')"
            )
            self.conn.commit()
            removidos = cur.rowcount
            if removidos > 0:
                logger.info(f"[EmbeddingCache] {removidos} entrada(s) expirada(s) removidas.")
            return removidos
        except Exception as exc:
            logger.warning(f"[EmbeddingCache] Erro ao limpar expirados: {exc}")
            return 0

    def obter_estatisticas(self) -> Dict[str, Any]:
        """Retorna estatísticas do cache para o comando [status]."""
        try:
            total = self.conn.execute(
                "SELECT COUNT(*) FROM embedding_cache"
            ).fetchone()[0]
            hits_hoje = self.conn.execute(
                "SELECT COALESCE(SUM(hits), 0) FROM embedding_cache "
                "WHERE date(timestamp) = date('now')"
            ).fetchone()[0]
            return {"total": total, "hits_hoje": hits_hoje, "l1_size": len(self._l1)}
        except Exception:
            return {"total": 0, "hits_hoje": 0, "l1_size": len(self._l1)}

    # ─── Privados ────────────────────────────────────────────────────────────

    def _inicializar_tabela(self) -> None:
        try:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    query_hash     TEXT    PRIMARY KEY,
                    query_texto    TEXT    NOT NULL,
                    embedding_json TEXT    NOT NULL,
                    timestamp      TEXT    NOT NULL,
                    hits           INTEGER DEFAULT 0
                )
            """)
            self.conn.commit()
        except Exception as exc:
            logger.warning(f"[EmbeddingCache] Falha ao criar tabela: {exc}")

    @staticmethod
    def _hash(texto: str) -> str:
        return hashlib.md5(texto.encode("utf-8")).hexdigest()


# =============================================================================
# AUTOCHECK — Testes de Resiliência (incorporados de test_resiliencia.py)
# Execução automática na startup ou via: python ai_health_monitor.py --autocheck
# =============================================================================

def executar_autocheck(conn: sqlite3.Connection = None, silencioso: bool = False) -> bool:
    """
    Executa os 7 testes de resiliência do sistema.
    Substitui o arquivo test_resiliencia.py — pode ser chamado na startup.

    Args:
        conn:       Conexão SQLite (opcional; usa :memory: se None)
        silencioso: Se True, suprime saída no console (apenas retorna bool)

    Returns:
        True se todos os testes passaram.

    Uso na startup (main.py ou orchestrator.py):
        from ai_health_monitor import executar_autocheck
        if not executar_autocheck(silencioso=True):
            print("Aviso: testes de resiliencia com falha — verificar logs.")
    """
    import traceback as _tb

    _conn_local = conn or sqlite3.connect(":memory:")
    resultados = []

    def _ok(nome, cond, detalhe=""):
        resultados.append((nome, cond, detalhe))
        if not silencioso:
            icone = "PASSOU" if cond else "FALHOU"
            print(f"  [{icone}]  {nome}")
            if detalhe:
                print(f"           {detalhe}")
        return cond

    # T1 — API key inválida → modo offline gracioso
    try:
        m = AIHealthMonitor({"gemini_api_key": "chave_invalida_xyz"})
        r = m.verificar_saude()
        _ok("T1 APIHealthMonitor key invalida", r["disponivel"] is False and r["modo"] == "offline",
            f"disponivel={r['disponivel']} modo={r['modo']}")
    except Exception as e:
        _ok("T1 APIHealthMonitor key invalida", False, str(e))

    # T2 — Sem chave → modo offline
    try:
        m = AIHealthMonitor({"gemini_api_key": ""})
        r = m.verificar_saude()
        _ok("T2 AIHealthMonitor sem chave", r["disponivel"] is False and r["modo"] == "offline",
            f"disponivel={r['disponivel']}")
    except Exception as e:
        _ok("T2 AIHealthMonitor sem chave", False, str(e))

    # T3 — EmbeddingCache L1/L2 sem rede
    try:
        cache = EmbeddingCache(_conn_local)
        vetor = [0.1, 0.2, 0.3, 0.4, 0.5]
        texto = "fissura estrutural em pilar de concreto armado"
        cache.salvar(texto, vetor)
        cache._l1.clear()
        v_l2 = cache.obter(texto)
        v_l1 = cache.obter(texto)
        ok = v_l2 is not None and abs(v_l2[0] - 0.1) < 1e-6 and v_l1 is not None
        _ok("T3 EmbeddingCache L1/L2", ok,
            f"L2={v_l2 is not None} L1={v_l1 is not None}")
    except Exception as e:
        _ok("T3 EmbeddingCache L1/L2", False, str(e))

    # T4 — GUT offline (cálculo sem IA)
    try:
        from gut_adaptativo import GUTAdaptativo, NexoCausal, OrigemNexo, MecanismoDegradacao, StatusAnomalia
        engine = GUTAdaptativo(conn=_conn_local, ai_engine=None)
        nexo = NexoCausal(origem=OrigemNexo.ENDOGENA_EXECUCAO,
                          mecanismo=MecanismoDegradacao.MECANICO,
                          status=StatusAnomalia.EM_OCORRENCIA)
        respostas = {k: 1.0 for k in ["G1","G2","G3","G4","U1","U2","U3","U4","T1","T2","T3","T4"]}
        respostas["T3"] = 0.60
        resultado = engine.calcular_score_offline(respostas, nexo)
        ok = all(k in resultado for k in ["G","U","T","prioridade"])
        _ok("T4 GUT calcular_score_offline", ok,
            f"G={resultado.get('G')} U={resultado.get('U')} T={resultado.get('T')}")
    except ImportError:
        _ok("T4 GUT calcular_score_offline", False, "gut_adaptativo.py nao encontrado")
    except Exception as e:
        _ok("T4 GUT calcular_score_offline", False, str(e))

    # T5 — Sessão GUT recuperada após crash
    try:
        from gut_adaptativo import GUTAdaptativo
        engine1 = GUTAdaptativo(conn=_conn_local, ai_engine=None)
        sid = "test-crash-001"
        engine1._salvar_etapa_parcial(sid, "G1", 0.80, descricao="Fissura em pilar P3")
        engine1._salvar_etapa_parcial(sid, "G2", 0.75)
        engine2 = GUTAdaptativo(conn=_conn_local, ai_engine=None)
        pend = engine2._verificar_sessao_pendente()
        ok = (pend is not None and pend["respostas"].get("G1") == 0.80
              and "Fissura" in pend.get("descricao",""))
        _ok("T5 Sessao GUT apos crash", ok,
            f"G1={pend['respostas'].get('G1') if pend else '-'}")
    except ImportError:
        _ok("T5 Sessao GUT apos crash", False, "gut_adaptativo.py nao encontrado")
    except Exception as e:
        _ok("T5 Sessao GUT apos crash", False, str(e))

    # T6 — Métodos obrigatórios existem
    try:
        from gut_adaptativo import GUTAdaptativo
        engine = GUTAdaptativo(conn=_conn_local, ai_engine=None)
        metodos = ["_exibir_resultado","_salvar_historico","_exibir_comparativo",
                   "_salvar_etapa_parcial","_verificar_sessao_pendente",
                   "_expirar_sessao","_retomar_sessao"]
        faltando = [m for m in metodos if not callable(getattr(engine, m, None))]
        _ok("T6 Metodos obrigatorios GUT", len(faltando) == 0,
            f"Faltando: {faltando}" if faltando else "Todos os 7 metodos encontrados")
    except ImportError:
        _ok("T6 Metodos obrigatorios GUT", False, "gut_adaptativo.py nao encontrado")
    except Exception as e:
        _ok("T6 Metodos obrigatorios GUT", False, str(e))

    # T7 — Cache miss retorna None
    try:
        cache = EmbeddingCache(_conn_local)
        resultado = cache.obter("texto que nao existe no cache xyz123")
        _ok("T7 EmbeddingCache miss retorna None", resultado is None, f"resultado={resultado}")
    except Exception as e:
        _ok("T7 EmbeddingCache miss gracioso", False, str(e))

    # Resultado final
    passou = sum(1 for _, ok, _ in resultados if ok)
    total  = len(resultados)
    if not silencioso:
        print(f"\n  RESULTADO: {passou}/{total} | {'TODOS PASSARAM' if passou == total else 'COM FALHAS'}")
    return passou == total


if __name__ == "__main__":
    import sys as _sys
    if "--autocheck" in _sys.argv:
        logging.basicConfig(level=logging.WARNING)
        print("\n  Executando autocheck de resiliencia...\n")
        ok = executar_autocheck(silencioso=False)
        _sys.exit(0 if ok else 1)

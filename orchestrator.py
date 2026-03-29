"""
orchestrator.py — Orquestrador + Monitor de Entrada (Reprocessamento Multifásico v1.0)
Sistema: Cérebro de Engenharia Diagnóstica

Consolida MonitorEntrada + OrquestradorReprocessamento em um único arquivo.

Uso:
    python orchestrator.py              # monitoramento contínuo
    python orchestrator.py --fase 2     # força Fase 2
    python orchestrator.py --fase 3     # força Fase 3 (requer IA)
    python orchestrator.py --status     # diagnóstico
    python orchestrator.py --relatorio  # completude por documento
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from log_manager import GerenciadorLog
from offline_extractor import ExtratorOffline
from quality_manager import QualityManager
from ia_integrator import IntegradorIA

PASTAS_ENTRADA  = {"doc": "doc_entrada",       "pdf": "pdf_entrada"}
PASTAS_SAIDA    = {"doc": "doc_processados",   "pdf": "pdf_processados"}
PASTA_ERROS     = "doc_erros"
EXTENSOES_DOC   = {".docx", ".txt", ".doc"}
EXTENSOES_PDF   = {".pdf"}
INTERVALO_LOOP  = 30
MAX_RETRIES_F3  = 5
BACKOFF_BASE_F3 = 60
DB_PATH         = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'banco_pericial.db')


class MonitorEntrada:
    """Monitor de pastas de entrada — polling sincrono (< 500ms)."""

    def __init__(self, log: Optional[GerenciadorLog] = None):
        self.log = log or GerenciadorLog.obter_instancia()
        for pasta in list(PASTAS_ENTRADA.values()) + list(PASTAS_SAIDA.values()) + [PASTA_ERROS]:
            os.makedirs(pasta, exist_ok=True)

    def verificar_entrada(self) -> bool:
        return len(self.listar_documentos()) > 0

    def pastas_vazias(self) -> bool:
        return not self.verificar_entrada()

    def listar_documentos(self) -> List[Dict]:
        docs: List[Dict] = []
        for tipo, pasta in PASTAS_ENTRADA.items():
            exts = EXTENSOES_DOC if tipo == "doc" else EXTENSOES_PDF
            try:
                for nome in os.listdir(pasta):
                    if Path(nome).suffix.lower() in exts:
                        cam = os.path.join(pasta, nome)
                        docs.append({"nome": nome, "caminho": cam, "tipo": tipo,
                                     "tamanho": os.path.getsize(cam)})
            except FileNotFoundError:
                os.makedirs(pasta, exist_ok=True)
            except Exception as e:
                self.log.warning(f"[Monitor] Erro ao listar '{pasta}': {e}")
        docs.sort(key=lambda d: d["tamanho"])
        return docs

    def listar_processados(self) -> List[Dict]:
        docs: List[Dict] = []
        for tipo, pasta in PASTAS_SAIDA.items():
            exts = EXTENSOES_DOC if tipo == "doc" else EXTENSOES_PDF
            try:
                for nome in os.listdir(pasta):
                    if Path(nome).suffix.lower() in exts:
                        docs.append({"nome": nome, "caminho": os.path.join(pasta, nome), "tipo": tipo})
            except FileNotFoundError:
                os.makedirs(pasta, exist_ok=True)
        return docs

    def mover_para_processados(self, doc: Dict) -> bool:
        destino_pasta = PASTAS_SAIDA.get(doc["tipo"])
        if not destino_pasta:
            return False
        destino = os.path.join(destino_pasta, doc["nome"])
        if os.path.exists(destino):
            base, ext = os.path.splitext(doc["nome"])
            destino = os.path.join(destino_pasta, f"{base}_{int(time.time())}{ext}")
        try:
            shutil.move(doc["caminho"], destino)
            self.log.info(f"[Monitor] → processados: {doc['nome']}")
            return True
        except Exception as e:
            self.log.error(f"[Monitor] Falha ao mover '{doc['nome']}': {e}")
            return False

    def mover_para_erros(self, doc: Dict, motivo: str = "") -> bool:
        destino = os.path.join(PASTA_ERROS, doc["nome"])
        if os.path.exists(destino):
            base, ext = os.path.splitext(doc["nome"])
            destino = os.path.join(PASTA_ERROS, f"{base}_{int(time.time())}{ext}")
        try:
            shutil.move(doc["caminho"], destino)
            self.log.warning(f"[Monitor] → erros: {doc['nome']} ({motivo[:80]})")
            return True
        except Exception as e:
            self.log.error(f"[Monitor] Falha ao mover para erros '{doc['nome']}': {e}")
            return False

    def estatisticas(self) -> Dict[str, int]:
        stats = {}
        for pasta in list(PASTAS_ENTRADA.values()) + list(PASTAS_SAIDA.values()) + [PASTA_ERROS]:
            try:
                stats[pasta] = len([f for f in os.listdir(pasta)
                                    if os.path.isfile(os.path.join(pasta, f))])
            except FileNotFoundError:
                stats[pasta] = 0
        return stats


class OrquestradorReprocessamento:
    """
    Coordenador do pipeline multifásico. NUNCA para por excecao interna.
    Estados: idle | fase_1 | fase_2 | fase_3 | aguardando_ia | erro
    """

    def __init__(self, db_path: str = DB_PATH, api_key: str = ""):
        self.db_path    = db_path
        self.api_key    = api_key or os.getenv("GEMINI_API_KEY", "")
        self.log        = GerenciadorLog.obter_instancia(db_path)
        self.monitor    = MonitorEntrada(log=self.log)
        self.extrator   = ExtratorOffline(db_path=db_path, log=self.log)
        self.quality    = QualityManager(db_path=db_path)
        self.integrador = IntegradorIA(api_key=self.api_key, db_path=db_path, log=self.log)
        self._estado    = "idle"
        self._ativo     = False
        self._retries3  = 0
        self._stats     = {"docs_fase1": 0, "topicos_fase2": 0, "topicos_fase3": 0,
                           "erros_total": 0, "ciclos_completos": 0}
        self.extrator._migrar_colunas_topicos()
        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, *_) -> None:
        print("\n\n  Encerrando ciclo atual...")
        self._ativo = False

    def iniciar(self) -> None:
        self._ativo = True
        self.log.info("[Orquestrador] Iniciado. IA: %s", "sim" if self.api_key else "nao")
        _banner()
        while self._ativo:
            try:
                self._ciclo()
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log.error(f"[Orquestrador] Erro: {e}", exc_info=True)
                self._stats["erros_total"] += 1
                time.sleep(INTERVALO_LOOP)
        self.log.info("[Orquestrador] Encerrado. %s", self._stats)

    def _ciclo(self) -> None:
        docs = self.monitor.listar_documentos()
        if docs:
            self._fase1(docs)
            return
        self._fase2()
        self._fase3_com_retry()
        self._stats["ciclos_completos"] += 1
        time.sleep(INTERVALO_LOOP)

    def _fase1(self, docs: List[Dict]) -> None:
        self._estado = "fase_1"
        self.log.info(f"[Fase 1] {len(docs)} documento(s).")
        for doc in docs:
            if not self._ativo:
                break
            op_id = self.log.iniciar_operacao(fase=1, modo="offline")
            t0 = time.time()
            try:
                laudo_id = self.extrator.registrar_laudo(
                    doc["nome"], "laudo_judicial" if doc["tipo"] == "pdf" else "outro")
                n_top, n_par = self.extrator.processar_documento(doc["caminho"], laudo_id, op_id)
                modo = "offline"
                if self.integrador.is_available():
                    try:
                        self.integrador.processar_fase1(doc, laudo_id)
                        modo = "ia"
                    except Exception as e_ia:
                        self.log.warning(f"[Fase 1] IA falhou para '{doc['nome']}': {e_ia}")
                self.monitor.mover_para_processados(doc)
                self._stats["docs_fase1"] += 1
                self.log.finalizar_operacao(op_id, "sucesso", campos_modificados=n_top + n_par,
                                            novos_itens=n_top,
                                            mensagem=f"modo={modo} t={time.time()-t0:.1f}s")
                print(f"  [Fase 1] '{doc['nome']}' ok: {n_top} topicos | {modo}")
            except Exception as e:
                self.log.error(f"[Fase 1] Erro '{doc['nome']}': {e}", exc_info=True)
                self.log.finalizar_operacao(op_id, "erro", erros=1, mensagem=str(e)[:200])
                self.monitor.mover_para_erros(doc, str(e))
                self._stats["erros_total"] += 1

    def _fase2(self) -> None:
        # ── Fase 2 offline (preenchimento de lacunas) ─────────────────────────
        self._estado = "fase_2"
        op_id = self.log.iniciar_operacao(fase=2, modo="offline")
        try:
            lacunas = self.quality.identificar_lacunas()
            self.log.info(f"[Fase 2] {len(lacunas)} lacuna(s).")
            stats = self.extrator.reprocessar_todos(
                callback_verificar_entrada=self.monitor.verificar_entrada)
            self._stats["topicos_fase2"] += stats.get("topicos_revisados", 0)
            resultado = self.quality.validar_fase2()
            self.log.finalizar_operacao(op_id, "sucesso",
                                        campos_modificados=stats.get("campos_preenchidos", 0),
                                        mensagem=resultado.resumo()[:200])
            print(f"\n  [Fase 2 offline] Score: {self.quality.score_banco()*100:.1f}% | "
                  f"Revisados: {stats.get('topicos_revisados', 0)}")
        except Exception as e:
            self.log.error(f"[Fase 2] Erro: {e}", exc_info=True)
            self.log.finalizar_operacao(op_id, "parcial", erros=1, mensagem=str(e)[:200])
            self._stats["erros_total"] += 1

        # ── Fase 1.5: preenche laudos_estruturado para tópicos sem IA anterior ──
        # Quando o Ollama estava indisponível durante [arquivos], a Fase 1 IA foi
        # pulada e laudos_estruturado ficou vazia. Fase 2 IA depende dessa tabela.
        # Esta etapa detecta e corrige essa lacuna antes de rodar o refinamento.
        if self.integrador.is_available():
            try:
                conn_check = self.integrador._conn()
                laudos_sem_fase1 = conn_check.execute("""
                    SELECT DISTINCT t.laudo_id, l.nome_arquivo, l.tipo_fonte
                    FROM topicos t
                    JOIN laudos l ON l.id = t.laudo_id
                    WHERE l.status = 'ativo'
                      AND t.texto_original IS NOT NULL
                      AND length(t.texto_original) > 30
                      AND NOT EXISTS (
                          SELECT 1 FROM laudos_estruturado le
                          WHERE le.topico_id = t.id
                            AND le.processado_fase1 = 1
                      )
                """).fetchall()
                conn_check.close()
                if laudos_sem_fase1:
                    self.log.info(
                        f"[Fase 1.5] {len(laudos_sem_fase1)} laudo(s) sem Fase 1 IA — iniciando."
                    )
                    print(f"\n  [Fase 1.5] {len(laudos_sem_fase1)} laudo(s) sem análise IA anterior — processando...")
                    for laudo_id, nome, tipo in laudos_sem_fase1:
                        doc = {"nome": nome, "tipo": tipo or "outro"}
                        # Processa em iterações até cobrir todos os tópicos do laudo
                        # (processar_fase1 tem LIMIT interno, por isso o loop)
                        tentativas = 0
                        while tentativas < 20:
                            tentativas += 1
                            stats_f1 = self.integrador.processar_fase1(doc, laudo_id)
                            # Soma todos os tipos de processamento (enriquecidos + irrelevantes + revisao + falhas)
                            total_proc = (
                                stats_f1.get("enriquecidos", 0) +
                                stats_f1.get("irrelevantes", 0) +
                                stats_f1.get("revisao", 0) +
                                stats_f1.get("fallback_offline", 0) +
                                stats_f1.get("falhas_ia", 0)
                            )
                            if total_proc == 0:
                                break  # Nenhum tópico novo processado — todos cobertos
                    print("  [Fase 1.5] Concluído.")
            except Exception as e_15:
                self.log.warning(f"[Fase 1.5] Erro: {e_15}")

        # ── Fase 2 IA (refinamento mistral:7b) ────────────────────────────────
        if self.integrador.is_available():
            op_id2 = self.log.iniciar_operacao(fase=2, modo="ia")
            try:
                try:
                    limite_f2 = max(10, int(os.getenv("IA_FASE2_LIMITE", "150")))
                except Exception:
                    limite_f2 = 150
                stats_ia = self.integrador.processar_fase2_ia(limite=limite_f2)
                refinados = stats_ia.get("refinados", 0)
                self._stats["topicos_fase2"] += refinados
                self.log.finalizar_operacao(
                    op_id2, "sucesso",
                    campos_modificados=refinados,
                    confianca_media=stats_ia.get("confianca_media", 0.0),
                    mensagem=f"mistral refinamento | batch={limite_f2} | falhas={stats_ia.get('falhas', 0)}"
                )
                print(f"  [Fase 2 IA]     Refinados: {refinados} | "
                      f"Conf: {stats_ia.get('confianca_media', 0)*100:.1f}% | "
                      f"Batch: {limite_f2}")
            except Exception as e:
                self.log.error(f"[Fase 2 IA] Erro: {e}", exc_info=True)
                self.log.finalizar_operacao(op_id2, "parcial", erros=1, mensagem=str(e)[:200])
        else:
            print("  [Fase 2 IA]     Ollama indisponível — pulando refinamento.")

    def _fase3_com_retry(self) -> None:
        if not self.integrador.is_available():
            # Mostrar mensagem de ajuda específica para cada caso
            if not self.api_key:
                try:
                    from ollama_engine import OllamaEngine
                    engine = OllamaEngine()
                    if not engine.disponivel:
                        print(engine.instrucoes_instalacao())
                    else:
                        print("\n  [Fase 3] Ollama disponível mas sem modelo. "
                              "Execute: ollama pull llama3.1:8b")
                except ImportError:
                    print("\n  [Fase 3] Configure GEMINI_API_KEY no .env "
                          "ou instale Ollama (https://ollama.com)")
            else:
                print("\n  [Fase 3] IA indisponível (Gemini e Ollama). "
                      "Verifique conexão ou reinicie o Ollama.")
            self._estado = "aguardando_ia"
            return
        self._estado  = "fase_3"
        self._retries3 = 0
        while self._retries3 < MAX_RETRIES_F3:
            op_id = self.log.iniciar_operacao(fase=3, modo="ia")
            try:
                if not self.integrador.is_available():
                    raise RuntimeError("IA indisponivel.")
                stats = self.integrador.processar_fase3(analisador=self.quality)
                self._stats["topicos_fase3"] += stats.get("topicos_refinados", 0)
                self.quality.validar_fase3()
                self._retries3 = 0
                self._estado   = "idle"
                self.log.finalizar_operacao(op_id, "sucesso",
                                            campos_modificados=stats.get("classificacoes", 0),
                                            confianca_media=stats.get("confianca_media", 0.0))
                print(f"\n  [Fase 3] Refinados: {stats.get('topicos_refinados',0)} | "
                      f"Conf: {stats.get('confianca_media',0)*100:.1f}%")
                return
            except Exception as e:
                espera = min(BACKOFF_BASE_F3 * (2 ** self._retries3), 300)
                self.log.error(f"[Fase 3] Tentativa {self._retries3+1}: {e}. Aguarda {espera}s.")
                self.log.finalizar_operacao(op_id, "aguardando_ia" if "indisponivel" in str(e) else "erro",
                                            erros=1, mensagem=str(e)[:200])
                self._retries3 += 1
                self._estado = "aguardando_ia"
                if not self._ativo:
                    break
                time.sleep(espera)
        if self._retries3 >= MAX_RETRIES_F3:
            print(f"\n  [Fase 3] {MAX_RETRIES_F3} tentativas falharam. Use --fase 3 para tentar novamente.")
            self._estado = "aguardando_ia"

    def forcar_fase(self, fase: int) -> None:
        if fase == 1:
            docs = self.monitor.listar_documentos()
            if not docs:
                print("  Nenhum documento na entrada.")
            else:
                self._fase1(docs)
        elif fase == 2:
            self._fase2()
        elif fase == 3:
            self._retries3 = 0
            self._fase3_com_retry()

    def exibir_status(self) -> None:
        print("\n" + "=" * 60)
        print("  STATUS — Reprocessamento Multifasico")
        print("=" * 60)
        icons = {"idle":"[idle]","fase_1":"[F1]","fase_2":"[F2]","fase_3":"[F3]",
                 "aguardando_ia":"[aguard]","erro":"[erro]"}
        print(f"\n  Estado: {icons.get(self._estado,'')} {self._estado}")
        print(f"  IA:     {'disponivel' if self.integrador.is_available() else 'indisponivel'}")
        print("\n  Pastas:")
        for pasta, qtd in self.monitor.estatisticas().items():
            print(f"    {pasta:30s}: {qtd}")
        print(self.quality.relatorio_saude_banco())
        print("\n  Sessao:")
        for k, v in self._stats.items():
            print(f"    {k:25s}: {v}")
        print(self.log.relatorio_fase(1, 5))
        print(self.log.relatorio_fase(2, 3))
        print(self.log.relatorio_fase(3, 3))
        print("=" * 60)

    def exibir_relatorio(self) -> None:
        print(self.quality.formatar_relatorio())


def _banner() -> None:
    print("\n" + "=" * 55)
    print("  REPROCESSAMENTO MULTIFASICO v1.0")
    print("  F1: novos docs | F2: melhoria offline | F3: IA")
    print("=" * 55 + "\n")


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=Path(__file__).parent / ".env")
    except ImportError:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--fase",      type=int, choices=[1, 2, 3])
    parser.add_argument("--status",    action="store_true")
    parser.add_argument("--relatorio", action="store_true")
    parser.add_argument("--db",        type=str, default=DB_PATH)
    parser.add_argument("--api-key",   type=str, default="")
    args = parser.parse_args()
    api_key = args.api_key or os.getenv("GEMINI_API_KEY", "")
    orq = OrquestradorReprocessamento(db_path=args.db, api_key=api_key)
    if args.status:
        orq.exibir_status(); return
    if args.relatorio:
        orq.exibir_relatorio(); return
    if args.fase:
        orq.forcar_fase(args.fase); return
    orq.iniciar()


if __name__ == "__main__":
    main()

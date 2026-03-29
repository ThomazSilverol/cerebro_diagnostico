"""
log_manager.py — Gerenciador Centralizado de Logs e Auditoria
Sistema: Cérebro de Engenharia Diagnóstica — Reprocessamento Inteligente v1.0

Responsabilidades:
  • Logging multi-nível (DEBUG, INFO, WARNING, ERROR, CRITICAL) em arquivo e console
  • Registro de operações de processamento com rastreabilidade completa
  • Histórico de mudanças por item do banco (quem, quando, o quê)
  • Relatórios de auditoria por fase e por documento

Referência: Regra Crítica 4 — LOGGING E AUDITORIA do prompt de reprocessamento.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

LOG_DIR       = "logs"
LOG_FILE      = os.path.join(LOG_DIR, "reprocessamento.log")
LOG_MAX_BYTES = 10 * 1024 * 1024   # 10 MB por arquivo
LOG_BACKUPS   = 5                  # 5 arquivos históricos


# ─────────────────────────────────────────────────────────────────────────────
# GerenciadorLog
# ─────────────────────────────────────────────────────────────────────────────

class GerenciadorLog:
    """
    Gerenciador centralizado de logs — singleton thread-safe.

    Níveis disponíveis: debug(), info(), warning(), error(), critical()

    Adicionalmente expõe:
      registrar_mudanca()  → histórico de alterações de campo
      relatorio_fase()     → sumário de operação por fase

    Exemplo de uso:
        log = GerenciadorLog.obter_instancia()
        log.info("Documento procesado", documento="laudo_01.pdf", fase=1)
        log.registrar_mudanca(topico_id=42, campo="grau_risco",
                              antes="-", depois="Alto", responsavel="fase_2_offline")
    """

    _instancia: Optional["GerenciadorLog"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: str = "banco_pericial.db"):
        self.db_path = db_path
        os.makedirs(LOG_DIR, exist_ok=True)
        self._logger = self._configurar_logger()
        self._garantir_tabelas()

    # ─── Singleton ────────────────────────────────────────────────────────────

    @classmethod
    def obter_instancia(cls, db_path: str = "banco_pericial.db") -> "GerenciadorLog":
        """Retorna (ou cria) a instância singleton."""
        with cls._lock:
            if cls._instancia is None:
                cls._instancia = cls(db_path)
            return cls._instancia

    # ─── Configuração do logger Python ───────────────────────────────────────

    def _configurar_logger(self) -> logging.Logger:
        logger = logging.getLogger("reprocessamento")
        if logger.handlers:
            return logger  # já configurado

        logger.setLevel(logging.DEBUG)

        # Handler arquivo (rotativo)
        fh = RotatingFileHandler(
            LOG_FILE, maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))

        # Handler console (INFO+)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%H:%M:%S"
        ))

        logger.addHandler(fh)
        logger.addHandler(ch)
        return logger

    # ─── Garantir tabelas de auditoria ────────────────────────────────────────

    def _garantir_tabelas(self) -> None:
        """Cria tabelas de log no banco se não existirem."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS reprocessamento_log (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    documento_id      INTEGER,
                    fase              INTEGER NOT NULL,
                    data_inicio       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    data_fim          TIMESTAMP,
                    modo              TEXT NOT NULL,
                    campos_modificados INTEGER DEFAULT 0,
                    novos_itens       INTEGER DEFAULT 0,
                    erros_detectados  INTEGER DEFAULT 0,
                    confianca_media   REAL DEFAULT 0.0,
                    status            TEXT NOT NULL,
                    mensagem          TEXT,
                    FOREIGN KEY(documento_id) REFERENCES laudos(id)
                );

                CREATE TABLE IF NOT EXISTS auditoria_mudancas (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    topico_id     INTEGER,
                    documento_id  INTEGER,
                    fase          INTEGER,
                    campo         TEXT NOT NULL,
                    valor_antes   TEXT,
                    valor_depois  TEXT,
                    responsavel   TEXT NOT NULL,
                    timestamp     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(topico_id) REFERENCES topicos(id)
                );

                CREATE TABLE IF NOT EXISTS dicionario_pericial_sinonimos (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    conceito    TEXT UNIQUE NOT NULL,
                    sinonimos   TEXT NOT NULL,
                    categoria   TEXT DEFAULT '',
                    frequencia  INTEGER DEFAULT 0,
                    confianca   REAL DEFAULT 0.8
                );
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            self._logger.error(f"[GerenciadorLog] Falha ao criar tabelas: {e}")

    # ─── API de logging ───────────────────────────────────────────────────────

    def _formatar(self, mensagem: str, **kwargs) -> str:
        if kwargs:
            extras = " | ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"{mensagem} | {extras}"
        return mensagem

    def debug(self, mensagem: str, **kwargs) -> None:
        self._logger.debug(self._formatar(mensagem, **kwargs))

    def info(self, mensagem: str, **kwargs) -> None:
        self._logger.info(self._formatar(mensagem, **kwargs))

    def warning(self, mensagem: str, **kwargs) -> None:
        self._logger.warning(self._formatar(mensagem, **kwargs))

    def error(self, mensagem: str, exc_info: bool = False, **kwargs) -> None:
        msg = self._formatar(mensagem, **kwargs)
        if exc_info:
            self._logger.error(msg + "\n" + traceback.format_exc())
        else:
            self._logger.error(msg)

    def critical(self, mensagem: str, exc_info: bool = False, **kwargs) -> None:
        msg = self._formatar(mensagem, **kwargs)
        if exc_info:
            self._logger.critical(msg + "\n" + traceback.format_exc())
        else:
            self._logger.critical(msg)

    # ─── Registro de operação de fase ────────────────────────────────────────

    def iniciar_operacao(
        self,
        fase: int,
        modo: str,
        documento_id: Optional[int] = None,
    ) -> int:
        """
        Registra início de uma operação de fase. Retorna o ID do registro.

        Args:
            fase: 1, 2 ou 3
            modo: 'offline' ou 'ia'
            documento_id: FK para laudos.id (None para operações globais)

        Returns:
            ID do registro em reprocessamento_log
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute(
                """INSERT INTO reprocessamento_log
                   (documento_id, fase, modo, status, mensagem)
                   VALUES (?, ?, ?, 'em_andamento', 'Iniciado')""",
                (documento_id, fase, modo)
            )
            op_id = cur.lastrowid
            conn.commit()
            conn.close()
            self.info(f"[Fase {fase}] Operação iniciada",
                      op_id=op_id, modo=modo, doc_id=documento_id)
            return op_id
        except Exception as e:
            self.error(f"[GerenciadorLog] Falha ao iniciar operação: {e}")
            return -1

    def finalizar_operacao(
        self,
        op_id: int,
        status: str,
        campos_modificados: int = 0,
        novos_itens: int = 0,
        erros: int = 0,
        confianca_media: float = 0.0,
        mensagem: str = "",
    ) -> None:
        """
        Atualiza o registro de operação com o resultado final.

        Args:
            op_id: ID retornado por iniciar_operacao()
            status: 'sucesso' | 'parcial' | 'erro' | 'aguardando_ia'
        """
        if op_id < 0:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """UPDATE reprocessamento_log SET
                   data_fim=CURRENT_TIMESTAMP,
                   campos_modificados=?,
                   novos_itens=?,
                   erros_detectados=?,
                   confianca_media=?,
                   status=?,
                   mensagem=?
                   WHERE id=?""",
                (campos_modificados, novos_itens, erros,
                 confianca_media, status, mensagem[:500], op_id)
            )
            conn.commit()
            conn.close()
            self.info(
                f"[Op {op_id}] Finalizada",
                status=status,
                campos=campos_modificados,
                novos=novos_itens,
                erros=erros,
            )
        except Exception as e:
            self.error(f"[GerenciadorLog] Falha ao finalizar operação {op_id}: {e}")

    # ─── Registro de mudança de campo ─────────────────────────────────────────

    def registrar_mudanca(
        self,
        campo: str,
        valor_antes: Any,
        valor_depois: Any,
        responsavel: str,
        topico_id: Optional[int] = None,
        documento_id: Optional[int] = None,
        fase: int = 0,
    ) -> None:
        """
        Registra uma alteração de campo para auditoria.

        Args:
            campo: Nome do campo alterado (ex: 'grau_risco')
            valor_antes: Valor anterior (será serializado para texto)
            valor_depois: Novo valor
            responsavel: Ex: 'fase_2_offline', 'fase_3_ia'
            topico_id: FK topicos.id (opcional)
            documento_id: FK laudos.id (opcional)
            fase: Número da fase (0 = não especificado)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT INTO auditoria_mudancas
                   (topico_id, documento_id, fase, campo, valor_antes, valor_depois, responsavel)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    topico_id, documento_id, fase, campo,
                    str(valor_antes)[:1000] if valor_antes is not None else None,
                    str(valor_depois)[:1000] if valor_depois is not None else None,
                    responsavel,
                )
            )
            conn.commit()
            conn.close()
            self.debug(
                f"Mudança registrada",
                topico=topico_id, campo=campo,
                antes=str(valor_antes)[:50], depois=str(valor_depois)[:50],
                por=responsavel,
            )
        except Exception as e:
            self.warning(f"[GerenciadorLog] Não salvou mudança (não crítico): {e}")

    # ─── Relatório de operações ────────────────────────────────────────────────

    def relatorio_fase(self, fase: int, limite: int = 20) -> str:
        """
        Retorna string formatada com as últimas operações de uma fase.

        Args:
            fase: 1, 2 ou 3
            limite: Máximo de registros a exibir

        Returns:
            Texto formatado para console
        """
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT data_inicio, data_fim, modo, campos_modificados,
                          novos_itens, erros_detectados, status, mensagem
                   FROM reprocessamento_log
                   WHERE fase = ?
                   ORDER BY data_inicio DESC LIMIT ?""",
                (fase, limite)
            ).fetchall()
            conn.close()

            if not rows:
                return f"  [Fase {fase}] Sem registros de operação."

            linhas = [f"\n  === RELATÓRIO — FASE {fase} (últimas {len(rows)} ops) ==="]
            for r in rows:
                dt_inicio = r[0][:16] if r[0] else "?"
                dt_fim    = r[1][:16] if r[1] else "Em andamento"
                linhas.append(
                    f"  {dt_inicio} → {dt_fim} | {r[2]:8s} | "
                    f"campos:{r[3]:4d} | novos:{r[4]:3d} | "
                    f"erros:{r[5]:2d} | {r[6]:15s} | {(r[7] or '')[:60]}"
                )
            return "\n".join(linhas)
        except Exception as e:
            return f"  [Fase {fase}] Erro ao gerar relatório: {e}"

    def historico_topico(self, topico_id: int) -> List[Dict[str, Any]]:
        """
        Retorna histórico completo de mudanças de um tópico.

        Args:
            topico_id: ID em topicos.id

        Returns:
            Lista de dicts ordenados por timestamp desc.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT timestamp, fase, campo, valor_antes, valor_depois, responsavel
                   FROM auditoria_mudancas
                   WHERE topico_id = ?
                   ORDER BY timestamp DESC""",
                (topico_id,)
            ).fetchall()
            conn.close()
            return [
                {
                    "timestamp":    r[0],
                    "fase":         r[1],
                    "campo":        r[2],
                    "valor_antes":  r[3],
                    "valor_depois": r[4],
                    "responsavel":  r[5],
                }
                for r in rows
            ]
        except Exception:
            return []

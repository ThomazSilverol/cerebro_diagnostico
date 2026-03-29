"""
quality_manager.py — Gerenciador de Qualidade e Integridade dos Dados
Sistema: Cérebro de Engenharia Diagnóstica — Reprocessamento Inteligente v1.0

Consolida AnalisadorCompletude + ValidadorDados em um único módulo:
  • Identifica campos vazios, incompletos ou malformados
  • Detecta duplicatas e inconsistências
  • Normaliza grau_risco, status_processamento e unidades
  • Gera score de completude (0.0–1.0) por documento e global
  • Prioriza tópicos para refinamento na Fase 3

Uso:
    from quality_manager import QualityManager
    qm = QualityManager("banco_pericial.db")
    lacunas = qm.identificar_lacunas()
    print(qm.formatar_relatorio())
    resultado = qm.validar_fase2()
    print(resultado.resumo())
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

GRAUS_RISCO_VALIDOS = {"Crítico", "Médio", "Mínimo", "-", "", None}
STATUS_PROC_VALIDOS = {
    "nao_iniciado", "fase_1_offline", "fase_1_ia",
    "fase_2_offline", "fase_2_ia", "fase_3_ia", "completo",
}
_NORM_RISCO = {
    "critico": "Crítico", "crítico": "Crítico", "alto": "Crítico", "grave": "Crítico",
    "medio":   "Médio",   "médio":   "Médio",   "moderado": "Médio",
    "minimo":  "Mínimo",  "mínimo":  "Mínimo",  "baixo": "Mínimo", "leve": "Mínimo",
}
_CAMPOS_PESO = {
    "titulo_topico":  0.25,
    "texto_original": 0.35,
    "palavras_chave": 0.25,
    "hierarquia":     0.10,
    "pagina":         0.05,
    # grau_risco REMOVIDO: classificação é responsabilidade exclusiva
    # das análises de imagem, GUT e IBAPE realizadas pelo perito.
}
_VAZIOS = {None, "", "-", "N/A", "n/a", "0", "nao_iniciado"}


# ─────────────────────────────────────────────────────────────────────────────
# Estruturas de dados
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Lacuna:
    topico_id:     int
    laudo_id:      int
    campo:         str
    tipo:          str   # 'vazio' | 'incompleto' | 'malformado' | 'duplicado'
    descricao:     str
    prioridade:    int = 1   # 1=baixa  2=média  3=alta


@dataclass
class ResultadoValidacao:
    fk_inconsistencias:     int = 0
    campos_normalizados:    int = 0
    outliers_detectados:    int = 0
    terminologia_corrigida: int = 0
    erros_criticos:  List[str] = field(default_factory=list)
    avisos:          List[str] = field(default_factory=list)

    @property
    def score_saude(self) -> float:
        p = self.fk_inconsistencias * 3 + self.outliers_detectados + len(self.erros_criticos) * 2
        return max(0.0, min(1.0, 1.0 - (p / max(1, p + 10))))

    def resumo(self) -> str:
        linhas = [
            "  [QualityManager] Resultado:",
            f"    FK inconsistências:   {self.fk_inconsistencias}",
            f"    Campos normalizados:  {self.campos_normalizados}",
            f"    Outliers detectados:  {self.outliers_detectados}",
            f"    Terminologia corrig.: {self.terminologia_corrigida}",
            f"    Score de saúde:       {self.score_saude:.2f}",
        ]
        if self.erros_criticos:
            linhas.append(f"    ⚠️  Erros críticos ({len(self.erros_criticos)}):")
            for e in self.erros_criticos[:5]:
                linhas.append(f"       - {e}")
        return "\n".join(linhas)


# ─────────────────────────────────────────────────────────────────────────────
# QualityManager
# ─────────────────────────────────────────────────────────────────────────────

class QualityManager:
    """
    Gerenciador unificado de completude e integridade do banco.

    Exemplo de uso completo:
        qm = QualityManager("banco_pericial.db")

        # Antes da Fase 2
        lacunas = qm.identificar_lacunas()
        print(f"{len(lacunas)} lacunas encontradas")

        # Após Fase 2
        resultado = qm.validar_fase2()
        print(resultado.resumo())

        # Após Fase 3
        resultado3 = qm.validar_fase3()
        print(resultado3.resumo())

        # Relatório geral
        print(qm.formatar_relatorio())
        ids = qm.topicos_prioritarios_ia(limite=50)
    """

    def __init__(self, db_path: str = "banco_pericial.db"):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _eh_vazio(v: Any) -> bool:
        return v is None or str(v).strip() in _VAZIOS

    # ─── Identificação de lacunas ─────────────────────────────────────────────

    def identificar_lacunas(self) -> List[Lacuna]:
        """
        Escaneia todos os tópicos e retorna lacunas priorizadas.
        Retorna lista ordenada por prioridade descendente.
        """
        lacunas: List[Lacuna] = []
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id, laudo_id, titulo_topico, texto_original, "
                "palavras_chave, hierarquia FROM topicos ORDER BY laudo_id, id"
            ).fetchall()
        finally:
            conn.close()

        for tid, laudo_id, titulo, texto, palavras, hier in rows:
            if self._eh_vazio(titulo):
                lacunas.append(Lacuna(tid, laudo_id, "titulo_topico", "vazio", "Título ausente", 3))
            elif len(str(titulo)) < 8:
                lacunas.append(Lacuna(tid, laudo_id, "titulo_topico", "incompleto", f"Título curto: '{titulo}'", 2))

            if self._eh_vazio(texto):
                lacunas.append(Lacuna(tid, laudo_id, "texto_original", "vazio", "Texto ausente", 3))
            elif len(str(texto)) < 30:
                lacunas.append(Lacuna(tid, laudo_id, "texto_original", "incompleto", f"Texto curto ({len(str(texto))} chars)", 2))

            if self._eh_vazio(palavras):
                lacunas.append(Lacuna(tid, laudo_id, "palavras_chave", "vazio", "Palavras-chave ausentes", 2))
            elif len(str(palavras).split(",")) < 2:
                lacunas.append(Lacuna(tid, laudo_id, "palavras_chave", "incompleto", f"Apenas 1 palavra-chave", 1))

            if self._eh_vazio(hier):
                lacunas.append(Lacuna(tid, laudo_id, "hierarquia", "vazio", "Hierarquia ausente", 1))

            # grau_risco NÃO é auditado aqui: classificação é responsabilidade
            # exclusiva das análises de imagem, GUT e IBAPE realizadas pelo perito.

        lacunas += self._detectar_duplicatas()
        lacunas.sort(key=lambda x: x.prioridade, reverse=True)
        return lacunas

    def _detectar_duplicatas(self) -> List[Lacuna]:
        dupl: List[Lacuna] = []
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id, laudo_id, substr(texto_original,1,200) FROM topicos "
                "WHERE texto_original IS NOT NULL AND texto_original != '' ORDER BY 3"
            ).fetchall()
            vistos: Dict[str, tuple] = {}
            for tid, laudo_id, txt in rows:
                chave = txt.strip().lower()[:150]
                if chave in vistos and chave:
                    dupl.append(Lacuna(tid, laudo_id, "texto_original", "duplicado",
                                       f"Duplicado do tópico {vistos[chave][0]}", 1))
                else:
                    vistos[chave] = (tid, laudo_id)
        except Exception:
            pass
        finally:
            conn.close()
        return dupl

    # ─── Score de completude ──────────────────────────────────────────────────

    def score_banco(self) -> float:
        """Retorna score médio de completude (0.0–1.0)."""
        conn = self._conn()
        try:
            laudos = conn.execute("SELECT id FROM laudos WHERE status='ativo'").fetchall()
        finally:
            conn.close()
        if not laudos:
            return 0.0
        scores = [self._score_documento(lid[0]) for lid in laudos]
        return sum(scores) / len(scores)

    def _score_documento(self, laudo_id: int) -> float:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT titulo_topico, texto_original, palavras_chave, "
                "hierarquia, pagina FROM topicos WHERE laudo_id=?",
                (laudo_id,)
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return 0.0
        campos = list(_CAMPOS_PESO.keys())
        score = 0.0
        for campo, peso in _CAMPOS_PESO.items():
            idx = campos.index(campo)
            preenchidos = sum(1 for r in rows if idx < len(r) and not self._eh_vazio(r[idx]))
            score += peso * (preenchidos / len(rows))
        return round(score, 3)

    def formatar_relatorio(self) -> str:
        """Relatório de completude por documento para exibição no console."""
        conn = self._conn()
        try:
            laudos = conn.execute(
                "SELECT id, nome_arquivo FROM laudos WHERE status='ativo'"
            ).fetchall()
        finally:
            conn.close()
        if not laudos:
            return "  Nenhum documento ativo no banco."

        linhas = ["\n  === RELATÓRIO DE COMPLETUDE ===\n"]
        scores = []
        for lid, nome in laudos:
            s = self._score_documento(lid)
            scores.append(s)
            icone = "🔴" if s < 0.5 else ("🟡" if s < 0.8 else "🟢")
            linhas.append(f"  {icone} [{s*100:4.0f}%] {nome[:55]}")

        media = sum(scores) / len(scores) if scores else 0
        linhas.append(f"\n  Score médio: {media*100:.1f}% | Total: {len(laudos)} documento(s)")
        return "\n".join(linhas)

    def topicos_prioritarios_ia(self, limite: int = 50) -> List[int]:
        """
        IDs de tópicos sem refinamento semântico (Fase 3) com texto substancial.

        Critério: status_processamento ainda não chegou à fase_3_ia, indicando
        que o sumário executivo, nexo causal e normas relacionadas ainda não
        foram enriquecidos pelo processamento automático.

        Nota: grau_risco NÃO é critério de prioridade aqui — essa classificação
        é responsabilidade exclusiva das análises de imagem, GUT e IBAPE.
        """
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

    # ─── Validação pós-Fase 2 ────────────────────────────────────────────────

    def validar_fase2(self) -> ResultadoValidacao:
        """Validação offline pós-Fase 2: FK, normalização, harmonização."""
        r = ResultadoValidacao()
        r.fk_inconsistencias    += self._verificar_fk(r)
        r.campos_normalizados   += self._normalizar_grau_risco(r)
        r.campos_normalizados   += self._normalizar_status(r)
        r.campos_normalizados   += self._normalizar_parametros(r)
        r.terminologia_corrigida += self._harmonizar_palavras_chave(r)
        r.outliers_detectados   += self._detectar_outliers_conf(r)
        return r

    # ─── Validação pós-Fase 3 ────────────────────────────────────────────────

    def validar_fase3(self) -> ResultadoValidacao:
        """Validação pós-Fase 3: consistência IA, outliers, cobertura."""
        r = ResultadoValidacao()
        r.fk_inconsistencias    += self._verificar_fk(r)
        r.campos_normalizados   += self._normalizar_grau_risco(r)
        r.outliers_detectados   += self._detectar_outliers_conf(r)
        r.outliers_detectados   += self._detectar_confianca_inconsistente(r)
        r.terminologia_corrigida += self._verificar_cobertura_ia(r)
        return r

    # ─── Verificações internas ────────────────────────────────────────────────

    def _verificar_fk(self, r: ResultadoValidacao) -> int:
        conn = self._conn()
        try:
            orphans = conn.execute(
                "SELECT COUNT(*) FROM topicos t "
                "WHERE NOT EXISTS (SELECT 1 FROM laudos l WHERE l.id=t.laudo_id)"
            ).fetchone()[0]
            if orphans:
                r.erros_criticos.append(f"FK violada: {orphans} tópico(s) sem laudo")
            return orphans
        except Exception:
            return 0
        finally:
            conn.close()

    def _normalizar_grau_risco(self, r: ResultadoValidacao) -> int:
        conn = self._conn()
        corrigidos = 0
        try:
            for tid, risco in conn.execute("SELECT id, grau_risco FROM topicos WHERE grau_risco IS NOT NULL").fetchall():
                if risco in GRAUS_RISCO_VALIDOS:
                    continue
                norm = _NORM_RISCO.get(str(risco).lower().strip())
                if norm:
                    conn.execute("UPDATE topicos SET grau_risco=? WHERE id=?", (norm, tid))
                    corrigidos += 1
                else:
                    r.avisos.append(f"Tópico {tid}: grau_risco desconhecido '{risco}'")
            if corrigidos:
                conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
        return corrigidos

    def _normalizar_status(self, r: ResultadoValidacao) -> int:
        conn = self._conn()
        corrigidos = 0
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(topicos)").fetchall()}
            if "status_processamento" not in cols:
                return 0
            for tid, status in conn.execute("SELECT id, status_processamento FROM topicos").fetchall():
                if status not in STATUS_PROC_VALIDOS:
                    conn.execute("UPDATE topicos SET status_processamento='nao_iniciado' WHERE id=?", (tid,))
                    corrigidos += 1
            if corrigidos:
                conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
        return corrigidos

    def _normalizar_parametros(self, r: ResultadoValidacao) -> int:
        conn = self._conn()
        n = 0
        try:
            for pid, param, valor, unidade in conn.execute(
                "SELECT id, parametro, valor, unidade FROM parametros_normativos"
            ).fetchall():
                if unidade and unidade.lower() == "mm" and param == "dimensão":
                    try:
                        v_m = float(str(valor).replace(",", ".")) / 1000
                        conn.execute("UPDATE parametros_normativos SET valor=?,unidade='m' WHERE id=?",
                                     (f"{v_m:.4f}", pid))
                        n += 1
                    except (ValueError, TypeError):
                        pass
            if n:
                conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
        return n

    def _harmonizar_palavras_chave(self, r: ResultadoValidacao) -> int:
        conn = self._conn()
        n = 0
        try:
            for tid, pks in conn.execute(
                "SELECT id, palavras_chave FROM topicos WHERE palavras_chave IS NOT NULL"
            ).fetchall():
                if not pks:
                    continue
                itens = list(dict.fromkeys(p.strip().lower() for p in pks.split(",") if p.strip()))
                nova = ", ".join(itens)
                if nova != pks:
                    conn.execute("UPDATE topicos SET palavras_chave=? WHERE id=?", (nova, tid))
                    n += 1
            if n:
                conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
        return n

    def _detectar_outliers_conf(self, r: ResultadoValidacao) -> int:
        conn = self._conn()
        n = 0
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(topicos)").fetchall()}
            if "ia_score_confianca" not in cols:
                return 0
            for tid, conf in conn.execute(
                "SELECT id, ia_score_confianca FROM topicos WHERE ia_score_confianca IS NOT NULL"
            ).fetchall():
                if conf < 0.0 or conf > 1.0:
                    conn.execute("UPDATE topicos SET ia_score_confianca=? WHERE id=?",
                                 (max(0.0, min(1.0, conf)), tid))
                    n += 1
            if n:
                conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
        return n

    def _detectar_confianca_inconsistente(self, r: ResultadoValidacao) -> int:
        """
        Detecta tópicos onde ia_score_confianca é alto mas o sumário
        executivo está vazio — indica que o refinamento Fase 3 não foi gravado.

        Nota: ausência de grau_risco NÃO é reportada como inconsistência —
        essa classificação é responsabilidade do perito via análise de imagem,
        GUT ou IBAPE.
        """
        conn = self._conn()
        n = 0
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(topicos)").fetchall()}
            if "ia_score_confianca" not in cols:
                return 0
            for tid, conf, reescrito in conn.execute(
                "SELECT id, ia_score_confianca, texto_reescrito FROM topicos "
                "WHERE ia_score_confianca>=0.7 AND (texto_reescrito IS NULL OR texto_reescrito='')"
            ).fetchall():
                r.avisos.append(
                    f"Tópico {tid}: confiança IA={conf:.2f} mas sumário executivo vazio"
                )
                n += 1
        except Exception:
            pass
        finally:
            conn.close()
        return n

    def _verificar_cobertura_ia(self, r: ResultadoValidacao) -> int:
        conn = self._conn()
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(topicos)").fetchall()}
            if "status_processamento" not in cols:
                return 0
            sem_ia = conn.execute(
                "SELECT COUNT(*) FROM topicos "
                "WHERE status_processamento NOT IN ('fase_3_ia','completo') "
                "AND length(texto_original)>50"
            ).fetchone()[0]
            if sem_ia:
                r.avisos.append(f"{sem_ia} tópico(s) substanciais sem análise IA")
            return sem_ia
        except Exception:
            return 0
        finally:
            conn.close()

    def relatorio_saude_banco(self) -> str:
        """Relatório rápido de saúde para o comando [status] do main.py."""
        conn = self._conn()
        try:
            n_laudos  = conn.execute("SELECT COUNT(*) FROM laudos WHERE status='ativo'").fetchone()[0]
            n_topicos = conn.execute("SELECT COUNT(*) FROM topicos").fetchone()[0]
            n_params  = conn.execute("SELECT COUNT(*) FROM parametros_normativos").fetchone()[0]
            dist_risco = {r[0] or "(vazio)": r[1] for r in conn.execute(
                "SELECT grau_risco, COUNT(*) FROM topicos GROUP BY grau_risco"
            ).fetchall()}
        finally:
            conn.close()

        linhas = [
            f"\n  Laudos ativos: {n_laudos}  |  Tópicos: {n_topicos}  |  Parâmetros: {n_params}",
            f"  Score completude: {self.score_banco()*100:.1f}%",
            "  Grau de risco: " + " | ".join(f"{k}:{v}" for k,v in dist_risco.items()),
        ]
        return "\n".join(linhas)

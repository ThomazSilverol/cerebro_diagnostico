"""
verify_embeddings.py — Utilitário CLI de Diagnóstico e Reprocessamento de Embeddings
Cérebro de Engenharia Diagnóstica v2.0

USO:
  python verify_embeddings.py --banco cerebro_pericial.db
  python verify_embeddings.py --banco cerebro_pericial.db --reprocessar
  python verify_embeddings.py --banco cerebro_pericial.db --reprocessar --lote 10 --dry-run

RESTRIÇÕES:
  ✅  Não modifica nenhum arquivo existente do projeto
  ✅  Importa gerar_embedding de ai_engine (não reimplementa)
  ✅  Usa: sqlite3, argparse, logging, tqdm, time, sys, os, json
  ✅  Compatível com Python 3.10+
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from typing import List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────────────
#  CONFIGURAÇÃO DE LOGGING
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("verify_embeddings")

# ──────────────────────────────────────────────────────────────────────────────
#  IMPORTAÇÃO OPCIONAL DO AI_ENGINE
# ──────────────────────────────────────────────────────────────────────────────

try:
    from ai_engine import AIEngine
    AI_ENGINE_DISPONIVEL = True
except ImportError:
    AI_ENGINE_DISPONIVEL = False
    log.warning(
        "Não foi possível importar 'ai_engine'. "
        "Certifique-se de que verify_embeddings.py está no mesmo diretório do projeto "
        "e que as dependências estão instaladas (pip install google-generativeai python-dotenv pyyaml)."
    )

try:
    from tqdm import tqdm
    TQDM_DISPONIVEL = True
except ImportError:
    TQDM_DISPONIVEL = False
    log.warning("tqdm não instalado — progresso será exibido em texto simples. "
                "Instale com: pip install tqdm")


# ──────────────────────────────────────────────────────────────────────────────
#  HELPERS DE FORMATAÇÃO
# ──────────────────────────────────────────────────────────────────────────────

def _box(linhas: List[str], largura: int = 56) -> str:
    """Gera uma caixa de texto com bordas Unicode."""
    sep_topo  = "╔" + "═" * largura + "╗"
    sep_meio  = "╠" + "═" * largura + "╣"
    sep_base  = "╚" + "═" * largura + "╝"
    corpo = []
    for linha in linhas:
        if linha == "---":
            corpo.append("╠" + "═" * largura + "╣")
        else:
            corpo.append("║  " + linha.ljust(largura - 2) + "║")
    return "\n".join([sep_topo] + corpo + [sep_base])


def _tabela(colunas: List[str], linhas: List[Tuple], widths: List[int]) -> str:
    """Gera tabela CLI com bordas."""
    def linha_sep(esq, meio, dir_, fill="─"):
        return esq + fill * widths[0] + (meio + fill * w for w in widths[1:] if False) + dir_

    def formatar_row(cells):
        partes = []
        for i, (c, w) in enumerate(zip(cells, widths)):
            partes.append(str(c)[:w].ljust(w))
        return "│ " + " │ ".join(partes) + " │"

    sep = "├─" + "─┼─".join("─" * w for w in widths) + "─┤"
    topo = "┌─" + "─┬─".join("─" * w for w in widths) + "─┐"
    base = "└─" + "─┴─".join("─" * w for w in widths) + "─┘"

    linhas_str = [topo, formatar_row(colunas), sep]
    for row in linhas:
        linhas_str.append(formatar_row(row))
    linhas_str.append(base)
    return "\n".join(linhas_str)


def _formatar_tempo(segundos: float) -> str:
    """Converte segundos em string legível (1m30s)."""
    if segundos < 60:
        return f"{segundos:.0f}s"
    m, s = divmod(int(segundos), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


# ──────────────────────────────────────────────────────────────────────────────
#  ACESSO AO BANCO
# ──────────────────────────────────────────────────────────────────────────────

def _abrir_banco(caminho: str) -> sqlite3.Connection:
    """Abre o banco SQLite com validação de existência e estrutura."""
    if not os.path.exists(caminho):
        log.error(f"Banco não encontrado: '{caminho}'")
        log.error("Verifique o caminho ou use --banco para especificá-lo.")
        sys.exit(1)

    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row

    # Validar que a tabela topicos existe
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='topicos'"
    )
    if not cursor.fetchone():
        log.error("Tabela 'topicos' não encontrada no banco informado.")
        log.error("Confirme que o banco é do projeto Cérebro de Engenharia Diagnóstica.")
        conn.close()
        sys.exit(1)

    # Validar que a coluna embedding existe
    cursor.execute("PRAGMA table_info(topicos)")
    colunas = {row["name"] for row in cursor.fetchall()}
    if "embedding" not in colunas:
        log.error("Coluna 'embedding' não encontrada na tabela 'topicos'.")
        log.error("Execute o sistema uma vez para aplicar as migrações de banco.")
        conn.close()
        sys.exit(1)

    return conn


def _diagnosticar(conn: sqlite3.Connection, limite: int) -> dict:
    """
    Executa as 4 queries de diagnóstico e retorna um dicionário com os resultados.
    """
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM topicos")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM topicos WHERE embedding IS NOT NULL")
    com_emb = cur.fetchone()[0]

    sem_emb = total - com_emb
    pct = (com_emb / total * 100) if total > 0 else 0.0

    # Lista dos primeiros {limite} sem embedding (com nome da fonte)
    cur.execute("""
        SELECT t.id, COALESCE(l.nome_arquivo, 'desconhecido') as fonte,
               COALESCE(t.hierarquia, '') as hierarquia
        FROM topicos t
        LEFT JOIN laudos l ON t.laudo_id = l.id
        WHERE t.embedding IS NULL
        ORDER BY t.id ASC
        LIMIT ?
    """, (limite,))
    lista_sem = cur.fetchall()

    return {
        "total":     total,
        "com_emb":   com_emb,
        "sem_emb":   sem_emb,
        "pct":       pct,
        "lista_sem": lista_sem,
    }


def _exibir_diagnostico(info: dict, nome_banco: str, limite: int):
    """Imprime o relatório de diagnóstico formatado."""
    total    = info["total"]
    com_emb  = info["com_emb"]
    sem_emb  = info["sem_emb"]
    pct      = info["pct"]

    if pct >= 100.0:
        status = "🟢 COBERTURA TOTAL"
    elif pct == 0.0:
        status = "🔴 SEM COBERTURA SEMÂNTICA"
    else:
        status = f"🟡 COBERTURA PARCIAL ({pct:.1f}%)"

    L = 56
    titulo = f"DIAGNÓSTICO DE EMBEDDINGS — {os.path.basename(nome_banco)}"
    linhas_box = [
        titulo[:L],
        "---",
        f"Total de tópicos no banco:      {total}",
        f"Tópicos COM embedding:          {com_emb}",
        f"Tópicos SEM embedding:          {sem_emb}",
        f"Cobertura semântica:            {pct:.1f}%",
        "---",
        f"Status: {status}",
    ]
    print("\n" + _box(linhas_box, L))

    if sem_emb > 0:
        lista = info["lista_sem"]
        widths = [6, 32, 28]
        rows = [(row[0], row[1][:32], row[2][:28]) for row in lista]
        print("\n  Primeiros tópicos sem embedding:\n")
        print(_tabela(["ID", "Fonte", "Hierarquia"], rows, widths))

        if sem_emb > limite:
            print(
                f"\n  ... e mais {sem_emb - limite} tópico(s) sem embedding."
                f"\n  Use --limite N para ver mais."
            )


# ──────────────────────────────────────────────────────────────────────────────
#  REPROCESSAMENTO
# ──────────────────────────────────────────────────────────────────────────────

def _buscar_topicos_sem_embedding(conn: sqlite3.Connection) -> List[dict]:
    """Retorna todos os tópicos sem embedding (id + texto)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT t.id, COALESCE(t.texto_original, t.texto_reescrito, '') as texto
        FROM topicos t
        WHERE t.embedding IS NULL
        ORDER BY t.id ASC
    """)
    return [{"id": row[0], "texto": row[1]} for row in cur.fetchall()]


def _gravar_embedding(conn: sqlite3.Connection, topico_id: int, vetor: List[float]):
    """Grava o embedding serializado como JSON na coluna embedding."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE topicos SET embedding = ? WHERE id = ?",
        (json.dumps(vetor), topico_id)
    )
    conn.commit()


def _reprocessar(
    conn: sqlite3.Connection,
    topicos: List[dict],
    ai_engine,
    lote: int,
    dry_run: bool,
) -> dict:
    """
    Processa os tópicos em lotes, gerando e gravando embeddings.
    Retorna relatório com contadores.
    """
    total_proc = len(topicos)
    atualizados = 0
    falhas      = 0
    ids_falha: List[int] = []
    inicio_geral = time.time()

    # Tqdm ou fallback simples
    if TQDM_DISPONIVEL:
        iterador = tqdm(
            topicos,
            desc="Reprocessando embeddings",
            unit="tópico",
            bar_format="{desc}: {n_fmt}/{total_fmt} [{percentage:.0f}%] ETA: {remaining}",
        )
    else:
        iterador = topicos

    try:
        for i, topico in enumerate(iterador):
            tid   = topico["id"]
            texto = topico["texto"].strip()

            # Texto vazio não vale tentar gerar embedding
            if not texto:
                log.warning(f"Tópico id={tid} sem texto — pulado.")
                falhas += 1
                ids_falha.append(tid)
                continue

            try:
                vetor = ai_engine.gerar_embedding(texto[:6000])  # limite de tokens
            except Exception as e:
                log.warning(f"Exceção ao gerar embedding id={tid}: {e}")
                vetor = None

            # Vetor inválido = todos zeros ou None
            if not vetor or all(v == 0.0 for v in vetor):
                log.warning(f"Falha embedding id={tid} — vetor nulo ou inválido.")
                falhas += 1
                ids_falha.append(tid)
            else:
                if not dry_run:
                    _gravar_embedding(conn, tid, vetor)
                atualizados += 1

            # Pausa entre lotes para evitar rate-limit
            if (i + 1) % lote == 0 and (i + 1) < total_proc:
                if not TQDM_DISPONIVEL:
                    pct_done = (i + 1) / total_proc * 100
                    print(f"  → Lote concluído: {i+1}/{total_proc} ({pct_done:.0f}%)")
                time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\n  ⚠️  Interrompido pelo usuário (Ctrl+C).")
        print("  Progresso parcial será exibido abaixo.\n")

    tempo_total = time.time() - inicio_geral
    taxa = (atualizados / total_proc * 100) if total_proc > 0 else 0.0

    return {
        "processados":  total_proc,
        "atualizados":  atualizados,
        "falhas":       falhas,
        "ids_falha":    ids_falha,
        "taxa":         taxa,
        "tempo":        tempo_total,
        "dry_run":      dry_run,
    }


def _exibir_relatorio_reprocessamento(rel: dict):
    """Imprime o relatório final de reprocessamento."""
    L = 56
    linhas_box = [
        "RELATÓRIO DE REPROCESSAMENTO",
        "---",
        f"Tópicos processados:    {rel['processados']}",
        f"Embeddings gerados:     {rel['atualizados']} ✅",
        f"Falhas (API):           {rel['falhas']} ❌",
        f"Taxa de sucesso:        {rel['taxa']:.1f}%",
        f"Tempo total:            {_formatar_tempo(rel['tempo'])}",
    ]
    print("\n" + _box(linhas_box, L))

    if rel["falhas"] > 0:
        ids_str = ", ".join(str(i) for i in rel["ids_falha"][:20])
        if len(rel["ids_falha"]) > 20:
            ids_str += f" ... (+{len(rel['ids_falha']) - 20} mais)"
        print(f"\n  IDs com falha: {ids_str}")
        print(
            "  Dica: verifique GEMINI_API_KEY e conexão com a internet,\n"
            "  então execute novamente para reprocessar apenas os pendentes."
        )

    if rel["dry_run"]:
        print("\n  ⚙️  MODO SIMULAÇÃO — nenhuma alteração foi gravada no banco.")


# ──────────────────────────────────────────────────────────────────────────────
#  PONTO DE ENTRADA
# ──────────────────────────────────────────────────────────────────────────────

def _parse_args():
    parser = argparse.ArgumentParser(
        prog="verify_embeddings",
        description=(
            "Diagnóstico e reprocessamento de embeddings — "
            "Cérebro de Engenharia Diagnóstica v2.0"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python verify_embeddings.py\n"
            "  python verify_embeddings.py --banco cerebro_pericial.db\n"
            "  python verify_embeddings.py --banco cerebro_pericial.db --reprocessar\n"
            "  python verify_embeddings.py --banco cerebro_pericial.db --reprocessar --lote 10 --dry-run\n"
        ),
    )
    parser.add_argument(
        "--banco",
        default="cerebro_pericial.db",
        metavar="PATH",
        help="Caminho para o banco cerebro_pericial.db (default: ./cerebro_pericial.db)",
    )
    parser.add_argument(
        "--reprocessar",
        action="store_true",
        help="Ativa o modo de reprocessamento dos tópicos sem embedding",
    )
    parser.add_argument(
        "--lote",
        type=int,
        default=20,
        metavar="N",
        help="Tamanho do lote para reprocessamento (1–100, default: 20)",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=10,
        metavar="N",
        help="Quantos tópicos sem embedding listar no diagnóstico (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Simula o reprocessamento sem gravar no banco",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    # Validar intervalo do lote
    lote = max(1, min(100, args.lote))
    if lote != args.lote:
        log.warning(f"--lote ajustado para {lote} (válido: 1–100).")

    # ── Abrir banco ───────────────────────────────────────────────────────────
    conn = _abrir_banco(args.banco)

    # ── DIAGNÓSTICO (sempre) ──────────────────────────────────────────────────
    print(f"\n  📂 Banco: {os.path.abspath(args.banco)}")
    info = _diagnosticar(conn, limite=args.limite)
    _exibir_diagnostico(info, args.banco, limite=args.limite)

    if not args.reprocessar:
        conn.close()
        if info["sem_emb"] > 0:
            print(
                "\n  💡 Execute com --reprocessar para gerar os embeddings faltantes.\n"
                "     Exemplo: python verify_embeddings.py --banco "
                f"{args.banco} --reprocessar\n"
            )
        return

    # ── REPROCESSAMENTO ───────────────────────────────────────────────────────
    if info["sem_emb"] == 0:
        print("\n  ✅ Nenhum tópico sem embedding. Reprocessamento desnecessário.\n")
        conn.close()
        return

    # Verificar ai_engine disponível
    if not AI_ENGINE_DISPONIVEL:
        log.error(
            "Reprocessamento cancelado: ai_engine não pôde ser importado.\n"
            "  ➡  Certifique-se de que este script está no mesmo diretório do projeto\n"
            "  ➡  e que as dependências estão instaladas."
        )
        conn.close()
        sys.exit(1)

    # Carregar .env para pegar GEMINI_API_KEY automaticamente
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # Continua sem .env — api_key pode vir de variável de ambiente

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        log.warning(
            "GEMINI_API_KEY não encontrada no ambiente. "
            "Os embeddings serão gerados como vetores nulos (fallback offline). "
            "Configure o .env ou a variável de ambiente para geração real."
        )

    # Inicializar AIEngine
    try:
        ai_engine = AIEngine(api_key=api_key)
    except Exception as e:
        log.error(f"Erro ao inicializar AIEngine: {e}")
        conn.close()
        sys.exit(1)

    # Buscar todos os tópicos sem embedding
    topicos = _buscar_topicos_sem_embedding(conn)

    # Confirmação do usuário (exceto em dry-run)
    if not args.dry_run:
        print(f"\n  ⚙️  Deseja reprocessar {len(topicos)} tópico(s) sem embedding?")
        resp = input("  [S/N]: ").strip().upper()
        if resp != "S":
            print("  Reprocessamento cancelado.")
            conn.close()
            return
    else:
        print(f"\n  ⚙️  MODO SIMULAÇÃO — {len(topicos)} tópico(s) seriam processados.")

    # Executar
    relatorio = _reprocessar(
        conn=conn,
        topicos=topicos,
        ai_engine=ai_engine,
        lote=lote,
        dry_run=args.dry_run,
    )
    _exibir_relatorio_reprocessamento(relatorio)

    conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
migrate_palavras_chave.py — Migração do Banco para Palavras-Chave v2.0

Reprocessa todos os tópicos com palavras-chave de baixa qualidade,
aplicando o novo algoritmo extrair_palavras_chave_v2() em 4 camadas.

Referência: Seção 6 da especificação de Palavras-Chave v2.0
            IBAPE (2025) items 12.1-12.3 | NBR 13752:2024

USO:
    python migrate_palavras_chave.py --banco cerebro_pericial.db
    python migrate_palavras_chave.py --banco cerebro_pericial.db --dry-run
    python migrate_palavras_chave.py --banco cerebro_pericial.db --usar-ia
    python migrate_palavras_chave.py --banco cerebro_pericial.db --limite 50 --relatorio
    python migrate_palavras_chave.py --banco cerebro_pericial.db --apenas-ruins

OPÇÕES:
    --banco PATH       Caminho do banco SQLite (default: cerebro_pericial.db)
    --usar-ia          Usar Gemini para enriquecer palavras-chave (requer API key)
    --limite N         Processar apenas N tópicos (útil para testes)
    --dry-run          Mostrar resultado sem alterar o banco
    --relatorio        Gerar relatorio_migracao.txt com estatísticas
    --apenas-ruins     Processar apenas tópicos com palavras-chave de baixa qualidade
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("migrate_palavras_chave")

# =============================================================================
# STOPWORDS DE DIAGNÓSTICO — detecta tópicos com palavras-chave ruins
# =============================================================================
STOPWORDS_DIAGNOSTICO = frozenset({
    "laudo", "laudos", "norma", "normas", "estrutura", "estruturas",
    "desempenho", "sistema", "sistemas", "edificação", "edificações",
    "requisito", "requisitos", "construção", "construções",
    "conforme", "descrito", "desenvolvidos", "presente", "análise",
    "sejam", "desenvolvidos", "objeto", "objetivo",
})


def _e_palavras_ruins(palavras_chave: Optional[str]) -> bool:
    """
    Detecta se um tópico tem palavras-chave de baixa qualidade.
    Critério: contém stopwords de diagnóstico OU está vazio.
    """
    if not palavras_chave or palavras_chave.strip() == "":
        return True
    termos = {t.strip().lower() for t in palavras_chave.split(",")}
    return bool(termos & STOPWORDS_DIAGNOSTICO)


def diagnosticar_banco(conn: sqlite3.Connection) -> Dict[str, int]:
    """
    Analisa o banco e classifica tópicos com palavras-chave ruins.

    Returns:
        dict com estatísticas do diagnóstico.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM topicos")
    total = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM topicos WHERE "
        "palavras_chave LIKE '%laudo%' OR palavras_chave LIKE '%conforme%' "
        "OR palavras_chave LIKE '%desenvolvidos%' "
        "OR palavras_chave IS NULL OR palavras_chave = ''"
    )
    ruins = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM topicos WHERE palavras_chave IS NULL OR palavras_chave = ''")
    vazios = cursor.fetchone()[0]

    cursor.execute(
        "SELECT palavras_chave FROM topicos WHERE "
        "palavras_chave IS NOT NULL AND palavras_chave != '' LIMIT 2000"
    )
    rows = cursor.fetchall()
    todos_termos: List[str] = []
    for (pk,) in rows:
        todos_termos += [t.strip().lower() for t in (pk or "").split(",") if t.strip()]

    top20_antes = Counter(todos_termos).most_common(20)

    logger.info(f"  📊 Total de tópicos:        {total}")
    logger.info(f"  ⚠️  Palavras-chave ruins:   {ruins} ({100*ruins//max(total,1)}%)")
    logger.info(f"  ❌  Sem palavras-chave:      {vazios}")

    return {
        "total": total,
        "ruins": ruins,
        "vazios": vazios,
        "top20_antes": top20_antes,
    }


def carregar_topicos(
    conn: sqlite3.Connection,
    apenas_ruins: bool = False,
    limite: Optional[int] = None,
) -> List[Dict]:
    """
    Carrega tópicos do banco para reprocessamento.

    Args:
        conn:        Conexão SQLite.
        apenas_ruins: Se True, filtra apenas tópicos com palavras-chave ruins.
        limite:      Máximo de tópicos a retornar.
    Returns:
        Lista de dicts com id, titulo_topico, texto_original,
        hierarquia, palavras_chave e tipo_fonte.
    """
    cursor = conn.cursor()
    sql = """
        SELECT t.id, t.titulo_topico, t.texto_original,
               t.hierarquia, t.palavras_chave, l.tipo_fonte
        FROM topicos t
        LEFT JOIN laudos l ON t.laudo_id = l.id
        WHERE t.texto_original IS NOT NULL AND t.texto_original != ''
    """
    if apenas_ruins:
        sql += (
            " AND ("
            "t.palavras_chave LIKE '%laudo%' OR "
            "t.palavras_chave LIKE '%conforme%' OR "
            "t.palavras_chave LIKE '%desenvolvidos%' OR "
            "t.palavras_chave IS NULL OR t.palavras_chave = ''"
            ")"
        )
    sql += " ORDER BY t.id"
    if limite:
        sql += f" LIMIT {int(limite)}"

    cursor.execute(sql)
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def reprocessar_topico(
    topico: Dict,
    conn: sqlite3.Connection,
    taxonomy_manager,
    ai_engine=None,
    usar_ia: bool = False,
) -> Tuple[str, str]:
    """
    Reprocessa um único tópico com extrair_palavras_chave_v2.

    Returns:
        Tupla (palavras_chave_antigas, palavras_chave_novas)
    """
    try:
        from processors import extrair_palavras_chave_v2
    except ImportError:
        logger.error("processors.py não encontrado. Abortando.")
        sys.exit(1)

    antigas = topico.get("palavras_chave") or ""
    tipo_doc = topico.get("tipo_fonte") or "laudo_judicial"
    hierarquia = topico.get("hierarquia") or ""
    texto = topico.get("texto_original") or ""

    novas = extrair_palavras_chave_v2(
        texto=texto,
        hierarquia=hierarquia,
        tipo_documento=tipo_doc,
        conn=conn,
        max_palavras=10,
        usar_ia=usar_ia,
        ai_engine=ai_engine,
        taxonomy_manager=taxonomy_manager,
    )
    return antigas, novas


def atualizar_banco(
    conn: sqlite3.Connection,
    topico_id: int,
    novas_palavras: str,
) -> None:
    """Atualiza palavras_chave de um tópico no banco."""
    conn.execute(
        "UPDATE topicos SET palavras_chave = ? WHERE id = ?",
        (novas_palavras, topico_id),
    )


def gerar_relatorio(
    stats_antes: Dict,
    stats_depois: Dict,
    candidatos_stopword: List[str],
    candidatos_canonicos: List[Tuple[str, str]],
    caminho: str = "relatorio_migracao.txt",
    dry_run: bool = False,
) -> None:
    """Gera relatório textual da migração."""
    linhas = [
        "=" * 70,
        f"  RELATÓRIO DE MIGRAÇÃO — Palavras-Chave v2.0",
        f"  Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Modo: {'DRY-RUN (sem alterações)' if dry_run else 'APLICADO'}",
        "=" * 70,
        "",
        "ANTES DA MIGRAÇÃO:",
        f"  Total de tópicos:          {stats_antes['total']}",
        f"  Tópicos com palavras ruins: {stats_antes['ruins']}",
        f"  Tópicos sem palavras-chave: {stats_antes['vazios']}",
        "",
        "  Top 20 palavras-chave ANTES:",
    ]
    for i, (termo, freq) in enumerate(stats_antes.get("top20_antes", []), 1):
        linhas.append(f"    {i:2d}. {termo} ({freq}x)")

    linhas += [
        "",
        "DEPOIS DA MIGRAÇÃO:",
        f"  Total reprocessados:       {stats_depois.get('reprocessados', 0)}",
        f"  Com Camada 1 (normativas): {stats_depois.get('com_camada1', 0)}",
        f"  Com Camada 2 (periciais):  {stats_depois.get('com_camada2', 0)}",
        f"  Sem palavras (não-técn.):  {stats_depois.get('sem_palavras', 0)}",
        "",
        "  Top 20 palavras-chave DEPOIS:",
    ]
    for i, (termo, freq) in enumerate(stats_depois.get("top20_depois", []), 1):
        linhas.append(f"    {i:2d}. {termo} ({freq}x)")

    if candidatos_stopword:
        linhas += [
            "",
            f"⚠️  CANDIDATOS A NOVAS STOPWORDS (aparecem em > 60% dos tópicos):",
        ]
        for t in candidatos_stopword[:20]:
            linhas.append(f"    - {t}")

    if candidatos_canonicos:
        linhas += [
            "",
            "💡 CANDIDATOS A TERMOS_CANONICOS (variantes frequentes):",
        ]
        for variante, canonico in candidatos_canonicos[:10]:
            linhas.append(f"    '{variante}' → '{canonico}'")

    linhas += ["", "=" * 70]
    conteudo = "\n".join(linhas)
    print("\n" + conteudo)
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(conteudo)
        print(f"\n  📄 Relatório salvo em: {caminho}")
    except Exception as e:
        logger.warning(f"Não foi possível salvar relatório: {e}")


def detectar_candidatos_stopword(
    conn: sqlite3.Connection, threshold: float = 0.6
) -> List[str]:
    """
    Detecta termos que aparecem em > threshold dos tópicos.
    Candidatos a novas stopwords técnicas.
    """
    cursor = conn.cursor()
    total = cursor.execute("SELECT COUNT(*) FROM topicos").fetchone()[0]
    if total == 0:
        return []
    cursor.execute(
        "SELECT palavras_chave FROM topicos WHERE palavras_chave IS NOT NULL AND palavras_chave != ''"
    )
    todos: List[str] = []
    for (pk,) in cursor.fetchall():
        todos += [t.strip().lower() for t in (pk or "").split(",") if t.strip()]
    contagem = Counter(todos)
    return [
        termo for termo, freq in contagem.most_common(50)
        if freq / total > threshold and len(termo) > 3
    ]


# =============================================================================
# TESTES UNITÁRIOS (Seção 9 da especificação)
# =============================================================================

def executar_testes(taxonomy_manager) -> bool:
    """
    Executa os 7 testes unitários definidos na especificação.
    Returns:
        True se todos passaram, False se algum falhou.
    """
    from processors import extrair_palavras_chave_v2
    resultados: List[Tuple[str, bool, str]] = []

    def verificar(nome: str, condicao: bool, detalhe: str = "") -> None:
        resultados.append((nome, condicao, detalhe))
        status = "✅ PASSOU" if condicao else "❌ FALHOU"
        print(f"  {status}: {nome}" + (f" — {detalhe}" if detalhe and not condicao else ""))

    print("\n" + "=" * 60)
    print("  🧪 TESTES UNITÁRIOS — Palavras-Chave v2.0")
    print("=" * 60)

    # TESTE 1 — Seção não técnica retorna vazio
    r1 = extrair_palavras_chave_v2(
        "O imóvel está na Rua Hortência, Jardins Nápoles...",
        "H01 PREÂMBULO", "laudo_judicial",
        taxonomy_manager=taxonomy_manager,
    )
    verificar("TESTE 1 — Seção não técnica retorna vazio", r1 == "", f"retornou: '{r1}'")

    # TESTE 2 — NBR com número sempre incluída (Camada 1)
    r2 = extrair_palavras_chave_v2(
        "Conforme ABNT NBR 6118:2023, o cobrimento mínimo de 25 mm deve ser respeitado.",
        "H20 CRITÉRIO NORMATIVO", "norma_abnt",
        taxonomy_manager=taxonomy_manager,
    )
    verificar("TESTE 2a — NBR indexada", "nbr 6118" in r2.lower() or "6118" in r2.lower(), r2)
    verificar("TESTE 2b — Parâmetro 25 mm indexado", "25 mm" in r2.lower(), r2)
    verificar("TESTE 2c — 'laudo' não indexado", "laudo" not in r2.lower(), r2)

    # TESTE 3 — Normalização canônica (trinca → fissura)
    r3 = extrair_palavras_chave_v2(
        "Trincas e rachaduras mapeadas na vedação.",
        "H28 ANOMALIA IDENTIFICADA", "laudo_judicial",
        taxonomy_manager=taxonomy_manager,
    )
    verificar("TESTE 3a — 'trinca' normalizada para 'fissura'", "fissura" in r3.lower(), r3)
    verificar("TESTE 3b — 'trinca' não presente", "trinca" not in r3.lower(), r3)
    verificar("TESTE 3c — 'rachadura' não presente", "rachadura" not in r3.lower(), r3)

    # TESTE 4 — Classificação IBAPE indexada (Camada 2)
    r4 = extrair_palavras_chave_v2(
        "A anomalia é de origem endógena, configurando vício construtivo. Nexo causal identificado.",
        "H30 NEXO CAUSAL", "laudo_judicial",
        taxonomy_manager=taxonomy_manager,
    )
    verificar(
        "TESTE 4a — 'anomalia endógena' ou 'endógena' presente",
        "endógena" in r4.lower() or "anomalia endógena" in r4.lower(),
        r4,
    )
    verificar("TESTE 4b — 'vício construtivo' presente", "vício" in r4.lower(), r4)
    verificar("TESTE 4c — 'nexo causal' presente", "nexo" in r4.lower(), r4)

    # TESTE 5 — Stopwords técnicas excluídas
    r5 = extrair_palavras_chave_v2(
        "O presente laudo pericial, conforme norma e requisitos da edificação, estabelece desempenho.",
        "H05 ANÁLISE TÉCNICA", "laudo_judicial",
        taxonomy_manager=taxonomy_manager,
    )
    for sw in ["laudo", "norma", "desempenho", "edificação", "requisito", "conforme", "presente"]:
        verificar(f"TESTE 5 — stopword '{sw}' excluída", sw not in r5.lower(), r5)

    # TESTE 6 — Endereço não indexado como técnico
    r6 = extrair_palavras_chave_v2(
        "Imóvel localizado à Rua Hortência, 42, Condomínio Jardins Nápoles, São Paulo/SP.",
        "H12 CARACTERIZAÇÃO DA REGIÃO", "laudo_judicial",
        taxonomy_manager=taxonomy_manager,
    )
    verificar("TESTE 6a — 'jardins' não indexado", "jardins" not in r6.lower(), r6)
    verificar("TESTE 6b — 'hortência' não indexado", "hortência" not in r6.lower(), r6)
    verificar("TESTE 6c — 'nápoles' não indexado", "nápoles" not in r6.lower(), r6)

    # TESTE 7 — Verificar prioridade de NBR sobre outros termos
    r7 = extrair_palavras_chave_v2(
        "NBR 15575. Eflorescência ativa. Cobrimento insuficiente. Vício construtivo. 15 mm.",
        "H25 ANOMALIA", "laudo_judicial",
        taxonomy_manager=taxonomy_manager,
    )
    r7_lista = [t.strip() for t in r7.split(",")]
    nbr_idx = next((i for i, t in enumerate(r7_lista) if "15575" in t or "nbr" in t.lower()), -1)
    eflo_idx = next((i for i, t in enumerate(r7_lista) if "eflorescência" in t.lower()), 999)
    verificar(
        "TESTE 7 — NBR antes de eflorescência na lista",
        nbr_idx != -1 and nbr_idx <= eflo_idx,
        f"NBR pos={nbr_idx}, eflorescência pos={eflo_idx} | {r7}",
    )

    passou = sum(1 for _, ok, _ in resultados if ok)
    total = len(resultados)
    print(f"\n  Resultado: {passou}/{total} testes passaram.")
    print("=" * 60)
    return passou == total


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migração de Palavras-Chave para v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--banco", default="cerebro_pericial.db", help="Caminho do banco SQLite")
    parser.add_argument("--usar-ia", action="store_true", help="Usar Gemini para enriquecer")
    parser.add_argument("--limite", type=int, default=None, help="Processar apenas N tópicos")
    parser.add_argument("--dry-run", action="store_true", help="Simular sem alterar o banco")
    parser.add_argument("--relatorio", action="store_true", help="Gerar relatorio_migracao.txt")
    parser.add_argument("--apenas-ruins", action="store_true", help="Apenas tópicos com palavras ruins")
    parser.add_argument("--testes", action="store_true", help="Executar testes unitários e sair")
    args = parser.parse_args()

    # Valida banco
    if not os.path.exists(args.banco):
        logger.error(f"Banco não encontrado: {args.banco}")
        sys.exit(1)

    # Carrega TaxonomyManager
    try:
        from taxonomy_manager import TaxonomyManager
        tm = TaxonomyManager()
        logger.info("✅ TaxonomyManager carregado.")
    except Exception as e:
        logger.error(f"TaxonomyManager não disponível: {e}")
        sys.exit(1)

    # Modo testes
    if args.testes:
        sucesso = executar_testes(tm)
        sys.exit(0 if sucesso else 1)

    # Carrega AIEngine se necessário
    ai_engine = None
    if args.usar_ia:
        try:
            from ai_engine import AIEngine
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.getenv("GEMINI_API_KEY", "")
            ai_engine = AIEngine(api_key=api_key)
            if ai_engine.ia_disponivel:
                logger.info("✅ AIEngine conectado (Gemini).")
            else:
                logger.warning("⚠️  AIEngine sem API key — enriquecimento IA desativado.")
                ai_engine = None
        except Exception as e:
            logger.warning(f"AIEngine não disponível: {e}")

    # Conecta ao banco
    conn = sqlite3.connect(args.banco)
    conn.execute("PRAGMA journal_mode=WAL")

    print("\n" + "=" * 60)
    print("  🔄 MIGRAÇÃO DE PALAVRAS-CHAVE v2.0")
    print(f"  Banco: {args.banco}")
    print(f"  Modo:  {'DRY-RUN' if args.dry_run else 'APLICAR ALTERAÇÕES'}")
    print("=" * 60)

    # Diagnóstico inicial
    print("\n📊 DIAGNÓSTICO INICIAL:")
    stats_antes = diagnosticar_banco(conn)

    # Carrega tópicos
    topicos = carregar_topicos(conn, apenas_ruins=args.apenas_ruins, limite=args.limite)
    print(f"\n  📋 Tópicos a processar: {len(topicos)}")

    if not topicos:
        print("  ✅ Nenhum tópico para reprocessar.")
        conn.close()
        return

    # Reprocessamento
    print(f"\n⚙️  REPROCESSANDO...")
    reprocessados = 0
    com_camada1 = 0
    com_camada2 = 0
    sem_palavras = 0
    todos_termos_novos: List[str] = []

    for i, topico in enumerate(topicos, 1):
        antigas, novas = reprocessar_topico(
            topico, conn, tm, ai_engine, usar_ia=args.usar_ia
        )

        # Estatísticas
        reprocessados += 1
        if novas:
            termos_novos = [t.strip().lower() for t in novas.split(",") if t.strip()]
            todos_termos_novos += termos_novos
            # Verifica se tem entidades normativas (Camada 1)
            import re as _re
            if any(_re.search(r'nbr|\d+\s*(mm|cm|mpa|kpa|%)', t) for t in termos_novos):
                com_camada1 += 1
            # Verifica se tem termos periciais (Camada 2)
            if tm.buscar_vocabulario_pericial(termos_novos[0] if termos_novos else ""):
                com_camada2 += 1
        else:
            sem_palavras += 1

        # Aplica no banco
        if not args.dry_run:
            atualizar_banco(conn, topico["id"], novas)

        # Progresso
        if i % 100 == 0 or i == len(topicos):
            print(f"  [{i:4d}/{len(topicos)}] ID={topico['id']} | "
                  f"'{topico.get('titulo_topico','')[:40]}' → '{novas[:60]}'")

    # Commit
    if not args.dry_run:
        conn.commit()
        print(f"\n  ✅ {reprocessados} tópicos atualizados no banco.")
    else:
        print(f"\n  🔍 DRY-RUN concluído — nenhuma alteração aplicada.")

    # Estatísticas após
    top20_depois = Counter(todos_termos_novos).most_common(20)
    stats_depois = {
        "reprocessados": reprocessados,
        "com_camada1": com_camada1,
        "com_camada2": com_camada2,
        "sem_palavras": sem_palavras,
        "top20_depois": top20_depois,
    }

    print(f"\n  📊 Resumo: {reprocessados} reprocessados | "
          f"{com_camada1} com NBR | {com_camada2} com termos periciais | "
          f"{sem_palavras} seções não-técnicas")

    # Candidatos a novas stopwords
    candidatos_sw = detectar_candidatos_stopword(conn, threshold=0.6)
    if candidatos_sw:
        print(f"\n  ⚠️  Candidatos a stopwords (> 60% dos tópicos): "
              f"{', '.join(candidatos_sw[:10])}")

    # Relatório
    if args.relatorio:
        gerar_relatorio(
            stats_antes, stats_depois,
            candidatos_sw, [],
            caminho="relatorio_migracao.txt",
            dry_run=args.dry_run,
        )

    conn.close()
    print("\n  🏁 Migração concluída!")


if __name__ == "__main__":
    main()

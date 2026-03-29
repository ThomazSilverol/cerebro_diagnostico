"""
migrations.py — Migrações Unificadas do Banco de Dados
Sistema: Cérebro de Engenharia Diagnóstica v2.0

Consolida em um único arquivo:
  • Tabelas de resiliência (embedding_cache, gut_sessao_parcial)
  • Tabelas de reprocessamento (reprocessamento_log, auditoria_mudancas)
  • Dicionário pericial de sinônimos
  • Colunas GUT e rastreamento IA em topicos

Execução direta: python migrations.py [caminho_do_banco]
Uso por código: from migrations import aplicar_todas; aplicar_todas(conn)

Idempotente — seguro rodar múltiplas vezes.
"""
from __future__ import annotations
import json
import sqlite3
import sys
import logging

logger = logging.getLogger("migrations")

# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 1 — Tabelas de resiliência (ai_health_monitor / gut_adaptativo)
# ─────────────────────────────────────────────────────────────────────────────

_DDL_EMBEDDING_CACHE = """
CREATE TABLE IF NOT EXISTS embedding_cache (
    query_hash     TEXT PRIMARY KEY,
    query_texto    TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    hits           INTEGER DEFAULT 0
);"""

_DDL_GUT_SESSAO = """
CREATE TABLE IF NOT EXISTS gut_sessao_parcial (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL UNIQUE,
    descricao      TEXT NOT NULL,
    subsistema     TEXT DEFAULT NULL,
    nexo_json      TEXT DEFAULT NULL,
    respostas_json TEXT DEFAULT '{}',
    etapa_atual    TEXT DEFAULT NULL,
    timestamp      TEXT NOT NULL,
    expirado       INTEGER DEFAULT 0
);"""

_DDL_GUT_SESSAO_IDX = """
CREATE INDEX IF NOT EXISTS idx_gut_sessao_expirado
ON gut_sessao_parcial (expirado, timestamp);"""

# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 2 — Tabelas de reprocessamento multifásico
# ─────────────────────────────────────────────────────────────────────────────

_DDL_REPROCESSAMENTO_LOG = """
CREATE TABLE IF NOT EXISTS reprocessamento_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    documento_id       INTEGER,
    fase               INTEGER NOT NULL,
    data_inicio        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_fim           TIMESTAMP,
    modo               TEXT NOT NULL,
    campos_modificados INTEGER DEFAULT 0,
    novos_itens        INTEGER DEFAULT 0,
    erros_detectados   INTEGER DEFAULT 0,
    confianca_media    REAL DEFAULT 0.0,
    status             TEXT NOT NULL,
    mensagem           TEXT,
    FOREIGN KEY(documento_id) REFERENCES laudos(id)
);"""

_DDL_AUDITORIA = """
CREATE TABLE IF NOT EXISTS auditoria_mudancas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topico_id    INTEGER,
    documento_id INTEGER,
    fase         INTEGER DEFAULT 0,
    campo        TEXT NOT NULL,
    valor_antes  TEXT,
    valor_depois TEXT,
    responsavel  TEXT NOT NULL,
    timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(topico_id)    REFERENCES topicos(id),
    FOREIGN KEY(documento_id) REFERENCES laudos(id)
);"""

_DDL_DICIONARIO = """
CREATE TABLE IF NOT EXISTS dicionario_pericial_sinonimos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    conceito   TEXT UNIQUE NOT NULL,
    sinonimos  TEXT NOT NULL,
    categoria  TEXT DEFAULT '',
    frequencia INTEGER DEFAULT 0,
    confianca  REAL DEFAULT 0.8
);"""

# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 3 — Novas colunas em topicos (rastreamento IA + GUT)
# ─────────────────────────────────────────────────────────────────────────────

_COLUNAS_TOPICOS: list[tuple[str, str]] = [
    # Rastreamento de reprocessamento
    ("status_processamento",  "TEXT DEFAULT 'nao_iniciado'"),
    ("versao_processamento",  "INTEGER DEFAULT 1"),
    ("historico_mudancas",    "TEXT DEFAULT '[]'"),
    # Análise IA
    ("tipo_anomalia",         "TEXT DEFAULT ''"),
    ("origem_patologica",     "TEXT DEFAULT ''"),
    ("mecanismo",             "TEXT DEFAULT ''"),
    ("ia_score_confianca",    "REAL DEFAULT 0.0"),
    ("ia_modelo",             "TEXT DEFAULT ''"),
    ("ia_timestamp",          "TIMESTAMP"),
    # GUT estendido
    ("gut_versao",            "TEXT DEFAULT ''"),
    ("gut_nexo_json",         "TEXT DEFAULT ''"),
    ("gut_session_id",        "TEXT DEFAULT ''"),
    # Avaliação manual do perito
    ("favorito",              "INTEGER DEFAULT 0"),
    ("comentario_usuario",    "TEXT DEFAULT ''"),
    # Hierarquia pai-filho
    ("topico_pai_id",         "INTEGER DEFAULT NULL"),
]

# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 3-B — Tabelas de extração estruturada e contextos normativos
# ─────────────────────────────────────────────────────────────────────────────

_DDL_LAUDOS_ESTRUTURADO = """
CREATE TABLE IF NOT EXISTS laudos_estruturado (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    laudo_id                  INTEGER NOT NULL REFERENCES laudos(id) ON DELETE CASCADE,
    topico_id                 INTEGER REFERENCES topicos(id) ON DELETE CASCADE,
    patologias                TEXT    DEFAULT '[]',
    estruturas                TEXT    DEFAULT '[]',
    materiais                 TEXT    DEFAULT '[]',
    locais                    TEXT    DEFAULT '[]',
    normas_identificadas      TEXT    DEFAULT '[]',
    palavras_chave_primarias  TEXT    DEFAULT '[]',
    palavras_chave_secundarias TEXT   DEFAULT '[]',
    titulo_sugerido           TEXT    DEFAULT '',
    sumario                   TEXT    DEFAULT '',
    causa_raiz                TEXT    DEFAULT '',
    nexo_causal               TEXT    DEFAULT '',
    relacoes_patologicas      TEXT    DEFAULT '[]',
    score_risco               TEXT    DEFAULT '',
    recomendacao              TEXT    DEFAULT '',
    confianca_extracao        TEXT    DEFAULT 'BAIXA',
    confianca_refinada        REAL    DEFAULT 0.0,
    status_relevancia         TEXT    DEFAULT '',
    motivo_irrelevancia       TEXT    DEFAULT '',
    prompt_refinamento        TEXT    DEFAULT '',
    modelo_fase1              TEXT    DEFAULT '',
    modelo_fase2              TEXT    DEFAULT '',
    processado_fase1          INTEGER DEFAULT 0,
    processado_fase2          INTEGER DEFAULT 0,
    timestamp_fase1           TIMESTAMP,
    timestamp_fase2           TIMESTAMP
);"""

_DDL_CONTEXTOS_NORMATIVOS = """
CREATE TABLE IF NOT EXISTS contextos_normativos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    norma           TEXT    NOT NULL,
    item            TEXT    DEFAULT '',
    titulo          TEXT    DEFAULT '',
    descricao       TEXT    NOT NULL,
    categoria       TEXT    DEFAULT '',
    aplicacao       TEXT    DEFAULT '',
    embedding       TEXT    DEFAULT '[]',
    laudo_origem_id INTEGER REFERENCES laudos(id),
    confianca       TEXT    DEFAULT 'ALTA',
    data_inclusao   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);"""

_DDL_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_topicos_status      ON topicos (status_processamento);",
    "CREATE INDEX IF NOT EXISTS idx_topicos_laudo       ON topicos (laudo_id);",
    "CREATE INDEX IF NOT EXISTS idx_repro_fase          ON reprocessamento_log (fase, status);",
    "CREATE INDEX IF NOT EXISTS idx_auditoria_top       ON auditoria_mudancas (topico_id);",
    "CREATE INDEX IF NOT EXISTS idx_laud_est_laudo      ON laudos_estruturado (laudo_id);",
    "CREATE INDEX IF NOT EXISTS idx_laud_est_topico     ON laudos_estruturado (topico_id);",
    "CREATE INDEX IF NOT EXISTS idx_laud_est_confianca  ON laudos_estruturado (confianca_extracao);",
    "CREATE INDEX IF NOT EXISTS idx_laud_est_risco      ON laudos_estruturado (score_risco);",
    "CREATE INDEX IF NOT EXISTS idx_laud_est_fase1      ON laudos_estruturado (processado_fase1);",
    "CREATE INDEX IF NOT EXISTS idx_laud_est_fase2      ON laudos_estruturado (processado_fase2);",
    "CREATE INDEX IF NOT EXISTS idx_ctx_norma           ON contextos_normativos (norma);",
    "CREATE INDEX IF NOT EXISTS idx_ctx_categoria       ON contextos_normativos (categoria);",
    "CREATE INDEX IF NOT EXISTS idx_topicos_pai         ON topicos (topico_pai_id);",
    "CREATE INDEX IF NOT EXISTS idx_trechos_usados_tp   ON trechos_utilizados (topico_id);",
    "CREATE INDEX IF NOT EXISTS idx_trechos_usados_ss   ON trechos_utilizados (sessao_id);",
]

# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 6 — Melhorias arquiteturais M4/M5/M6/M7 (2026-03-27)
# ─────────────────────────────────────────────────────────────────────────────

# M6: contagem de tokens por chunk
_COL_TOKEN_COUNT = ("token_count", "INTEGER DEFAULT NULL")

# M5: rastreabilidade quesito → chunk
_COL_QUESITO_TOPICO = ("topico_id", "INTEGER DEFAULT NULL")

# M7: tabela de análise IA separada do texto original
_DDL_TOPICOS_ANALISE_IA = """
CREATE TABLE IF NOT EXISTS topicos_analise_ia (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topico_id       INTEGER NOT NULL UNIQUE,
    texto_reescrito TEXT,
    modelo_ia       TEXT    DEFAULT NULL,
    versao_analise  INTEGER DEFAULT 1,
    criado_em       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(topico_id) REFERENCES topicos(id)
);"""

_DDL_TOPICOS_ANALISE_IA_IDX = """
CREATE INDEX IF NOT EXISTS idx_tai_topico ON topicos_analise_ia(topico_id);"""

# M7: migração — copia texto_reescrito existente para nova tabela
_SQL_MIGRAR_ANALISE_IA = """
INSERT OR IGNORE INTO topicos_analise_ia (topico_id, texto_reescrito)
SELECT id, texto_reescrito FROM topicos
WHERE texto_reescrito IS NOT NULL
  AND texto_reescrito != ''
  AND texto_reescrito != texto_original;"""

# M4: tabela unificada de parâmetros
_DDL_PARAMETROS = """
CREATE TABLE IF NOT EXISTS parametros (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    laudo_id       INTEGER,
    topico_id      INTEGER,
    nome_parametro TEXT    NOT NULL,
    valor_texto    TEXT    DEFAULT NULL,
    valor_minimo   REAL    DEFAULT NULL,
    valor_maximo   REAL    DEFAULT NULL,
    valor_ponto    REAL    DEFAULT NULL,
    unidade        TEXT    DEFAULT '',
    contexto       TEXT    DEFAULT '',
    norma_ref      TEXT    DEFAULT '',
    item_ref       TEXT    DEFAULT '',
    pagina         INTEGER DEFAULT 0,
    origem         TEXT    DEFAULT 'extraido',
    FOREIGN KEY(laudo_id)  REFERENCES laudos(id),
    FOREIGN KEY(topico_id) REFERENCES topicos(id)
);"""

_DDL_PARAMETROS_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_param_nome  ON parametros(nome_parametro);",
    "CREATE INDEX IF NOT EXISTS idx_param_laudo ON parametros(laudo_id);",
]

# M4: migração de dados — copia registros legados para tabela unificada
_SQL_MIGRAR_PARAMETROS_NORMATIVOS = """
INSERT OR IGNORE INTO parametros
    (laudo_id, topico_id, nome_parametro, valor_texto,
     unidade, contexto, item_ref, pagina, origem)
SELECT laudo_id, topico_id, parametro, valor,
       unidade, contexto, item_ref, pagina, 'normativo'
FROM parametros_normativos
WHERE NOT EXISTS (
    SELECT 1 FROM parametros p2
    WHERE p2.laudo_id   = parametros_normativos.laudo_id
      AND p2.topico_id  = parametros_normativos.topico_id
      AND p2.nome_parametro = parametros_normativos.parametro
      AND p2.origem = 'normativo'
);"""

_SQL_MIGRAR_PARAMETROS_EXTRAIDOS = """
INSERT OR IGNORE INTO parametros
    (laudo_id, topico_id, nome_parametro, valor_minimo, valor_maximo,
     valor_ponto, unidade, contexto, norma_ref, item_ref, pagina, origem)
SELECT laudo_id, topico_id, nome_parametro, valor_minimo, valor_maximo,
       valor_ponto, unidade, contexto, norma_ref, item_ref, pagina, 'extraido'
FROM parametros_extraidos
WHERE NOT EXISTS (
    SELECT 1 FROM parametros p2
    WHERE p2.laudo_id      = parametros_extraidos.laudo_id
      AND p2.topico_id     = parametros_extraidos.topico_id
      AND p2.nome_parametro = parametros_extraidos.nome_parametro
      AND p2.origem = 'extraido'
);"""

# M6: backfill token_count para tópicos existentes
_SQL_BACKFILL_TOKEN_COUNT = """
UPDATE topicos
SET token_count = length(texto_original) / 4
WHERE token_count IS NULL
  AND texto_original IS NOT NULL;"""

# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 5 — FTS5 (busca full-text nativa em SQLite)
# ─────────────────────────────────────────────────────────────────────────────
# Tabela virtual FTS5 espelhando os campos textuais de topicos.
# tokenize='unicode61 remove_diacritics 1' → "fissura" casa "FISSURA", "fissurà".
# Pesos BM25 por coluna (usados em busca): titulo=8, hierarquia=4,
#   palavras_chave=6, texto_original=1 — igual ao scoring Python existente.

_DDL_TOPICOS_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS topicos_fts USING fts5(
    titulo_topico,
    hierarquia,
    palavras_chave,
    texto_original,
    content='topicos',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 1'
);"""

# Trigger: mantém FTS em sincronia após INSERT em topicos
_DDL_FTS_TRIGGER_INSERT = """
CREATE TRIGGER IF NOT EXISTS topicos_fts_ai
AFTER INSERT ON topicos BEGIN
  INSERT INTO topicos_fts(rowid, titulo_topico, hierarquia, palavras_chave, texto_original)
  VALUES (new.id, new.titulo_topico, new.hierarquia, new.palavras_chave, new.texto_original);
END;"""

# Trigger: mantém FTS em sincronia após DELETE em topicos
_DDL_FTS_TRIGGER_DELETE = """
CREATE TRIGGER IF NOT EXISTS topicos_fts_ad
AFTER DELETE ON topicos BEGIN
  INSERT INTO topicos_fts(topicos_fts, rowid, titulo_topico, hierarquia, palavras_chave, texto_original)
  VALUES ('delete', old.id, old.titulo_topico, old.hierarquia, old.palavras_chave, old.texto_original);
END;"""

# Trigger: mantém FTS em sincronia após UPDATE em topicos
_DDL_FTS_TRIGGER_UPDATE = """
CREATE TRIGGER IF NOT EXISTS topicos_fts_au
AFTER UPDATE ON topicos BEGIN
  INSERT INTO topicos_fts(topicos_fts, rowid, titulo_topico, hierarquia, palavras_chave, texto_original)
  VALUES ('delete', old.id, old.titulo_topico, old.hierarquia, old.palavras_chave, old.texto_original);
  INSERT INTO topicos_fts(rowid, titulo_topico, hierarquia, palavras_chave, texto_original)
  VALUES (new.id, new.titulo_topico, new.hierarquia, new.palavras_chave, new.texto_original);
END;"""

# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 4 — Dicionário pericial base
# ─────────────────────────────────────────────────────────────────────────────

_SINONIMOS: list[dict] = [
    {"conceito": "fissura",           "sinonimos": ["trinca","rachadura","fenda","abertura","fissurado"],         "categoria": "patologia",   "confianca": 0.95},
    {"conceito": "impermeabilização", "sinonimos": ["estanqueidade","infiltração","vazamento","umidade","percolação"], "categoria": "patologia", "confianca": 0.92},
    {"conceito": "corrosão",          "sinonimos": ["ferrugem","oxidação","armadura exposta","carbonatação","desagregação"], "categoria": "patologia", "confianca": 0.95},
    {"conceito": "recalque",          "sinonimos": ["afundamento","cedência","subsidência","assentamento","desnivelamento"], "categoria": "patologia", "confianca": 0.90},
    {"conceito": "desplacamento",     "sinonimos": ["soltura","descolamento","estufamento","queda de revestimento"], "categoria": "patologia",  "confianca": 0.88},
    {"conceito": "eflorescência",     "sinonimos": ["salitre","manchas brancas","cristalização de sais"],         "categoria": "patologia",   "confianca": 0.85},
    {"conceito": "bolor",             "sinonimos": ["mofo","fungo","mancha escura","proliferação fúngica"],       "categoria": "patologia",   "confianca": 0.85},
    {"conceito": "estrutura",         "sinonimos": ["viga","pilar","laje","concreto armado","estrutural","elemento estrutural"], "categoria": "elemento", "confianca": 0.92},
    {"conceito": "fundação",          "sinonimos": ["sapata","estaca","radier","bloco","tubulão","infraestrutura"], "categoria": "elemento",   "confianca": 0.90},
    {"conceito": "revestimento",      "sinonimos": ["azulejo","porcelanato","cerâmica","piso","acabamento"],      "categoria": "elemento",    "confianca": 0.88},
    {"conceito": "argamassa",         "sinonimos": ["reboco","emboço","chapisco","massa","argamassamento"],       "categoria": "material",    "confianca": 0.87},
    {"conceito": "patologia",         "sinonimos": ["anomalia","defeito","falha","dano","manifestação patológica","vício construtivo"], "categoria": "conceito", "confianca": 0.95},
    {"conceito": "norma",             "sinonimos": ["nbr","abnt","iso","requisito","especificação","critério","normativo"], "categoria": "referencia", "confianca": 0.90},
    {"conceito": "laudo",             "sinonimos": ["parecer","vistoria","inspeção","relatório técnico","perícia"], "categoria": "documento",  "confianca": 0.88},
    {"conceito": "nexo causal",       "sinonimos": ["causa raiz","origem","agente causador","responsabilidade técnica"], "categoria": "conceito", "confianca": 0.85},
    {"conceito": "guarda-corpo",      "sinonimos": ["parapeito","corrimão","proteção lateral","gradil","proteção de borda"], "categoria": "elemento", "confianca": 0.88},
    {"conceito": "desempenho",        "sinonimos": ["desempenho térmico","desempenho acústico","vida útil","durabilidade"], "categoria": "conceito", "confianca": 0.85},
]


# ─────────────────────────────────────────────────────────────────────────────
# Função principal
# ─────────────────────────────────────────────────────────────────────────────

def aplicar_todas(conn: sqlite3.Connection) -> dict[str, bool]:
    """
    Aplica todas as migrações. Idempotente.

    Returns:
        Dict {nome_migração: sucesso}
    """
    resultados: dict[str, bool] = {}

    # — Tabelas de resiliência —
    for nome, ddl in [
        ("embedding_cache",    _DDL_EMBEDDING_CACHE),
        ("gut_sessao_parcial", _DDL_GUT_SESSAO),
        ("idx_gut_sessao",     _DDL_GUT_SESSAO_IDX),
    ]:
        try:
            conn.execute(ddl); conn.commit()
            resultados[nome] = True
            logger.info(f"[migrations] '{nome}' OK.")
        except Exception as e:
            resultados[nome] = False
            logger.error(f"[migrations] Falha '{nome}': {e}")

    # — Novas colunas em topicos —
    cols_existentes = {
        r[1] for r in conn.execute("PRAGMA table_info(topicos)").fetchall()
    }
    for nome_col, definicao in _COLUNAS_TOPICOS:
        if nome_col not in cols_existentes:
            try:
                conn.execute(f"ALTER TABLE topicos ADD COLUMN {nome_col} {definicao}")
                resultados[f"col:{nome_col}"] = True
                logger.info(f"[migrations] Coluna adicionada: topicos.{nome_col}")
            except Exception as e:
                resultados[f"col:{nome_col}"] = False
                logger.warning(f"[migrations] Coluna '{nome_col}' não adicionada: {e}")
    conn.commit()

    # — Tabelas de reprocessamento e estruturadas —
    for nome, ddl in [
        ("reprocessamento_log",           _DDL_REPROCESSAMENTO_LOG),
        ("auditoria_mudancas",            _DDL_AUDITORIA),
        ("dicionario_pericial_sinonimos", _DDL_DICIONARIO),
        ("laudos_estruturado",            _DDL_LAUDOS_ESTRUTURADO),
        ("contextos_normativos",          _DDL_CONTEXTOS_NORMATIVOS),
    ]:
        try:
            conn.execute(ddl); conn.commit()
            resultados[nome] = True
        except Exception as e:
            resultados[nome] = False
            logger.error(f"[migrations] Falha '{nome}': {e}")

    # — Novas colunas em laudos_estruturado (módulo de controle de qualidade) —
    cols_le = {r[1] for r in conn.execute("PRAGMA table_info(laudos_estruturado)").fetchall()}
    _COLUNAS_LAUDOS_ESTRUTURADO = [
        ("classificacao_texto",   "TEXT DEFAULT ''"),
        ("score_qualidade",       "REAL DEFAULT 0.0"),
        ("score_fundamentacao",   "REAL DEFAULT 0.0"),
        ("score_aplicabilidade",  "REAL DEFAULT 0.0"),
        ("classificacao_uso",     "TEXT DEFAULT ''"),
        ("justificativa_qualidade", "TEXT DEFAULT ''"),
        ("sugestao_uso",          "TEXT DEFAULT ''"),
    ]
    for nome_col, definicao in _COLUNAS_LAUDOS_ESTRUTURADO:
        if nome_col not in cols_le:
            try:
                conn.execute(f"ALTER TABLE laudos_estruturado ADD COLUMN {nome_col} {definicao}")
                logger.info(f"[migrations] Coluna adicionada: laudos_estruturado.{nome_col}")
            except Exception as e:
                logger.warning(f"[migrations] Coluna '{nome_col}' nao adicionada: {e}")
    conn.commit()

    # — Índices —
    for ddl in _DDL_INDICES:
        try:
            conn.execute(ddl)
        except Exception:
            pass
    conn.commit()

    # — FTS5: tabela virtual + triggers —
    for nome, ddl in [
        ("topicos_fts",        _DDL_TOPICOS_FTS),
        ("topicos_fts_ai",     _DDL_FTS_TRIGGER_INSERT),
        ("topicos_fts_ad",     _DDL_FTS_TRIGGER_DELETE),
        ("topicos_fts_au",     _DDL_FTS_TRIGGER_UPDATE),
    ]:
        try:
            conn.execute(ddl)
            conn.commit()
            resultados[nome] = True
            logger.info(f"[migrations] FTS5 '{nome}' OK.")
        except Exception as e:
            resultados[nome] = False
            logger.warning(f"[migrations] FTS5 '{nome}': {e}")

    # Popula FTS5 com tópicos já existentes (apenas se índice estiver vazio)
    try:
        fts_ok = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='topicos_fts'"
        ).fetchone()
        if fts_ok:
            fts_count = conn.execute("SELECT COUNT(*) FROM topicos_fts").fetchone()[0]
            if fts_count == 0:
                conn.execute(
                    "INSERT INTO topicos_fts(rowid, titulo_topico, hierarquia, "
                    "palavras_chave, texto_original) "
                    "SELECT id, titulo_topico, hierarquia, palavras_chave, texto_original "
                    "FROM topicos"
                )
                conn.commit()
                inserted = conn.execute("SELECT COUNT(*) FROM topicos_fts").fetchone()[0]
                logger.info(f"[migrations] FTS5 populado com {inserted} tópico(s).")
                resultados["fts5_populate"] = True
            else:
                logger.info(f"[migrations] FTS5 já tinha {fts_count} tópico(s), pulando rebuild.")
                resultados["fts5_populate"] = True
    except Exception as e:
        logger.warning(f"[migrations] FTS5 populate: {e}")
        resultados["fts5_populate"] = False

    # ─── BLOCO 6 — Melhorias arquiteturais M4/M5/M6/M7 ────────────────────────

    # M6: coluna token_count em topicos
    cols_top = {r[1] for r in conn.execute("PRAGMA table_info(topicos)").fetchall()}
    nome_col, definicao = _COL_TOKEN_COUNT
    if nome_col not in cols_top:
        try:
            conn.execute(f"ALTER TABLE topicos ADD COLUMN {nome_col} {definicao}")
            resultados[f"col:topicos.{nome_col}"] = True
            logger.info(f"[migrations] Coluna adicionada: topicos.{nome_col}")
        except Exception as e:
            resultados[f"col:topicos.{nome_col}"] = False
            logger.warning(f"[migrations] Coluna '{nome_col}': {e}")
    conn.commit()

    # M5: coluna topico_id em quesitos_respondidos
    cols_q = {r[1] for r in conn.execute("PRAGMA table_info(quesitos_respondidos)").fetchall()}
    nome_col_q, def_q = _COL_QUESITO_TOPICO
    if nome_col_q not in cols_q:
        try:
            conn.execute(f"ALTER TABLE quesitos_respondidos ADD COLUMN {nome_col_q} {def_q}")
            resultados["col:quesitos_respondidos.topico_id"] = True
            logger.info("[migrations] Coluna adicionada: quesitos_respondidos.topico_id")
        except Exception as e:
            resultados["col:quesitos_respondidos.topico_id"] = False
            logger.warning(f"[migrations] Coluna 'topico_id': {e}")
    conn.commit()

    # M7: tabela topicos_analise_ia + migração de dados
    for nome, ddl in [
        ("topicos_analise_ia",     _DDL_TOPICOS_ANALISE_IA),
        ("idx_tai_topico",         _DDL_TOPICOS_ANALISE_IA_IDX),
    ]:
        try:
            conn.execute(ddl); conn.commit()
            resultados[nome] = True
        except Exception as e:
            resultados[nome] = False
            logger.warning(f"[migrations] '{nome}': {e}")
    try:
        conn.execute(_SQL_MIGRAR_ANALISE_IA)
        migradas = conn.execute("SELECT COUNT(*) FROM topicos_analise_ia").fetchone()[0]
        conn.commit()
        resultados["migrar_analise_ia"] = True
        logger.info(f"[migrations] topicos_analise_ia: {migradas} registros migrados.")
    except Exception as e:
        resultados["migrar_analise_ia"] = False
        logger.warning(f"[migrations] migrar_analise_ia: {e}")

    # M4: tabela parametros unificada + migração de dados
    try:
        conn.execute(_DDL_PARAMETROS); conn.commit()
        resultados["parametros"] = True
    except Exception as e:
        resultados["parametros"] = False
        logger.warning(f"[migrations] 'parametros': {e}")
    for ddl in _DDL_PARAMETROS_IDX:
        try:
            conn.execute(ddl)
        except Exception:
            pass
    conn.commit()
    for nome_sql, sql_m in [
        ("migrar_param_normativos", _SQL_MIGRAR_PARAMETROS_NORMATIVOS),
        ("migrar_param_extraidos",  _SQL_MIGRAR_PARAMETROS_EXTRAIDOS),
    ]:
        try:
            conn.execute(sql_m); conn.commit()
            resultados[nome_sql] = True
            logger.info(f"[migrations] {nome_sql}: OK.")
        except Exception as e:
            resultados[nome_sql] = False
            logger.warning(f"[migrations] {nome_sql}: {e}")

    # M6: backfill token_count
    try:
        conn.execute(_SQL_BACKFILL_TOKEN_COUNT); conn.commit()
        resultados["backfill_token_count"] = True
        logger.info("[migrations] token_count: backfill concluído.")
    except Exception as e:
        resultados["backfill_token_count"] = False
        logger.warning(f"[migrations] backfill token_count: {e}")

    # — Dicionário (INSERT OR IGNORE) —
    inseridos = 0
    for item in _SINONIMOS:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO dicionario_pericial_sinonimos "
                "(conceito, sinonimos, categoria, confianca) VALUES (?,?,?,?)",
                (item["conceito"], json.dumps(item["sinonimos"], ensure_ascii=False),
                 item.get("categoria",""), item.get("confianca", 0.8))
            )
            inseridos += 1
        except Exception:
            pass
    conn.commit()
    resultados["dicionario_sinonimos"] = inseridos > 0
    logger.info(f"[migrations] Dicionário: {inseridos} conceito(s) verificado(s).")
    logger.info("[migrations] Todas as migrações aplicadas.")
    return resultados


def verificar(conn: sqlite3.Connection) -> dict:
    """Retorna status de cada tabela e coluna relevante."""
    tabelas = ["embedding_cache","gut_sessao_parcial","reprocessamento_log",
               "auditoria_mudancas","dicionario_pericial_sinonimos",
               "laudos_estruturado","contextos_normativos"]
    status = {}
    for t in tabelas:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)
        ).fetchone()
        status[f"tabela:{t}"] = row is not None

    cols = {r[1] for r in conn.execute("PRAGMA table_info(topicos)").fetchall()}
    for nome_col, _ in _COLUNAS_TOPICOS:
        status[f"col:{nome_col}"] = nome_col in cols

    try:
        qtd = conn.execute("SELECT COUNT(*) FROM dicionario_pericial_sinonimos").fetchone()[0]
        status["dicionario_conceitos"] = qtd
    except Exception:
        status["dicionario_conceitos"] = 0

    # FTS5
    try:
        fts_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='topicos_fts'"
        ).fetchone()
        status["fts5:topicos_fts"] = fts_row is not None
        if fts_row:
            status["fts5:documentos_indexados"] = conn.execute(
                "SELECT COUNT(*) FROM topicos_fts"
            ).fetchone()[0]
    except Exception:
        status["fts5:topicos_fts"] = False

    return status


def reconstruir_fts(conn: sqlite3.Connection) -> int:
    """
    Reconstrói o índice FTS5 do zero a partir de topicos.
    Use quando suspeitar que o índice ficou fora de sincronia.
    Retorna número de tópicos indexados.
    """
    conn.execute("DELETE FROM topicos_fts")
    conn.execute(
        "INSERT INTO topicos_fts(rowid, titulo_topico, hierarquia, "
        "palavras_chave, texto_original) "
        "SELECT id, titulo_topico, hierarquia, palavras_chave, texto_original "
        "FROM topicos"
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM topicos_fts").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Execução direta
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging as _log
    _log.basicConfig(level=_log.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
    db_path = sys.argv[1] if len(sys.argv) > 1 else "banco_pericial.db"
    print(f"\n  Aplicando migrações em: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        aplicar_todas(conn)
        st = verificar(conn)
        print("\n  Status:")
        for k, v in st.items():
            if isinstance(v, bool):
                print(f"    {'✅' if v else '❌'}  {k}")
            else:
                print(f"    ℹ️  {k}: {v}")
        print("\n  ✅ Concluído.\n")
    finally:
        conn.close()

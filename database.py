"""
database.py — Gerenciador de Banco de Dados do Cérebro de Engenharia Diagnóstica
Versão 2.0 — Suporte a embeddings vetoriais, parâmetros normativos, gestão de fontes,
             histórico de sessão e estatísticas de consulta.
"""
import sqlite3
import json
import math
import os
import struct
import logging
from typing import List, Dict, Any, Optional, Tuple

# Diretório onde este arquivo reside — garante que banco_pericial.db
# sempre aponte para o mesmo arquivo independente do diretório de trabalho.
_DIR_PROJETO = os.path.dirname(os.path.abspath(__file__))


# ══════════════════════════════════════════════════════════════════════════════
#  UTILITÁRIO VETORIAL — sem dependência de numpy
# ══════════════════════════════════════════════════════════════════════════════

def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Similaridade de cosseno entre dois vetores (pura Python, sem numpy)."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot  = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


# ══════════════════════════════════════════════════════════════════════════════
#  M3 — SERIALIZAÇÃO BINÁRIA DE EMBEDDINGS (float32, compatível com JSON legado)
# ══════════════════════════════════════════════════════════════════════════════

def _embedding_to_blob(v: List[float]) -> bytes:
    """Serializa lista de floats para BLOB binário (float32, little-endian).
    Resultado: 768 floats × 4 bytes = 3072 bytes (vs ~14KB em JSON).
    """
    if not v:
        return b''
    return struct.pack(f'{len(v)}f', *v)


def _blob_to_embedding(b) -> List[float]:
    """Deserializa BLOB binário ou string JSON para lista de floats.
    Aceita ambos os formatos para compatibilidade durante transição.
    """
    if b is None:
        return []
    if isinstance(b, (bytes, bytearray)):
        n = len(b) // 4
        return list(struct.unpack(f'{n}f', b)) if n > 0 else []
    if isinstance(b, str):
        try:
            return json.loads(b)
        except Exception:
            return []
    return []


# ══════════════════════════════════════════════════════════════════════════════
#  TIPOS DE FONTE E PESOS DE AUTORIDADE PERICIAL
# ══════════════════════════════════════════════════════════════════════════════

TIPOS_FONTE = {
    "norma_abnt":        "Norma ABNT/NBR",
    "norma_iso":         "Norma ISO/IEC",
    "norma_outro":       "Norma Técnica (outro órgão)",
    "laudo_judicial":    "Laudo Pericial Judicial",
    "parecer_tecnico":   "Parecer Técnico",
    "livro":             "Livro Técnico",
    "artigo":            "Artigo Científico",
    "manual_fabricante": "Manual de Fabricante",
    "outro":             "Outro",
}

PESO_AUTORIDADE = {
    "norma_abnt": 1.00, "norma_iso": 0.95, "norma_outro": 0.85,
    "laudo_judicial": 0.80, "parecer_tecnico": 0.75,
    "livro": 0.60, "artigo": 0.55, "manual_fabricante": 0.50, "outro": 0.30,
}


# ══════════════════════════════════════════════════════════════════════════════
#  CARREGADOR DE CONFIGURAÇÃO YAML — Sinônimos e stopwords do config_pericial
# ══════════════════════════════════════════════════════════════════════════════

def _construir_sins_ancora_yaml(config_path: str = "config_pericial.yaml") -> dict:
    """
    Lê config_pericial.yaml e constrói um dicionário de sinônimos para âncoras.
    Combina três fontes de dados do YAML:
      1. termos_canonicos  → mapeamentos bidirecionais curados pelo usuário
      2. drenagem_hidraulica → cluster coeso de termos de escoamento/drenagem
      3. yaml_extras       → sub-grupos semânticos de patologias e anomalias

    Retorna dict vazio se o arquivo não existir (falha silenciosa).
    """
    import os
    if not os.path.exists(config_path):
        return {}
    try:
        import yaml as _yaml
        with open(config_path, encoding="utf-8") as f:
            cfg = _yaml.safe_load(f) or {}
    except Exception:
        return {}

    result: dict = {}

    def _add(k: str, v: str):
        k, v = k.lower().strip(), v.lower().strip()
        if k and v and k != v:
            result.setdefault(k, [])
            if v not in result[k]:
                result[k].append(v)

    # 1. termos_canonicos — bidirecional
    for variante, canonico in cfg.get("termos_canonicos", {}).items():
        _add(variante, canonico)
        _add(canonico, variante)

    # 2. Cluster drenagem_hidraulica — todos os termos são sinônimos entre si
    termos_drenagem = [
        t.lower()
        for t in cfg.get("vocabulario_pericial", {})
                     .get("drenagem_hidraulica", {})
                     .get("termos", [])
    ]
    for t in termos_drenagem:
        for outro in termos_drenagem:
            if outro != t:
                _add(t, outro)

    # 3. Sub-grupos semânticos de patologias e anomalias (mais específicos
    #    que a categoria inteira)
    extras = {
        "infiltração":       ["infiltrações", "manchas de umidade", "umidade ascendente",
                               "umidade descendente", "perda de estanqueidade", "mancha d'água"],
        "bolor":             ["manifestação biológica", "mofo", "fungo"],
        "mofo":              ["manifestação biológica", "bolor", "fungo"],
        "fissura":           ["fissura estrutural", "fissura de retração", "fissura por recalque",
                               "não conformidade", "manifestação patológica"],
        "recalque":          ["recalque diferencial", "vazio abaixo do piso",
                               "rebaixamento de piso", "aterro inadequado", "recalque de aterro"],
        "carbonatação":      ["frente de carbonatação", "corrosão de armadura"],
        "esquadria":         ["sistema de esquadrias"],
        "impermeabilização": ["sistema de impermeabilização"],
        "fundação":          ["fundação rasa", "fundação profunda", "infraestrutura"],
        "vício construtivo": ["vícios construtivos", "vício de uso", "anomalia endógena"],
        "anomalia":          ["anomalia endógena", "anomalia exógena", "anomalia funcional",
                               "manifestações patológicas"],
        "patologia":         ["manifestação patológica", "manifestações patológicas",
                               "sinistro", "irregularidade construtiva"],
        "prazo de garantia": ["prazo de garantia legal", "prazo de garantia contratual",
                               "garantia legal", "perda de garantia"],
    }
    for k, vs in extras.items():
        for v in vs:
            _add(k, v)
            _add(v, k)

    return result


def _carregar_stopwords_yaml(config_path: str = "config_pericial.yaml") -> set:
    """
    Lê stopwords_tecnicas do config_pericial.yaml.
    Filtra apenas os termos de ruído (inglês + verbos genéricos) —
    não remove termos técnicos como 'norma' ou 'laudo' que o perito
    pode querer pesquisar.
    Retorna set vazio se o arquivo não existir.
    """
    import os
    if not os.path.exists(config_path):
        return set()
    try:
        import yaml as _yaml
        with open(config_path, encoding="utf-8") as f:
            cfg = _yaml.safe_load(f) or {}
    except Exception:
        return set()

    # Apenas termos de ruído sem valor técnico para pesquisa
    # (inglês de livros + verbos + locuções genéricas)
    ruido_ingles = {
        "concrete", "cement", "strength", "research", "journal",
        "london", "international", "properties", "effect", "creep",
        "paste", "high", "practice", "astm", "proc", "inst",
        "amer", "part", "neville",
    }
    ruido_verbos = {
        "deve", "devem", "deverá", "deverão", "pode", "podem",
        "poderá", "conforme", "segundo", "mediante", "estabelece",
        "estabelecido", "determina", "indica",
    }
    ruido_genericos = {
        "forma", "modo", "caso", "tipo", "tipos", "parte", "partes",
        "seção", "presente", "objeto", "objetivo",
    }
    return ruido_ingles | ruido_verbos | ruido_genericos


# Carregamento lazy — executado uma única vez na primeira busca
_SINS_ANCORA_YAML_CACHE: dict = {}
_STOPWORDS_YAML_CACHE: set = set()
_YAML_CARREGADO = False


def _garantir_yaml_carregado(config_path: str = "config_pericial.yaml") -> None:
    global _SINS_ANCORA_YAML_CACHE, _STOPWORDS_YAML_CACHE, _YAML_CARREGADO
    if not _YAML_CARREGADO:
        _SINS_ANCORA_YAML_CACHE = _construir_sins_ancora_yaml(config_path)
        _STOPWORDS_YAML_CACHE   = _carregar_stopwords_yaml(config_path)
        _YAML_CARREGADO = True


# ══════════════════════════════════════════════════════════════════════════════
#  M1 — CHROMADB MANAGER (opcional — sistema funciona sem chromadb instalado)
# ══════════════════════════════════════════════════════════════════════════════

# Mapeamento tipo_fonte → coleção ChromaDB
_TIPO_PARA_COLECAO: Dict[str, str] = {
    'norma_abnt':      'normas',
    'norma_iso':       'normas',
    'laudo_judicial':  'laudos',
    'parecer_tecnico': 'laudos',
    'livro':           'referencias',
    'manual_fabricante': 'referencias',
    'norma_outro':     'referencias',
    'artigo':          'referencias',
}
_NOMES_COLECOES = ('normas', 'laudos', 'referencias')


def _colecao_para_tipo(tipo_fonte: str) -> str:
    """Retorna o nome da coleção ChromaDB para um dado tipo_fonte."""
    return _TIPO_PARA_COLECAO.get(tipo_fonte or '', 'referencias')


class ChromaManager:
    """
    Gerenciador de banco vetorial ChromaDB com 3 coleções por tipo de fonte.
    Totalmente opcional: se chromadb não estiver instalado ou falhar ao iniciar,
    `disponivel = False` e o sistema usa a busca vetorial Python legada.

    Coleções:
      normas      → norma_abnt, norma_iso
      laudos      → laudo_judicial, parecer_tecnico
      referencias → livro, manual, artigo, outro
    """

    def __init__(self, persist_dir: str):
        self.disponivel = False
        self._collections: Dict[str, Any] = {}
        self._log = logging.getLogger("chroma_manager")
        try:
            import chromadb  # type: ignore
            os.makedirs(persist_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(path=persist_dir)
            for nome in _NOMES_COLECOES:
                self._collections[nome] = self._client.get_or_create_collection(
                    name=nome,
                    metadata={"hnsw:space": "cosine"},
                )
            self.disponivel = True
            total = sum(c.count() for c in self._collections.values())
            self._log.info(
                f"[ChromaDB] Disponível — {total} embeddings indexados "
                f"({', '.join(f'{n}:{self._collections[n].count()}' for n in _NOMES_COLECOES)})."
            )
        except ImportError:
            self._log.info(
                "[ChromaDB] Não instalado. "
                "Execute: pip install chromadb  para habilitar busca vetorial acelerada."
            )
        except Exception as e:
            self._log.warning(f"[ChromaDB] Falha na inicialização: {e}")

    def upsert(self, topico_id: int, embedding: List[float],
               tipo_fonte: str = 'outro',
               metadata: Optional[Dict] = None) -> None:
        """Salva ou atualiza embedding na coleção correspondente ao tipo_fonte."""
        if not self.disponivel or not embedding:
            return
        colecao = _colecao_para_tipo(tipo_fonte)
        try:
            self._collections[colecao].upsert(
                ids=[str(topico_id)],
                embeddings=[embedding],
                metadatas=[metadata or {}],
            )
        except Exception as e:
            self._log.debug(f"[ChromaDB] upsert falhou para topico {topico_id}: {e}")

    def query(self, embedding: List[float],
              n: int = 50,
              tipo_fonte: str = None) -> tuple:
        """
        Consulta os n embeddings mais similares.
        Se tipo_fonte informado: consulta apenas a coleção correspondente.
        Se None: consulta todas as 3 coleções e funde por score.
        Retorna (ids_int, scores) onde scores são similaridades cosseno (0.0–1.0).
        """
        if not self.disponivel or not embedding:
            return [], []
        try:
            if tipo_fonte:
                cols_alvo = [_colecao_para_tipo(tipo_fonte)]
            else:
                cols_alvo = list(_NOMES_COLECOES)

            pares: List[tuple] = []
            for nome in cols_alvo:
                col = self._collections[nome]
                total = col.count()
                if total == 0:
                    continue
                results = col.query(
                    query_embeddings=[embedding],
                    n_results=min(n, total),
                    include=["distances"],
                )
                ids_str = results.get("ids",       [[]])[0]
                dists   = results.get("distances", [[]])[0]
                for sid, dist in zip(ids_str, dists):
                    pares.append((int(sid), max(0.0, 1.0 - float(dist))))

            if not pares:
                return [], []
            # Funde por score (mantém maior score por id) e retorna top-n
            melhor: Dict[int, float] = {}
            for tid, score in pares:
                if tid not in melhor or score > melhor[tid]:
                    melhor[tid] = score
            ordenados = sorted(melhor.items(), key=lambda x: x[1], reverse=True)[:n]
            ids_int = [t[0] for t in ordenados]
            scores  = [t[1] for t in ordenados]
            return ids_int, scores
        except Exception as e:
            self._log.debug(f"[ChromaDB] query falhou: {e}")
            return [], []

    def deletar(self, topico_id: int, tipo_fonte: str = None) -> None:
        """Remove embedding do ChromaDB. Se tipo_fonte informado, remove só da coleção certa."""
        if not self.disponivel:
            return
        cols_alvo = [_colecao_para_tipo(tipo_fonte)] if tipo_fonte else list(_NOMES_COLECOES)
        for nome in cols_alvo:
            try:
                self._collections[nome].delete(ids=[str(topico_id)])
            except Exception:
                pass


class DatabaseManager:
    def __init__(self, db_path: str = ''):
        if db_path:
            self.db_path = os.path.abspath(db_path)
        else:
            self.db_path = os.path.join(_DIR_PROJETO, 'banco_pericial.db')
        self.inicializar_sistema()
        # M1 — Banco vetorial ChromaDB (opcional)
        chroma_dir = os.path.join(os.path.dirname(self.db_path), 'chroma_db')
        self._chroma = ChromaManager(chroma_dir)

    # ─────────────────────────────────────────────────────────────────────────
    #  CONEXÃO
    # ─────────────────────────────────────────────────────────────────────────

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ─────────────────────────────────────────────────────────────────────────
    #  INICIALIZAÇÃO E MIGRAÇÃO
    # ─────────────────────────────────────────────────────────────────────────

    def inicializar_sistema(self):
        conn   = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS laudos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_arquivo  TEXT    NOT NULL,
                tipo_fonte    TEXT    DEFAULT 'outro',
                titulo_formal TEXT    DEFAULT '',
                ano_edicao    TEXT    DEFAULT '',
                versao        TEXT    DEFAULT '',
                orgao_emissor TEXT    DEFAULT '',
                status        TEXT    DEFAULT 'ativo',
                data_inclusao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                data_revisao  TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS topicos (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                laudo_id                INTEGER,
                numero_topico           TEXT,
                titulo_topico           TEXT,
                hierarquia              TEXT    DEFAULT '',
                texto_original          TEXT,
                texto_reescrito         TEXT,
                grau_risco              TEXT    DEFAULT '-',
                matriz_gut              TEXT    DEFAULT '-',
                criterio_ia             TEXT    DEFAULT '-',
                avaliacao_risco_usuario TEXT    DEFAULT '-',
                avaliacao_gut_usuario   TEXT    DEFAULT '-',
                palavras_chave          TEXT    DEFAULT '',
                pagina                  INTEGER DEFAULT 0,
                embedding               TEXT    DEFAULT NULL,
                data_ingestao           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                topico_pai_id           INTEGER DEFAULT NULL,
                FOREIGN KEY(laudo_id) REFERENCES laudos(id)
            )
        ''')

        # ── M7: Tabela de análise IA separada do texto original ───────────────
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS topicos_analise_ia (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                topico_id       INTEGER NOT NULL UNIQUE,
                texto_reescrito TEXT,
                modelo_ia       TEXT    DEFAULT NULL,
                versao_analise  INTEGER DEFAULT 1,
                criado_em       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                atualizado_em   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(topico_id) REFERENCES topicos(id)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_tai_topico
            ON topicos_analise_ia(topico_id)
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS parametros_normativos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                laudo_id   INTEGER,
                topico_id  INTEGER,
                parametro  TEXT    NOT NULL,
                valor      TEXT    NOT NULL,
                unidade    TEXT    DEFAULT '',
                contexto   TEXT    DEFAULT '',
                item_ref   TEXT    DEFAULT '',
                pagina     INTEGER DEFAULT 0,
                FOREIGN KEY(laudo_id)  REFERENCES laudos(id),
                FOREIGN KEY(topico_id) REFERENCES topicos(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quesitos_respondidos (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                laudo_id        INTEGER,
                origem_quesito  TEXT,
                pergunta        TEXT,
                resposta_perito TEXT,
                FOREIGN KEY(laudo_id) REFERENCES laudos(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS consultas_populares (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                termo           TEXT    UNIQUE NOT NULL,
                contagem        INTEGER DEFAULT 1,
                ultima_consulta TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trechos_utilizados (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topico_id   INTEGER NOT NULL,
                sessao_id   INTEGER,
                consulta    TEXT,
                data_uso    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(topico_id) REFERENCES topicos(id),
                FOREIGN KEY(sessao_id) REFERENCES sessoes(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessoes (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                criada_em        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ultima_atividade TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS historico_sessao (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                sessao_id INTEGER,
                papel     TEXT    NOT NULL,
                conteudo  TEXT    NOT NULL,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(sessao_id) REFERENCES sessoes(id)
            )
        ''')

        # ── Tabela parametros_extraidos (intervalos numéricos v1.0) ──────────
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS parametros_extraidos (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                topico_id       INTEGER,
                laudo_id        INTEGER,
                nome_parametro  TEXT    NOT NULL,
                valor_minimo    REAL    DEFAULT NULL,
                valor_maximo    REAL    DEFAULT NULL,
                valor_ponto     REAL    DEFAULT NULL,
                unidade         TEXT    DEFAULT '',
                contexto        TEXT    DEFAULT '',
                norma_ref       TEXT    DEFAULT '',
                item_ref        TEXT    DEFAULT '',
                pagina          INTEGER DEFAULT 0,
                FOREIGN KEY(topico_id) REFERENCES topicos(id),
                FOREIGN KEY(laudo_id)  REFERENCES laudos(id)
            )
        ''')

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pe_nome "
            "ON parametros_extraidos(nome_parametro)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pe_minmax "
            "ON parametros_extraidos(valor_minimo, valor_maximo)"
        )

        # ── M4: Tabela unificada de parâmetros (consolida normativos+extraídos) ──
        cursor.execute('''
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
            )
        ''')
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_param_nome "
            "ON parametros(nome_parametro)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_param_laudo "
            "ON parametros(laudo_id)"
        )

        # Migração não-destrutiva para bancos antigos
        self._migrar_colunas(cursor, 'topicos', {
            'grau_risco': "TEXT DEFAULT '-'", 'matriz_gut': "TEXT DEFAULT '-'",
            'criterio_ia': "TEXT DEFAULT '-'", 'avaliacao_risco_usuario': "TEXT DEFAULT '-'",
            'avaliacao_gut_usuario': "TEXT DEFAULT '-'", 'palavras_chave': "TEXT DEFAULT ''",
            'hierarquia': "TEXT DEFAULT ''", 'pagina': "INTEGER DEFAULT 0",
            'embedding': "TEXT DEFAULT NULL", 'data_ingestao': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            # Colunas v1.1 — busca estruturada e confiança IA
            'tipo_anomalia':      "TEXT DEFAULT '-'",
            'origem_patologica':  "TEXT DEFAULT '-'",
            'ia_score_confianca': "REAL DEFAULT NULL",
            'ia_modelo':          "TEXT DEFAULT NULL",
            'ia_timestamp':       "TIMESTAMP DEFAULT NULL",
            # M6 — contagem de tokens para monitoramento de tamanho de chunk
            'token_count':        "INTEGER DEFAULT NULL",
            # Hierarquia pai-filho
            'topico_pai_id':      "INTEGER DEFAULT NULL",
        })
        # M5 — rastreabilidade chunk→quesito
        self._migrar_colunas(cursor, 'quesitos_respondidos', {
            'topico_id': "INTEGER DEFAULT NULL",
        })
        self._migrar_colunas(cursor, 'laudos', {
            'tipo_fonte': "TEXT DEFAULT 'outro'", 'titulo_formal': "TEXT DEFAULT ''",
            'ano_edicao': "TEXT DEFAULT ''", 'versao': "TEXT DEFAULT ''",
            'orgao_emissor': "TEXT DEFAULT ''", 'status': "TEXT DEFAULT 'ativo'",
            'data_revisao': "TIMESTAMP",
        })

        # Índices para busca estruturada (criados após migração para garantir coluna)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tipo_anomalia "
            "ON topicos(tipo_anomalia)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_origem_patologica "
            "ON topicos(origem_patologica)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ia_score "
            "ON topicos(ia_score_confianca)"
        )

        # ── Tabela gut_historico (GUT Adaptativo v4.0) ────────────────────────
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gut_historico (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                descricao              TEXT    NOT NULL,
                subsistema             TEXT    NOT NULL,
                embedding              BLOB    DEFAULT NULL,
                nexo_origem            TEXT    DEFAULT NULL,
                nexo_mecanismo         TEXT    DEFAULT NULL,
                nexo_status            TEXT    DEFAULT NULL,
                nexo_causal_texto      TEXT    DEFAULT NULL,
                nexo_indeterminado     INTEGER DEFAULT 0,
                G_final                INTEGER NOT NULL,
                U_final                INTEGER NOT NULL,
                T_final                INTEGER NOT NULL,
                prioridade_gut         INTEGER NOT NULL,
                risco_gut              TEXT    NOT NULL,
                npa_shs                REAL    DEFAULT NULL,
                prioridade_shs         TEXT    DEFAULT NULL,
                shs_calculado          INTEGER DEFAULT 0,
                shs_converge_gut       INTEGER DEFAULT NULL,
                sobreposicao_detectada INTEGER DEFAULT 0,
                fonte_avaliacao        TEXT    NOT NULL,
                aceito_perito          INTEGER DEFAULT 1,
                G_original             INTEGER DEFAULT NULL,
                U_original             INTEGER DEFAULT NULL,
                T_original             INTEGER DEFAULT NULL,
                respostas_json         TEXT    DEFAULT NULL,
                projeto_id             INTEGER DEFAULT NULL,
                timestamp              TEXT    NOT NULL
            )
        ''')

        # Migração não-destrutiva para gut_historico
        self._migrar_colunas(cursor, 'gut_historico', {
            'nexo_origem':             "TEXT DEFAULT NULL",
            'nexo_mecanismo':          "TEXT DEFAULT NULL",
            'nexo_status':             "TEXT DEFAULT NULL",
            'nexo_causal_texto':       "TEXT DEFAULT NULL",
            'nexo_indeterminado':      "INTEGER DEFAULT 0",
            'npa_shs':                 "REAL DEFAULT NULL",
            'prioridade_shs':          "TEXT DEFAULT NULL",
            'shs_calculado':           "INTEGER DEFAULT 0",
            'shs_converge_gut':        "INTEGER DEFAULT NULL",
            'sobreposicao_detectada':  "INTEGER DEFAULT 0",
            'G_original':              "INTEGER DEFAULT NULL",
            'U_original':              "INTEGER DEFAULT NULL",
            'T_original':              "INTEGER DEFAULT NULL",
            'respostas_json':          "TEXT DEFAULT NULL",
            'projeto_id':              "INTEGER DEFAULT NULL",
        })

        conn.commit()
        conn.close()
        self._auto_sync_fts()

    def _auto_sync_fts(self):
        """
        Verifica silenciosamente se o índice FTS5 está em sincronia com topicos.
        Reconstrói automaticamente se estiver vazio ou com menos registros.
        Chamado uma vez na inicialização — fallback para LIKE se FTS5 não existir.
        """
        try:
            conn = self.get_connection()
            fts_existe = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='topicos_fts'"
            ).fetchone()
            if not fts_existe:
                conn.close()
                return
            fts_count = conn.execute("SELECT COUNT(*) FROM topicos_fts").fetchone()[0]
            top_count = conn.execute("SELECT COUNT(*) FROM topicos").fetchone()[0]
            if fts_count < top_count:
                conn.execute("DELETE FROM topicos_fts")
                conn.execute(
                    "INSERT INTO topicos_fts(rowid, titulo_topico, hierarquia, "
                    "palavras_chave, texto_original) "
                    "SELECT id, titulo_topico, hierarquia, palavras_chave, texto_original "
                    "FROM topicos"
                )
                conn.commit()
            conn.close()
        except Exception:
            pass  # falha silenciosa — busca degrada para LIKE automaticamente

    def _migrar_colunas(self, cursor, tabela: str, novas: dict):
        cursor.execute(f"PRAGMA table_info({tabela})")
        existentes = {col[1] for col in cursor.fetchall()}
        for col, defn in novas.items():
            if col not in existentes:
                cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {col} {defn}")

    # ─────────────────────────────────────────────────────────────────────────
    #  FONTES
    # ─────────────────────────────────────────────────────────────────────────

    def registrar_laudo(self, nome_arquivo: str, tipo_fonte: str = 'outro',
                        titulo_formal: str = '', ano_edicao: str = '',
                        versao: str = '', orgao_emissor: str = '') -> int:
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO laudos (nome_arquivo, tipo_fonte, titulo_formal,
               ano_edicao, versao, orgao_emissor) VALUES (?, ?, ?, ?, ?, ?)''',
            (nome_arquivo, tipo_fonte, titulo_formal, ano_edicao, versao, orgao_emissor)
        )
        lid = cursor.lastrowid
        conn.commit(); conn.close()
        return lid

    def buscar_laudo_por_nome(self, nome_arquivo: str) -> Optional[int]:
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM laudos WHERE nome_arquivo = ?", (nome_arquivo,))
        r = cursor.fetchone()
        conn.close()
        return r[0] if r else None

    def listar_fontes(self, tipo: str = None, status: str = 'ativo') -> List[Dict]:
        conn   = self.get_connection()
        cursor = conn.cursor()
        sql = '''SELECT l.id, l.nome_arquivo, l.tipo_fonte, l.titulo_formal,
                        l.ano_edicao, l.status, l.data_inclusao,
                        COUNT(t.id) as n_trechos
                 FROM laudos l LEFT JOIN topicos t ON t.laudo_id = l.id'''
        params = []; conds = []
        if tipo:   conds.append("l.tipo_fonte = ?"); params.append(tipo)
        if status: conds.append("l.status = ?");     params.append(status)
        if conds:  sql += " WHERE " + " AND ".join(conds)
        sql += " GROUP BY l.id ORDER BY l.tipo_fonte, l.data_inclusao DESC"
        cursor.execute(sql, params)
        cols = [d[0] for d in cursor.description]
        r = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close(); return r

    def atualizar_fonte(self, laudo_id: int, **kwargs):
        validos = {'tipo_fonte','titulo_formal','ano_edicao','versao','orgao_emissor','status'}
        updates = {k: v for k, v in kwargs.items() if k in validos}
        if not updates: return
        conn   = self.get_connection()
        cursor = conn.cursor()
        sets   = ", ".join(f"{k} = ?" for k in updates)
        cursor.execute(
            f"UPDATE laudos SET {sets}, data_revisao = CURRENT_TIMESTAMP WHERE id = ?",
            list(updates.values()) + [laudo_id]
        )
        conn.commit(); conn.close()

    def deletar_fonte(self, laudo_id: int):
        conn   = self.get_connection()
        cursor = conn.cursor()
        # M4: inclui tabela unificada de parâmetros
        for tabela in ['parametros_normativos', 'parametros_extraidos',
                       'parametros', 'quesitos_respondidos']:
            cursor.execute(f"DELETE FROM {tabela} WHERE laudo_id = ?", (laudo_id,))
        # M7: remove análises IA dos tópicos deste laudo
        cursor.execute(
            "DELETE FROM topicos_analise_ia WHERE topico_id IN "
            "(SELECT id FROM topicos WHERE laudo_id = ?)", (laudo_id,)
        )
        cursor.execute("DELETE FROM topicos WHERE laudo_id = ?", (laudo_id,))
        cursor.execute("DELETE FROM laudos WHERE id = ?", (laudo_id,))
        # M1: remove do ChromaDB
        ids_rows = conn.execute(
            "SELECT id FROM topicos WHERE laudo_id = ?", (laudo_id,)
        ).fetchall()
        conn.commit(); conn.close()
        for (tid,) in ids_rows:
            self._chroma.deletar(tid)

    # ─────────────────────────────────────────────────────────────────────────
    #  TÓPICOS
    # ─────────────────────────────────────────────────────────────────────────

    def salvar_topico(self, laudo_id, num, titulo, orig, reescrito,
                      risco='-', gut='-', criterio='-',
                      aval_risco='-', aval_gut='-',
                      palavras_chave='', hierarquia='', pagina=0,
                      token_count: int = None,
                      topico_pai_id: int = None) -> int:
        # M6: calcula token_count automaticamente se não fornecido
        if token_count is None and orig:
            token_count = max(1, len(orig) // 4)
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO topicos
               (laudo_id, numero_topico, titulo_topico, hierarquia,
                texto_original, texto_reescrito, grau_risco, matriz_gut,
                criterio_ia, avaliacao_risco_usuario, avaliacao_gut_usuario,
                palavras_chave, pagina, token_count, topico_pai_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (laudo_id, num, titulo, hierarquia, orig, reescrito,
             risco, gut, criterio, aval_risco, aval_gut,
             palavras_chave, pagina, token_count, topico_pai_id)
        )
        tid = cursor.lastrowid
        conn.commit(); conn.close()
        return tid

    def resolver_pai(self, laudo_id: int, numero_topico: str) -> Optional[int]:
        """
        Resolve o id do tópico pai dentro do mesmo laudo_id.
        Ex.: "4.1" → busca "4"; "4.1.2" → busca "4.1".
        Retorna None se não houver ponto ou se o pai não existir.
        Garante isolamento por documento: nunca cruza laudo_id.
        """
        if not numero_topico or '.' not in str(numero_topico):
            return None
        pai_num = str(numero_topico).rsplit('.', 1)[0]
        conn = self.get_connection()
        row = conn.execute(
            "SELECT id FROM topicos WHERE laudo_id = ? AND numero_topico = ? LIMIT 1",
            (laudo_id, pai_num)
        ).fetchone()
        conn.close()
        return row[0] if row else None

    def enriquecer_com_pai(self, resultados: List[Dict]) -> List[Dict]:
        """
        Para cada resultado que possui topico_pai_id, busca o tópico pai
        em lote e adiciona a chave 'pai' ao dict do resultado.
        Usa uma única query IN para não impactar performance.
        """
        ids_pai = list({
            r['topico_pai_id'] for r in resultados
            if r.get('topico_pai_id')
        })
        if not ids_pai:
            return resultados
        placeholders = ','.join('?' * len(ids_pai))
        conn = self.get_connection()
        rows = conn.execute(
            f"SELECT id, numero_topico, titulo_topico, texto_original "
            f"FROM topicos WHERE id IN ({placeholders})",
            ids_pai
        ).fetchall()
        conn.close()
        pais = {r[0]: {'id': r[0], 'numero': r[1], 'titulo': r[2], 'texto': r[3] or ''}
                for r in rows}
        for res in resultados:
            pid = res.get('topico_pai_id')
            if pid and pid in pais:
                res['pai'] = pais[pid]
        return resultados

    def salvar_embedding(self, topico_id: int, embedding: List[float],
                         tipo_fonte: str = None):
        # M3: armazena como BLOB binário (mais compacto que JSON)
        blob = _embedding_to_blob(embedding)
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE topicos SET embedding = ? WHERE id = ?",
            (blob, topico_id)
        )
        conn.commit()
        # Resolve tipo_fonte a partir do banco se não fornecido
        if not tipo_fonte:
            row = conn.execute(
                "SELECT l.tipo_fonte FROM topicos t "
                "JOIN laudos l ON l.id = t.laudo_id WHERE t.id = ?",
                (topico_id,)
            ).fetchone()
            tipo_fonte = row[0] if row else 'outro'
        conn.close()
        # M1: replica no ChromaDB na coleção correta
        self._chroma.upsert(topico_id, embedding, tipo_fonte=tipo_fonte)

    # ─────────────────────────────────────────────────────────────────────────
    #  BUSCA HÍBRIDA
    # ─────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────
    #  FTS5 — busca full-text nativa
    # ─────────────────────────────────────────────────────────────────────────

    def _fts_disponivel(self) -> bool:
        """Retorna True se a tabela virtual topicos_fts existe no banco."""
        try:
            conn = self.get_connection()
            r = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='topicos_fts'"
            ).fetchone()
            conn.close()
            return r is not None
        except Exception:
            return False

    def reconstruir_fts(self) -> int:
        """
        Reconstrói o índice FTS5 do zero.
        Use quando novos tópicos foram inseridos sem passar pelos triggers
        (ex.: carga em massa direta no SQLite).
        Retorna número de documentos indexados.
        """
        conn = self.get_connection()
        try:
            conn.execute("DELETE FROM topicos_fts")
            conn.execute(
                "INSERT INTO topicos_fts(rowid, titulo_topico, hierarquia, "
                "palavras_chave, texto_original) "
                "SELECT id, titulo_topico, hierarquia, palavras_chave, texto_original "
                "FROM topicos"
            )
            conn.commit()
            return conn.execute("SELECT COUNT(*) FROM topicos_fts").fetchone()[0]
        finally:
            conn.close()

    @staticmethod
    def _build_fts_match(termos: List[str]) -> Optional[str]:
        """
        Constrói expressão MATCH para FTS5 a partir da lista de termos.
        Usa prefixo '*' para capturar plurais e flexões:
            "fissura*" casa fissura, fissuras, fissuração, fissurado.
        Termos multi-palavra são buscados como frase exata.
        Retorna None se não houver termos válidos.
        """
        import re as _re
        parts = []
        _fts_especiais = _re.compile(r'["\(\)\:\^\[\]\\]')
        for t in termos:
            t_clean = _fts_especiais.sub('', t.strip().lower())
            if not t_clean or len(t_clean) < 2:
                continue
            if ' ' in t_clean:
                # Frase: busca exata sem prefixo
                parts.append(f'"{t_clean}"')
            else:
                # Token único: prefixo para capturar flexões
                parts.append(f'"{t_clean}"*')
        return ' OR '.join(parts) if parts else None

    def busca_textual(self, termos: List[str], tipo_fonte: str = None,
                      status: str = 'ativo',
                      termos_anchor: List[str] = None) -> List[Dict]:
        """
        Busca textual com suporte a termos âncora (termos_anchor).

        termos_anchor: subconjunto dos termos originais digitados pelo usuário
            (antes da expansão de sinônimos). Quando fornecido:
            - O SQL exige que ao menos um âncora esteja presente em qualquer campo
              (AND lógico, não OR) — descarta resultados irrelevantes que só
              contêm termos expandidos genéricos como "piso" ou "revestimento".
            - O score de âncora é multiplicado por 20× para flutuar ao topo.

        Sem termos_anchor o comportamento é idêntico ao original.
        """
        anchor_set = [a.lower() for a in (termos_anchor or []) if a and len(a) > 2]

        conn   = self.get_connection()
        cursor = conn.cursor()
        rows   = None
        cols   = None

        # ── Tentativa FTS5 (mais rápida, suporta acentos e prefixos) ────────
        if termos and self._fts_disponivel():
            match_expr = self._build_fts_match(termos)
            if match_expr:
                try:
                    sql_fts = (
                        "SELECT t.id, t.numero_topico, t.titulo_topico, t.hierarquia, "
                        "t.texto_original, t.texto_reescrito, t.palavras_chave, "
                        "t.pagina, t.embedding, t.data_ingestao, "
                        "t.favorito, t.comentario_usuario, t.topico_pai_id, "
                        "l.id as laudo_id, l.nome_arquivo, l.tipo_fonte, "
                        "l.ano_edicao, l.titulo_formal, l.orgao_emissor "
                        "FROM topicos_fts "
                        "JOIN topicos t ON topicos_fts.rowid = t.id "
                        "JOIN laudos l ON t.laudo_id = l.id "
                        "WHERE topicos_fts MATCH ? "
                        "AND (t.texto_reescrito NOT LIKE '%CONTEÚDO_IRRELEVANTE%' "
                        "     OR t.texto_reescrito IS NULL) "
                    )
                    params_fts: List = [match_expr]
                    if status:
                        sql_fts += "AND l.status = ? "
                        params_fts.append(status)
                    if tipo_fonte:
                        sql_fts += "AND l.tipo_fonte = ? "
                        params_fts.append(tipo_fonte)
                    sql_fts += "ORDER BY rank LIMIT 80"
                    cursor.execute(sql_fts, params_fts)
                    cols = [d[0] for d in cursor.description]
                    rows = cursor.fetchall()
                except Exception:
                    rows = None   # falha silenciosa → cai no LIKE abaixo

        # ── Fallback LIKE (quando FTS5 indisponível ou falhou) ───────────────
        if rows is None:
            sql = (
                "SELECT t.id, t.numero_topico, t.titulo_topico, t.hierarquia, "
                "t.texto_original, t.texto_reescrito, t.palavras_chave, "
                "t.pagina, t.embedding, t.data_ingestao, "
                "t.favorito, t.comentario_usuario, t.topico_pai_id, "
                "l.id as laudo_id, l.nome_arquivo, l.tipo_fonte, "
                "l.ano_edicao, l.titulo_formal, l.orgao_emissor "
                "FROM topicos t JOIN laudos l ON t.laudo_id = l.id "
                "WHERE t.texto_reescrito NOT LIKE '%CONTEÚDO_IRRELEVANTE%' "
            )
            params: List = []
            if status:     sql += "AND l.status = ? ";     params.append(status)
            if tipo_fonte: sql += "AND l.tipo_fonte = ? "; params.append(tipo_fonte)

            if termos:
                conds = []
                for _ in termos:
                    conds.append(
                        "(t.texto_reescrito LIKE ? OR t.palavras_chave LIKE ? "
                        "OR t.texto_original LIKE ? OR t.titulo_topico LIKE ? "
                        "OR t.hierarquia LIKE ?)"
                    )
                sql += "AND (" + " OR ".join(conds) + ") "
                for t in termos:
                    v = f"%{t}%"
                    params.extend([v, v, v, v, v])

            if anchor_set:
                anchor_conds = []
                for _ in anchor_set:
                    anchor_conds.append(
                        "(t.texto_reescrito LIKE ? OR t.palavras_chave LIKE ? "
                        "OR t.texto_original LIKE ? OR t.titulo_topico LIKE ? "
                        "OR t.hierarquia LIKE ?)"
                    )
                sql += "AND (" + " OR ".join(anchor_conds) + ") "
                for a in anchor_set:
                    v = f"%{a}%"
                    params.extend([v, v, v, v, v])

            sql += "LIMIT 60"
            cursor.execute(sql, params)
            cols = [d[0] for d in cursor.description]
            rows = cursor.fetchall()

        conn.close()
        # ── Tabela de sinônimos para avaliação de âncoras ──────────────────
        # Base hardcoded — cobertura garantida sem dependência de arquivo externo.
        # Enriquecida em runtime pelo config_pericial.yaml via _garantir_yaml_carregado().
        _SINS_ANCORA_BASE = {
            "infiltração":       ["infiltracao","umidade","vazamento","permeabilidade","estanque"],
            "estanqueidade":     ["impermeabilização","impermeabilidade","vedação","estanque","infiltração"],
            "impermeabilização": ["manta","membrana","emulsão","estanqueidade","impermeabilizante"],
            "umidade":           ["infiltração","estanqueidade","umidade ascendente","manchas","bolor"],
            "mofo":              ["bolor","fungo","colonização","manchas escuras","microorganismo"],
            "bolor":             ["mofo","fungo","colonização","manchas escuras"],
            "esquadria":         ["caixilho","janela","folha","esquadrias","caixilharia"],
            "janela":            ["esquadria","caixilho","folha","vão"],
            "selante":           ["calafete","calafetagem","vedação","junta","silicone"],
            "vedação":           ["selante","calafetagem","junta","estanqueidade"],
            "fissura":           ["fissuração","trinca","rachadura","fenda","abertura","fissurado"],
            "trinca":            ["fissura","rachadura","fissuração","fenda"],
            "fissuração":        ["fissura","trinca","rachadura","abertura"],
            "corrosão":          ["ferrugem","oxidação","armadura exposta","carbonatação","corroído"],
            "carbonatação":      ["corrosão","ph concreto","cobrimento","armadura exposta"],
            "armadura":          ["corrosão","cobrimento","ferrugem","aço"],
            "recalque":          ["afundamento","subsidência","assentamento","desnivelamento","cedência"],
            "fundação":          ["recalque","sapata","estaca","radier","bloco","tubulão"],
            "desplacamento":     ["descolamento","soltura","estufamento","queda de revestimento"],
            "descolamento":      ["desplacamento","soltura","estufamento"],
            "revestimento":      ["azulejo","porcelanato","cerâmica","piso","argamassa colante"],
            "aderência":         ["pull-off","arrancamento","descolamento","argamassa colante"],
            "inclinação":        ["caimento","declividade","declive","inclinado","desnível"],
            "escoamento":        ["drenagem","ralo","calha","dreno","coletor"],
            "caimento":          ["inclinação","declividade","caimento mínimo","escoamento","ralo"],
            "drenagem":          ["ralo","calha","escoamento","coletor","dreno"],
            "piso":              ["contrapiso","regularização","revestimento de piso","piso cerâmico"],
            "contrapiso":        ["regularização","nivelamento","piso morto"],
            "estrutura":         ["viga","pilar","laje","concreto armado","estrutural"],
            "laje":              ["estrutura","laje portante","forro","teto"],
            "guarda-corpo":      ["parapeito","corrimão","proteção lateral","gradil"],
            "parapeito":         ["guarda-corpo","proteção lateral","barreira"],
            "patologia":         ["anomalia","defeito","falha","dano","manifestação patológica"],
            "anomalia":          ["patologia","defeito","falha","vício construtivo"],
            "garantia":          ["prazo de garantia","assistência técnica","proprietário","nbr 17170"],
            "eflorescência":     ["salitre","depósito calcário","mancha branca","cristalização"],
            "argamassa":         ["reboco","emboço","chapisco","massa","traço"],
        }

        # Enriquecer com sinônimos do config_pericial.yaml (lazy load)
        _garantir_yaml_carregado()
        # Merge: YAML adiciona ao base, não substitui
        _SINS_ANCORA = dict(_SINS_ANCORA_BASE)
        for _k, _vs in _SINS_ANCORA_YAML_CACHE.items():
            if _k not in _SINS_ANCORA:
                _SINS_ANCORA[_k] = list(_vs)
            else:
                _existentes = set(_SINS_ANCORA[_k])
                _SINS_ANCORA[_k] += [v for v in _vs if v not in _existentes]

        resultados = []
        for row in rows:
            d = dict(zip(cols, row))
            score = 0.0
            titulo     = (d.get("titulo_topico")    or "").lower()
            palavras   = (d.get("palavras_chave")   or "").lower()
            reescrito  = (d.get("texto_reescrito")  or "").lower()
            original   = (d.get("texto_original")   or "").lower()
            hierarquia = (d.get("hierarquia")        or "").lower()
            texto_all  = f"{titulo} {palavras} {hierarquia} {reescrito} {original}"

            for t in termos:
                tl = t.lower()
                score += titulo.count(tl)     * 8
                score += palavras.count(tl)   * 6
                score += hierarquia.count(tl) * 4
                score += reescrito.count(tl)  * 2
                score += original.count(tl)   * 1

            # Bônus âncora: termos originais do usuário valem 20× mais
            # BUG 3 FIX: bônus só conta quando âncora está no texto_original ou título,
            # NÃO apenas em palavras_chave geradas automaticamente (evita falsos positivos
            # de livros que receberam palavras-chave como "manifestação biológica" pelo
            # processamento offline, sem o conteúdo real ser sobre aquele tema).
            texto_substancial = f"{titulo} {hierarquia} {original}"  # sem palavras_chave e reescrito
            for a in anchor_set:
                score += titulo.count(a)                  * 160
                score += hierarquia.count(a)              * 80
                score += original.count(a)                * 40
                # palavras_chave e reescrito com peso reduzido (pode ser gerado automaticamente)
                score += palavras.count(a)                * 20
                score += reescrito.count(a)               * 10

            score += PESO_AUTORIDADE.get(d.get("tipo_fonte", "outro"), 0.3) * 5
            # Favoritos do perito sempre flutuam ao topo dos resultados
            if d.get("favorito"):
                score += 200
            d["score_textual"] = score
            d["score_vetorial"] = 0.0

            # ── Filtro e ranking por cobertura de âncoras ──────────────────
            # Threshold FIXO = 2: exige que o documento contenha ao menos
            # 2 âncoras distintos (ou seus sinônimos).
            # BUG 3 FIX: a contagem de âncoras usa texto_substancial (título + hierarquia +
            # texto_original) para evitar que palavras-chave geradas automaticamente
            # façam um documento passar pelo filtro sem o conteúdo real ser relevante.
            n_ancoras_satisfeitos = 0
            if anchor_set:
                for a in anchor_set:
                    grupo = [a] + _SINS_ANCORA.get(a, [])
                    # Verificar no texto substancial primeiro (peso alto, conteúdo real)
                    if any(g in texto_substancial for g in grupo):
                        n_ancoras_satisfeitos += 1
                    # Palavras-chave só contam se o texto substancial já tiver ≥1 âncora
                    # (evita falso positivo onde só as palavras_chave têm o termo)
                    elif n_ancoras_satisfeitos >= 1 and any(g in palavras for g in grupo):
                        n_ancoras_satisfeitos += 1
                if n_ancoras_satisfeitos < 2:
                    continue   # descarta: contém apenas 0 ou 1 âncora

            d["_n_ancoras"] = n_ancoras_satisfeitos
            resultados.append(d)

        # Ordenar: primário = nº âncoras satisfeitos (desc), secundário = score (desc).
        # Documentos que cobrem mais termos da query ficam sempre no topo,
        # independente do score bruto.
        return sorted(resultados,
                      key=lambda x: (-x.get("_n_ancoras", 0), -x["score_textual"]))

    def busca_hibrida(self, termos: List[str], embedding_query: List[float] = None,
                      tipo_fonte: str = None, n: int = 10,
                      termos_anchor: List[str] = None) -> List[Dict]:
        candidatos = self.busca_textual(termos, tipo_fonte, termos_anchor=termos_anchor)
        if not embedding_query or all(v == 0 for v in (embedding_query or [])):
            return candidatos[:n]

        # M1: consulta ChromaDB para scores vetoriais (evita loop Python O(n))
        # Fallback automático para cosseno Python se ChromaDB indisponível
        chroma_scores: Dict[int, float] = {}
        if self._chroma.disponivel:
            ids_chroma, scores_chroma = self._chroma.query(
                embedding_query, n=max(len(candidatos), 30)
            )
            chroma_scores = dict(zip(ids_chroma, scores_chroma))

        for d in candidatos:
            tid = d.get('id')
            if tid in chroma_scores:
                # M1: score vem do ChromaDB (HNSW acelerado)
                d['score_vetorial'] = chroma_scores[tid]
            else:
                # M3: fallback — desserializa BLOB ou JSON legado
                try:
                    emb = _blob_to_embedding(d.get('embedding'))
                    d['score_vetorial'] = _cosine_similarity(embedding_query, emb)
                except Exception:
                    d['score_vetorial'] = 0.0

        max_t = max((d['score_textual'] for d in candidatos), default=1) or 1
        max_v = max((d['score_vetorial'] for d in candidatos), default=1) or 1
        for d in candidatos:
            d['score_hibrido'] = (0.40 * d['score_textual'] / max_t +
                                  0.60 * d['score_vetorial'] / max_v)
        ranking = sorted(candidatos, key=lambda x: x['score_hibrido'], reverse=True)[:n]
        return self.enriquecer_com_pai(ranking)


    def salvar_quesito(self, laudo_id: int, secao: str,
                       pergunta: str, resposta: str,
                       topico_id: int = None) -> int:
        """Salva um par pergunta/resposta na tabela de quesitos.
        M5: topico_id opcional para rastreabilidade chunk→quesito.
        """
        conn = self.get_connection(); cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO quesitos_respondidos
               (laudo_id, origem_quesito, pergunta, resposta_perito, topico_id)
               VALUES (?, ?, ?, ?, ?)''',
            (laudo_id, secao, pergunta[:1000], resposta[:4000], topico_id)
        )
        qid = cursor.lastrowid; conn.commit(); conn.close(); return qid

    def salvar_analise_ia(self, topico_id: int, texto_reescrito: str,
                          modelo_ia: str = None) -> int:
        """M7: Salva análise IA separada do texto original (INSERT OR REPLACE).
        Preserva imutabilidade do texto_original em topicos.
        """
        conn = self.get_connection(); cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO topicos_analise_ia
               (topico_id, texto_reescrito, modelo_ia, atualizado_em)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(topico_id) DO UPDATE SET
                   texto_reescrito = excluded.texto_reescrito,
                   modelo_ia       = excluded.modelo_ia,
                   versao_analise  = versao_analise + 1,
                   atualizado_em   = CURRENT_TIMESTAMP''',
            (topico_id, texto_reescrito, modelo_ia)
        )
        aid = cursor.lastrowid; conn.commit(); conn.close(); return aid

    def deletar_topico(self, topico_id: int):
        """Remove um tópico individual e seus parâmetros do banco."""
        conn = self.get_connection(); cursor = conn.cursor()
        # M4+M7: remove de todas as tabelas filhas
        for tabela in ['parametros_normativos', 'parametros_extraidos',
                       'parametros', 'topicos_analise_ia']:
            cursor.execute(f"DELETE FROM {tabela} WHERE topico_id = ?", (topico_id,))
        cursor.execute("DELETE FROM topicos WHERE id = ?", (topico_id,))
        conn.commit(); conn.close()
        # M1: remove do ChromaDB
        self._chroma.deletar(topico_id)

    def avaliar_topico(self, topico_id: int,
                       favorito: Optional[bool] = None,
                       comentario: Optional[str] = None) -> Dict:
        """Atualiza avaliação manual do perito (favorito e/ou comentário).

        Retorna dict com os valores atuais após a atualização:
            {'favorito': 0|1, 'comentario_usuario': str}
        """
        updates: Dict[str, Any] = {}
        if favorito is not None:
            updates["favorito"] = 1 if favorito else 0
        if comentario is not None:
            updates["comentario_usuario"] = comentario.strip()

        conn = self.get_connection()
        try:
            if updates:
                set_cl = ", ".join(f"{k}=?" for k in updates)
                conn.execute(
                    f"UPDATE topicos SET {set_cl} WHERE id=?",
                    list(updates.values()) + [topico_id]
                )
                conn.commit()
            row = conn.execute(
                "SELECT favorito, comentario_usuario FROM topicos WHERE id=?",
                (topico_id,)
            ).fetchone()
            return {"favorito": row[0] if row else 0,
                    "comentario_usuario": row[1] if row else ""}
        finally:
            conn.close()

    def listar_anomalias_risco(self, laudo_id: int = None) -> List[Dict]:
        """Tópicos de laudos com grau de risco preenchido — usado pela Matriz GUT."""
        conn = self.get_connection(); cursor = conn.cursor()
        sql = (
            '''SELECT t.id, t.titulo_topico, t.grau_risco, t.matriz_gut,
                        t.criterio_ia, t.avaliacao_risco_usuario, t.avaliacao_gut_usuario,
                        l.nome_arquivo, l.tipo_fonte
                 FROM topicos t JOIN laudos l ON t.laudo_id = l.id
                 WHERE l.status = 'ativo'
                   AND t.grau_risco != '-'
                   AND l.tipo_fonte IN ('laudo_judicial','parecer_tecnico')''')
        params = []
        if laudo_id:
            sql += " AND t.laudo_id = ?"; params.append(laudo_id)
        sql += (" ORDER BY CASE t.grau_risco"
                " WHEN 'Crítico' THEN 1 WHEN 'Grave' THEN 2"
                " WHEN 'Médio'   THEN 3 WHEN 'Mínimo' THEN 4 ELSE 5 END")
        cursor.execute(sql, params)
        cols = [d[0] for d in cursor.description]
        r = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close(); return r

    def atualizar_risco_gut(self, topico_id: int, risco_perito: str, gut_perito: str):
        """Salva a avaliação manual do perito (sobrescreve avaliação automática)."""
        conn = self.get_connection(); cursor = conn.cursor()
        cursor.execute(
            '''UPDATE topicos SET avaliacao_risco_usuario = ?,
               avaliacao_gut_usuario = ? WHERE id = ?''',
            (risco_perito, gut_perito, topico_id)
        )
        conn.commit(); conn.close()

    def busca_quesitos(self, termos: List[str]) -> List[Dict]:
        conn   = self.get_connection()
        cursor = conn.cursor()
        sql = '''SELECT q.pergunta, q.resposta_perito, q.origem_quesito,
                        l.nome_arquivo, l.tipo_fonte, l.ano_edicao
                 FROM quesitos_respondidos q JOIN laudos l ON q.laudo_id = l.id
                 WHERE l.status = 'ativo' '''
        params = []
        if termos:
            conds = ["(q.pergunta LIKE ? OR q.resposta_perito LIKE ?)" for _ in termos]
            sql += " AND (" + " OR ".join(conds) + ")"
            for t in termos:
                v = f"%{t}%"; params.extend([v, v])
        cursor.execute(sql, params)
        cols = [d[0] for d in cursor.description]
        r = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close(); return r

    # ─────────────────────────────────────────────────────────────────────────
    #  PARÂMETROS NORMATIVOS
    # ─────────────────────────────────────────────────────────────────────────

    def salvar_parametro(self, laudo_id: int, topico_id: int,
                         parametro: str, valor: str, unidade: str = '',
                         contexto: str = '', item_ref: str = '', pagina: int = 0):
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO parametros_normativos
               (laudo_id, topico_id, parametro, valor, unidade, contexto, item_ref, pagina)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (laudo_id, topico_id, parametro, valor, unidade, contexto, item_ref, pagina)
        )
        # M4: dual-write na tabela unificada
        cursor.execute(
            '''INSERT INTO parametros
               (laudo_id, topico_id, nome_parametro, valor_texto,
                unidade, contexto, item_ref, pagina, origem)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'normativo')''',
            (laudo_id, topico_id, parametro, valor, unidade, contexto, item_ref, pagina)
        )
        conn.commit(); conn.close()

    def buscar_parametros(self, termo: str) -> List[Dict]:
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT p.parametro, p.valor, p.unidade, p.contexto,
                   p.item_ref, p.pagina,
                   l.nome_arquivo, l.tipo_fonte, l.ano_edicao, l.titulo_formal
            FROM parametros_normativos p JOIN laudos l ON p.laudo_id = l.id
            WHERE (p.parametro LIKE ? OR p.contexto LIKE ?) AND l.status = 'ativo'
            ORDER BY l.tipo_fonte, l.nome_arquivo
        ''', (f"%{termo}%", f"%{termo}%"))
        cols = [d[0] for d in cursor.description]
        r = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close(); return r

    def listar_parametros_norma(self, laudo_id: int) -> List[Dict]:
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT parametro, valor, unidade, contexto, item_ref, pagina
               FROM parametros_normativos WHERE laudo_id = ?
               ORDER BY item_ref, parametro''', (laudo_id,)
        )
        cols = [d[0] for d in cursor.description]
        r = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close(); return r

    def salvar_parametro_intervalo(self, topico_id: int, laudo_id: int,
                                    nome: str,
                                    val_min: float = None, val_max: float = None,
                                    val_ponto: float = None, unidade: str = '',
                                    contexto: str = '', norma_ref: str = '',
                                    item_ref: str = '', pagina: int = 0):
        """
        Salva parâmetro com intervalo mínimo/máximo em parametros_extraidos.

        Usado por _extrair_parametros() quando extrair_intervalo() detectar
        um intervalo bilateral (ex: "15 mm a 25 mm") ou unilateral (ex: "≥ 0,3 MPa").

        Args:
            topico_id:  ID do tópico de origem.
            laudo_id:   ID do laudo de origem.
            nome:       Nome do parâmetro (ex: 'espessura_contrapiso').
            val_min:    Valor mínimo do intervalo (pode ser None).
            val_max:    Valor máximo do intervalo (pode ser None).
            val_ponto:  Valor pontual (quando não há intervalo).
            unidade:    Unidade de medida (ex: 'mm', '%', 'MPa').
            contexto:   Trecho de texto original onde o valor foi encontrado.
            norma_ref:  NBR de referência (ex: 'NBR 13753').
            item_ref:   Item normativo (ex: '5.5.3').
            pagina:     Página do documento.
        """
        conn = self.get_connection(); cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO parametros_extraidos
            (topico_id, laudo_id, nome_parametro, valor_minimo, valor_maximo,
             valor_ponto, unidade, contexto, norma_ref, item_ref, pagina)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (topico_id, laudo_id, nome,
              val_min, val_max, val_ponto,
              unidade, contexto[:300], norma_ref, item_ref, pagina))
        # M4: dual-write na tabela unificada
        cursor.execute('''
            INSERT INTO parametros
            (laudo_id, topico_id, nome_parametro, valor_minimo, valor_maximo,
             valor_ponto, unidade, contexto, norma_ref, item_ref, pagina, origem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'extraido')
        ''', (laudo_id, topico_id, nome,
              val_min, val_max, val_ponto,
              unidade, contexto[:300], norma_ref, item_ref, pagina))
        conn.commit(); conn.close()

    def buscar_parametros_intervalo(self, nome_parametro: str,
                                    valor: float) -> List[Dict]:
        """
        Busca normas cujo intervalo definido cobre o valor consultado.

        Útil para verificar conformidade: dado um valor medido em campo,
        retorna quais normas ou laudos definem limites que cobrem aquele valor.

        Args:
            nome_parametro: Nome parcial do parâmetro (busca LIKE).
            valor:          Valor a verificar (float).

        Returns:
            List[Dict] com campos: nome_parametro, valor_minimo, valor_maximo,
            valor_ponto, unidade, contexto, norma_ref, item_ref, pagina,
            nome_arquivo, tipo_fonte, titulo_formal.

        Exemplo:
            db.buscar_parametros_intervalo('espessura_contrapiso', 18.0)
            # → normas que definem espessura entre X e Y onde X <= 18 <= Y
        """
        conn = self.get_connection(); cursor = conn.cursor()
        cursor.execute('''
            SELECT pe.nome_parametro, pe.valor_minimo, pe.valor_maximo,
                   pe.valor_ponto, pe.unidade, pe.contexto, pe.norma_ref,
                   pe.item_ref, pe.pagina,
                   l.nome_arquivo, l.tipo_fonte, l.titulo_formal
            FROM parametros_extraidos pe
            JOIN laudos l ON pe.laudo_id = l.id
            WHERE pe.nome_parametro LIKE ?
              AND l.status = 'ativo'
              AND (
                  -- Intervalo bilateral: X <= valor <= Y
                  (pe.valor_minimo IS NOT NULL AND pe.valor_maximo IS NOT NULL
                   AND pe.valor_minimo <= ? AND pe.valor_maximo >= ?)
                  OR
                  -- Limite mínimo unilateral: valor >= X  (ex: "≥ 0,3 MPa")
                  (pe.valor_minimo IS NOT NULL AND pe.valor_maximo IS NULL
                   AND pe.valor_ponto IS NULL AND pe.valor_minimo <= ?)
                  OR
                  -- Limite máximo unilateral: valor <= Y  (ex: "máximo 0,5%")
                  (pe.valor_maximo IS NOT NULL AND pe.valor_minimo IS NULL
                   AND pe.valor_ponto IS NULL AND pe.valor_maximo >= ?)
                  OR
                  -- Valor pontual exato
                  (pe.valor_ponto IS NOT NULL AND ABS(pe.valor_ponto - ?) < 0.001)
              )
            ORDER BY l.tipo_fonte, l.nome_arquivo
        ''', (f'%{nome_parametro}%', valor, valor, valor, valor, valor))
        cols = [d[0] for d in cursor.description]
        r = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close(); return r

    def buscar_parametros_v2(self, termo: str,
                             valor: float = None) -> List[Dict]:
        """M4: Consulta unificada na tabela parametros (normativos + extraídos).
        Se valor for fornecido, aplica filtro de intervalo/ponto.
        """
        conn = self.get_connection(); cursor = conn.cursor()
        sql = '''
            SELECT p.nome_parametro, p.valor_texto, p.valor_minimo, p.valor_maximo,
                   p.valor_ponto, p.unidade, p.contexto, p.norma_ref,
                   p.item_ref, p.pagina, p.origem,
                   l.nome_arquivo, l.tipo_fonte, l.ano_edicao, l.titulo_formal
            FROM parametros p JOIN laudos l ON p.laudo_id = l.id
            WHERE p.nome_parametro LIKE ? AND l.status = 'ativo'
        '''
        params: list = [f'%{termo}%']
        if valor is not None:
            sql += '''
              AND (
                  (p.valor_minimo IS NOT NULL AND p.valor_maximo IS NOT NULL
                   AND p.valor_minimo <= ? AND p.valor_maximo >= ?)
                  OR (p.valor_ponto IS NOT NULL AND ABS(p.valor_ponto - ?) < 0.001)
                  OR (p.valor_minimo IS NOT NULL AND p.valor_maximo IS NULL
                      AND p.valor_ponto IS NULL AND p.valor_minimo <= ?)
                  OR (p.valor_maximo IS NOT NULL AND p.valor_minimo IS NULL
                      AND p.valor_ponto IS NULL AND p.valor_maximo >= ?)
              )
            '''
            params.extend([valor, valor, valor, valor, valor])
        sql += ' ORDER BY l.tipo_fonte, p.nome_parametro'
        cursor.execute(sql, params)
        cols = [d[0] for d in cursor.description]
        r = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close(); return r

    def busca_estruturada(self, filtros: Dict) -> List[Dict]:
        """
        Busca multidimensional por atributos patológicos.

        Combina filtros SQL com ordenação por gravidade de risco.
        Todos os filtros são opcionais — omitir um campo não aplica restrição.

        Args:
            filtros: dict com chaves opcionais:
                tipo_anomalia     — ex. 'fissura', 'infiltração'
                origem_patologica — 'endógena' | 'exógena' | 'mista'
                risco_min         — 'Mínimo' | 'Médio' | 'Grave' | 'Crítico'
                tipo_fonte        — ex. 'norma_abnt', 'laudo_judicial'
                ia_score_min      — float 0.0–1.0 (filtra por confiança da IA)

        Returns:
            List[Dict] com campos do tópico + nome_arquivo, tipo_fonte, ano_edicao.

        Exemplo:
            db.busca_estruturada({
                'tipo_anomalia': 'fissura',
                'origem_patologica': 'endógena',
                'risco_min': 'Grave'
            })
        """
        ORDEM_RISCO = {'Mínimo': 1, 'Médio': 2, 'Grave': 3, 'Crítico': 4}

        conn   = self.get_connection()
        cursor = conn.cursor()

        sql = '''
            SELECT t.id, t.numero_topico, t.titulo_topico, t.hierarquia,
                   t.texto_original, t.texto_reescrito, t.palavras_chave,
                   t.grau_risco, t.tipo_anomalia, t.origem_patologica,
                   t.ia_score_confianca, t.pagina,
                   l.nome_arquivo, l.tipo_fonte, l.titulo_formal, l.ano_edicao
            FROM topicos t
            JOIN laudos l ON t.laudo_id = l.id
            WHERE l.status = 'ativo'
              AND t.texto_reescrito NOT LIKE '%CONTEÚDO_IRRELEVANTE%'
        '''
        params: list = []

        if filtros.get('tipo_anomalia'):
            v = f"%{filtros['tipo_anomalia']}%"
            sql += (" AND (t.tipo_anomalia LIKE ?"
                    " OR t.palavras_chave LIKE ?"
                    " OR t.texto_reescrito LIKE ?)")
            params.extend([v, v, v])

        if filtros.get('origem_patologica'):
            sql += " AND t.origem_patologica = ?"
            params.append(filtros['origem_patologica'])

        if filtros.get('tipo_fonte'):
            sql += " AND l.tipo_fonte = ?"
            params.append(filtros['tipo_fonte'])

        if filtros.get('ia_score_min') is not None:
            sql += " AND t.ia_score_confianca >= ?"
            params.append(float(filtros['ia_score_min']))

        sql += (" ORDER BY CASE t.grau_risco"
                " WHEN 'Crítico' THEN 1 WHEN 'Grave' THEN 2"
                " WHEN 'Médio'   THEN 3 WHEN 'Mínimo' THEN 4 ELSE 5 END,"
                " l.tipo_fonte LIMIT 60")

        cursor.execute(sql, params)
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close()

        # Filtrar risco_min em Python (evita hardcode de ordem no SQL para portabilidade)
        risco_min = filtros.get('risco_min')
        if risco_min and risco_min in ORDEM_RISCO:
            nivel_min = ORDEM_RISCO[risco_min]
            rows = [r for r in rows
                    if ORDEM_RISCO.get(r.get('grau_risco', ''), 0) >= nivel_min]

        return rows

    def busca_hibrida_adaptativa(self, termos: List[str],
                                  embedding_query: List[float] = None,
                                  contexto_caso: Dict = None,
                                  tipo_fonte: str = None) -> List[Dict]:
        """
        Wrapper sobre busca_hibrida() com threshold automático por contexto.

        Regras de threshold (score_hibrido mínimo para retornar resultado):
          - Qualquer termo contém 'abnt' ou 'nbr'  → 0.85 (precisão máxima)
          - num_quesitos > 50 no contexto_caso     → 0.60 (recall máximo)
          - tipo_busca == 'laudo_judicial'          → 0.70
          - Padrão                                  → 0.75

        Args:
            termos:          Lista de termos de busca.
            embedding_query: Vetor semântico da query (None = só textual).
            contexto_caso:   dict opcional:
                               'num_quesitos' (int) — total de quesitos no processo
                               'tipo_busca'   (str) — ex. 'laudo_judicial'
            tipo_fonte:      Filtro por tipo de fonte (None = todas).

        Returns:
            List[Dict] filtrados pelo threshold calculado, ordenados por score.

        Exemplo:
            db.busca_hibrida_adaptativa(
                ['NBR 13753', 'aderência cerâmica'],
                contexto_caso={'num_quesitos': 12, 'tipo_busca': 'laudo_judicial'}
            )  # threshold → 0.85 por causa de 'NBR'
        """
        ctx = contexto_caso or {}
        termos_lower = [t.lower() for t in termos]

        # Calcular threshold contextual
        if any('abnt' in t or 'nbr' in t for t in termos_lower):
            threshold = 0.85
        elif ctx.get('num_quesitos', 0) > 50:
            threshold = 0.60
        elif ctx.get('tipo_busca') == 'laudo_judicial':
            threshold = 0.70
        else:
            threshold = 0.75

        candidatos = self.busca_hibrida(
            termos=termos,
            embedding_query=embedding_query,
            tipo_fonte=tipo_fonte,
            n=25,
        )

        # Filtrar por threshold
        tem_embedding = (embedding_query and
                         any(v != 0 for v in (embedding_query or [])))
        if tem_embedding:
            return [r for r in candidatos
                    if r.get('score_hibrido', 0) >= threshold]
        else:
            # Sem embedding: threshold relativo ao melhor score textual
            max_s = max((r.get('score_textual', 0) for r in candidatos), default=1) or 1
            limiar = threshold * 0.7  # ajuste empírico para modo textual
            return [r for r in candidatos
                    if r.get('score_textual', 0) / max_s >= limiar]

    def registrar_confidence_ia(self, topico_id: int,
                                 score: float, modelo: str):
        """
        Registra score de confiança de uma análise IA para um tópico.

        Permite filtrar tópicos com baixa confiança via busca_estruturada()
        usando o parâmetro 'ia_score_min'.

        Args:
            topico_id: ID do tópico em topicos.
            score:     Float 0.0–1.0 (valores fora do range são truncados).
            modelo:    Nome do modelo usado (ex: 'gemini-1.5-flash').

        Exemplo:
            db.registrar_confidence_ia(42, 0.91, 'gemini-1.5-flash')
        """
        from datetime import datetime
        score_valido = max(0.0, min(1.0, float(score)))
        conn = self.get_connection(); cursor = conn.cursor()
        cursor.execute('''
            UPDATE topicos
            SET ia_score_confianca = ?,
                ia_modelo          = ?,
                ia_timestamp       = ?
            WHERE id = ?
        ''', (score_valido, modelo[:100],
              datetime.now().isoformat(), topico_id))
        conn.commit(); conn.close()

    # ─────────────────────────────────────────────────────────────────────────
    #  SESSÕES DE CONVERSA
    # ─────────────────────────────────────────────────────────────────────────

    def criar_sessao(self) -> int:
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sessoes DEFAULT VALUES")
        sid = cursor.lastrowid
        conn.commit(); conn.close()
        return sid

    def salvar_historico(self, sessao_id: int, papel: str, conteudo: str):
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO historico_sessao (sessao_id, papel, conteudo) VALUES (?, ?, ?)",
            (sessao_id, papel, conteudo[:4000])
        )
        cursor.execute(
            "UPDATE sessoes SET ultima_atividade = CURRENT_TIMESTAMP WHERE id = ?",
            (sessao_id,)
        )
        conn.commit(); conn.close()

    def buscar_historico_sessao(self, sessao_id: int, n: int = 4) -> List[Dict]:
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT papel, conteudo FROM historico_sessao
               WHERE sessao_id = ? ORDER BY criado_em DESC LIMIT ?''',
            (sessao_id, n * 2)
        )
        rows = [{'papel': r[0], 'conteudo': r[1]} for r in cursor.fetchall()]
        conn.close()
        return list(reversed(rows))

    # ─────────────────────────────────────────────────────────────────────────
    #  ESTATÍSTICAS
    # ─────────────────────────────────────────────────────────────────────────

    def registrar_consulta(self, termo: str):
        t = termo.lower().strip()[:200]
        if not t: return
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO consultas_populares (termo) VALUES (?)", (t,))
        cursor.execute(
            "UPDATE consultas_populares SET contagem = contagem + 1, "
            "ultima_consulta = CURRENT_TIMESTAMP WHERE termo = ?", (t,)
        )
        conn.commit(); conn.close()

    def top_consultas(self, n: int = 10) -> List[Tuple]:
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT termo, contagem, ultima_consulta FROM consultas_populares "
            "ORDER BY contagem DESC LIMIT ?", (n,)
        )
        r = cursor.fetchall(); conn.close(); return r

    def registrar_uso_trecho(self, topico_id: int,
                             sessao_id: int = None,
                             consulta: str = None):
        """Registra que um tópico foi efetivamente enviado ao LLM como contexto."""
        conn = self.get_connection()
        conn.execute(
            "INSERT INTO trechos_utilizados (topico_id, sessao_id, consulta) VALUES (?, ?, ?)",
            (topico_id, sessao_id, (consulta or '')[:200])
        )
        conn.commit(); conn.close()

    def top_trechos_utilizados(self, n: int = 10) -> List[Tuple]:
        """Tópicos mais enviados ao LLM, com badge de favorito."""
        conn = self.get_connection()
        rows = conn.execute("""
            SELECT t.id, t.titulo_topico, t.numero_topico,
                   l.nome_arquivo, l.tipo_fonte,
                   COUNT(tu.id) AS usos,
                   COALESCE(t.favorito, 0) AS favorito,
                   MAX(tu.data_uso) AS ultimo_uso
            FROM trechos_utilizados tu
            JOIN topicos t ON tu.topico_id = t.id
            JOIN laudos  l ON t.laudo_id   = l.id
            GROUP BY tu.topico_id
            ORDER BY usos DESC, favorito DESC
            LIMIT ?
        """, (n,)).fetchall()
        conn.close(); return rows

    def top_favoritos_com_uso(self, n: int = 10) -> List[Tuple]:
        """Tópicos marcados com estrela, ordenados por vezes usados pela IA."""
        conn = self.get_connection()
        rows = conn.execute("""
            SELECT t.id, t.titulo_topico, t.numero_topico,
                   l.nome_arquivo, l.tipo_fonte,
                   COALESCE(COUNT(tu.id), 0) AS usos,
                   MAX(tu.data_uso) AS ultimo_uso
            FROM topicos t
            JOIN laudos l ON t.laudo_id = l.id
            LEFT JOIN trechos_utilizados tu ON tu.topico_id = t.id
            WHERE t.favorito = 1
            GROUP BY t.id
            ORDER BY usos DESC, t.id DESC
            LIMIT ?
        """, (n,)).fetchall()
        conn.close(); return rows

    def estatisticas_banco(self) -> Dict[str, Any]:
        conn   = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM laudos WHERE status='ativo'")
        n_fontes = cursor.fetchone()[0]
        cursor.execute("SELECT tipo_fonte, COUNT(*) FROM laudos WHERE status='ativo' GROUP BY tipo_fonte")
        por_tipo = {r[0]: r[1] for r in cursor.fetchall()}
        cursor.execute("SELECT COUNT(*) FROM topicos t JOIN laudos l ON t.laudo_id=l.id WHERE l.status='ativo'")
        n_trechos = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM topicos WHERE embedding IS NOT NULL")
        n_emb = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM parametros_normativos")
        n_params_leg = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM parametros")
        n_params_uni = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM quesitos_respondidos")
        n_q = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM topicos_analise_ia")
        n_analise_ia = cursor.fetchone()[0]
        # M6: distribuição de tamanho de chunks
        cursor.execute(
            "SELECT AVG(token_count), MIN(token_count), MAX(token_count) "
            "FROM topicos WHERE token_count IS NOT NULL"
        )
        token_stats = cursor.fetchone()
        conn.close()
        return {'fontes_ativas': n_fontes, 'por_tipo': por_tipo,
                'trechos': n_trechos, 'com_embedding': n_emb,
                'parametros': n_params_leg, 'parametros_unificados': n_params_uni,
                'quesitos': n_q, 'analises_ia': n_analise_ia,
                'token_avg': round(token_stats[0] or 0, 1),
                'token_min': token_stats[1] or 0,
                'token_max': token_stats[2] or 0}

    # ─────────────────────────────────────────────────────────────────────────
    #  GUT ADAPTATIVO — Histórico e Feedback
    # ─────────────────────────────────────────────────────────────────────────

    def salvar_gut_historico(self, registro: dict) -> int:
        """
        Persiste uma avaliação GUT Adaptativa no histórico.

        Args:
            registro: dict com campos da tabela gut_historico.
                      Obrigatórios: descricao, subsistema, G_final, U_final,
                      T_final, prioridade_gut, risco_gut, fonte_avaliacao, timestamp.
        Returns:
            ID do registro inserido (int).
        """
        campos_obrigatorios = {
            'descricao', 'subsistema', 'G_final', 'U_final', 'T_final',
            'prioridade_gut', 'risco_gut', 'fonte_avaliacao', 'timestamp',
        }
        faltando = campos_obrigatorios - set(registro.keys())
        if faltando:
            raise ValueError(f"salvar_gut_historico: campos obrigatórios ausentes: {faltando}")

        conn   = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO gut_historico (
                    descricao, subsistema, embedding,
                    nexo_origem, nexo_mecanismo, nexo_status,
                    nexo_causal_texto, nexo_indeterminado,
                    G_final, U_final, T_final,
                    prioridade_gut, risco_gut,
                    npa_shs, prioridade_shs, shs_calculado, shs_converge_gut,
                    sobreposicao_detectada, fonte_avaliacao,
                    aceito_perito, G_original, U_original, T_original,
                    respostas_json, projeto_id, timestamp
                ) VALUES (
                    :descricao, :subsistema, :embedding,
                    :nexo_origem, :nexo_mecanismo, :nexo_status,
                    :nexo_causal_texto, :nexo_indeterminado,
                    :G_final, :U_final, :T_final,
                    :prioridade_gut, :risco_gut,
                    :npa_shs, :prioridade_shs, :shs_calculado, :shs_converge_gut,
                    :sobreposicao_detectada, :fonte_avaliacao,
                    :aceito_perito, :G_original, :U_original, :T_original,
                    :respostas_json, :projeto_id, :timestamp
                )
            ''', {
                'descricao':              registro.get('descricao'),
                'subsistema':             registro.get('subsistema'),
                'embedding':              registro.get('embedding'),
                'nexo_origem':            registro.get('nexo_origem'),
                'nexo_mecanismo':         registro.get('nexo_mecanismo'),
                'nexo_status':            registro.get('nexo_status'),
                'nexo_causal_texto':      registro.get('nexo_causal_texto'),
                'nexo_indeterminado':     int(registro.get('nexo_indeterminado', 0)),
                'G_final':                registro.get('G_final'),
                'U_final':                registro.get('U_final'),
                'T_final':                registro.get('T_final'),
                'prioridade_gut':         registro.get('prioridade_gut'),
                'risco_gut':              registro.get('risco_gut'),
                'npa_shs':                registro.get('npa_shs'),
                'prioridade_shs':         registro.get('prioridade_shs'),
                'shs_calculado':          int(registro.get('shs_calculado', 0)),
                'shs_converge_gut':       registro.get('shs_converge_gut'),
                'sobreposicao_detectada': int(registro.get('sobreposicao_detectada', 0)),
                'fonte_avaliacao':        registro.get('fonte_avaliacao'),
                'aceito_perito':          int(registro.get('aceito_perito', 1)),
                'G_original':             registro.get('G_original'),
                'U_original':             registro.get('U_original'),
                'T_original':             registro.get('T_original'),
                'respostas_json':         registro.get('respostas_json'),
                'projeto_id':             registro.get('projeto_id'),
                'timestamp':              registro.get('timestamp'),
            })
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logging.getLogger(__name__).error(f"salvar_gut_historico: {e}")
            raise
        finally:
            conn.close()

    def buscar_historico_similar(
        self,
        descricao: str,
        embedding,
        subsistema: str,
        threshold_semantico: float = 0.80,
        threshold_textual: float   = 0.50,
        limite: int                = 10,
        projeto_id                 = None,
    ) -> List[Dict]:
        """
        Busca casos similares no histórico GUT por similaridade semântica e textual.
        Subsistema diferente recebe desconto de 30% na similaridade.

        Returns:
            Lista de dicts com campos do gut_historico + 'similaridade' (float).
        """
        import math as _math
        conn   = self.get_connection()
        cursor = conn.cursor()
        DESCONTO = 0.30
        PESO_PROJ = 1.5

        try:
            cursor.execute('''
                SELECT id, descricao, subsistema, embedding,
                       nexo_origem, nexo_mecanismo, nexo_status,
                       G_final, U_final, T_final, prioridade_gut, risco_gut,
                       fonte_avaliacao, aceito_perito,
                       G_original, U_original, T_original,
                       respostas_json, projeto_id, timestamp,
                       sobreposicao_detectada
                FROM gut_historico
                WHERE aceito_perito = 1
                ORDER BY timestamp DESC
            ''')
            rows = cursor.fetchall()
        finally:
            conn.close()

        if not rows:
            return []

        palavras_q = set(descricao.lower().split())
        resultados = []

        for row in rows:
            (rid, desc_h, sub_h, emb_blob,
             nexo_orig, nexo_mec, nexo_st,
             G, U, T, prio, risco,
             fonte, aceito,
             G_ori, U_ori, T_ori,
             resp_json, proj_id, ts, sobre) = row

            # Jaccard textual
            palavras_h = set(desc_h.lower().split())
            union      = palavras_q | palavras_h
            sim_text   = len(palavras_q & palavras_h) / len(union) if union else 0.0

            # Cosseno semântico
            sim_vec = 0.0
            if embedding and emb_blob:
                try:
                    # M3: suporta BLOB binário e JSON legado
                    vec_h = _blob_to_embedding(emb_blob)
                    if vec_h and len(vec_h) == len(embedding):
                        dot    = sum(a * b for a, b in zip(embedding, vec_h))
                        norm_q = _math.sqrt(sum(x*x for x in embedding))
                        norm_h = _math.sqrt(sum(x*x for x in vec_h))
                        if norm_q > 0 and norm_h > 0:
                            sim_vec = dot / (norm_q * norm_h)
                except Exception:
                    pass

            sim = 0.6 * sim_vec + 0.4 * sim_text if embedding else sim_text
            if sub_h.lower() != subsistema.lower():
                sim *= (1.0 - DESCONTO)
            if projeto_id and proj_id == projeto_id:
                sim = min(1.0, sim * PESO_PROJ)

            thr = threshold_semantico if embedding else threshold_textual
            if sim < thr:
                continue

            resultados.append({
                'id': rid, 'descricao': desc_h, 'subsistema': sub_h,
                'nexo_origem': nexo_orig, 'nexo_mecanismo': nexo_mec, 'nexo_status': nexo_st,
                'G': G, 'U': U, 'T': T, 'prioridade': prio, 'risco': risco,
                'fonte': fonte, 'G_original': G_ori, 'U_original': U_ori, 'T_original': T_ori,
                'respostas_json': resp_json, 'projeto_id': proj_id, 'timestamp': ts,
                'similaridade': round(sim, 4), 'sobreposicao': bool(sobre),
            })

        resultados.sort(key=lambda x: x['similaridade'], reverse=True)
        return resultados[:limite]

    def registrar_feedback_gut(
        self,
        historico_id: int,
        aceito: bool,
        gut_corrigido: dict = None,
    ) -> None:
        """
        Registra feedback do perito sobre uma avaliação GUT.
        Se corrigido (aceito=False + gut_corrigido), atualiza G/U/T_final e
        preserva os valores originais em G/U/T_original.

        Args:
            historico_id:  ID do registro em gut_historico.
            aceito:        True = perito confirmou | False = perito rejeitou/corrigiu.
            gut_corrigido: dict com chaves G, U, T (opcional). Ex: {"G":6,"U":5,"T":4}
        """
        conn   = self.get_connection()
        cursor = conn.cursor()
        try:
            if gut_corrigido and not aceito:
                cursor.execute('''
                    UPDATE gut_historico
                    SET aceito_perito  = 0,
                        G_original     = COALESCE(G_original, G_final),
                        U_original     = COALESCE(U_original, U_final),
                        T_original     = COALESCE(T_original, T_final),
                        G_final        = :G,
                        U_final        = :U,
                        T_final        = :T,
                        prioridade_gut = :G * :U * :T
                    WHERE id = :id
                ''', {'G': gut_corrigido.get('G'), 'U': gut_corrigido.get('U'),
                      'T': gut_corrigido.get('T'), 'id': historico_id})
            else:
                cursor.execute(
                    'UPDATE gut_historico SET aceito_perito = ? WHERE id = ?',
                    (1 if aceito else 0, historico_id)
                )
            conn.commit()
        except Exception as e:
            logging.getLogger(__name__).error(f"registrar_feedback_gut: {e}")
            raise
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  FUNÇÕES STANDALONE — usadas por gut_adaptativo.py via import direto
#  (gut_adaptativo não tem acesso à instância de DatabaseManager, por isso
#   estas funções recebem conn como primeiro argumento)
# ══════════════════════════════════════════════════════════════════════════════

def salvar_gut_historico(conn: sqlite3.Connection, registro: dict) -> int:
    """
    Wrapper standalone de DatabaseManager.salvar_gut_historico().
    Chamado por gut_adaptativo.py: from database import salvar_gut_historico

    Args:
        conn:     Conexão SQLite ativa (aberta pelo chamador).
        registro: dict com os campos da tabela gut_historico.
                  Obrigatórios: descricao, subsistema, G_final, U_final,
                  T_final, prioridade_gut, risco_gut, fonte_avaliacao, timestamp.
    Returns:
        ID do registro inserido (int).
    """
    campos_obrigatorios = {
        'descricao', 'subsistema', 'G_final', 'U_final', 'T_final',
        'prioridade_gut', 'risco_gut', 'fonte_avaliacao', 'timestamp',
    }
    faltando = campos_obrigatorios - set(registro.keys())
    if faltando:
        raise ValueError(f"salvar_gut_historico: campos obrigatórios ausentes: {faltando}")

    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO gut_historico (
                descricao, subsistema, embedding,
                nexo_origem, nexo_mecanismo, nexo_status,
                nexo_causal_texto, nexo_indeterminado,
                G_final, U_final, T_final,
                prioridade_gut, risco_gut,
                npa_shs, prioridade_shs, shs_calculado, shs_converge_gut,
                sobreposicao_detectada, fonte_avaliacao,
                aceito_perito, G_original, U_original, T_original,
                respostas_json, projeto_id, timestamp
            ) VALUES (
                :descricao, :subsistema, :embedding,
                :nexo_origem, :nexo_mecanismo, :nexo_status,
                :nexo_causal_texto, :nexo_indeterminado,
                :G_final, :U_final, :T_final,
                :prioridade_gut, :risco_gut,
                :npa_shs, :prioridade_shs, :shs_calculado, :shs_converge_gut,
                :sobreposicao_detectada, :fonte_avaliacao,
                :aceito_perito, :G_original, :U_original, :T_original,
                :respostas_json, :projeto_id, :timestamp
            )
        ''', {
            'descricao':              registro.get('descricao'),
            'subsistema':             registro.get('subsistema'),
            'embedding':              registro.get('embedding'),
            'nexo_origem':            registro.get('nexo_origem'),
            'nexo_mecanismo':         registro.get('nexo_mecanismo'),
            'nexo_status':            registro.get('nexo_status'),
            'nexo_causal_texto':      registro.get('nexo_causal_texto'),
            'nexo_indeterminado':     int(registro.get('nexo_indeterminado', 0)),
            'G_final':                registro.get('G_final'),
            'U_final':                registro.get('U_final'),
            'T_final':                registro.get('T_final'),
            'prioridade_gut':         registro.get('prioridade_gut'),
            'risco_gut':              registro.get('risco_gut'),
            'npa_shs':                registro.get('npa_shs'),
            'prioridade_shs':         registro.get('prioridade_shs'),
            'shs_calculado':          int(registro.get('shs_calculado', 0)),
            'shs_converge_gut':       registro.get('shs_converge_gut'),
            'sobreposicao_detectada': int(registro.get('sobreposicao_detectada', 0)),
            'fonte_avaliacao':        registro.get('fonte_avaliacao'),
            'aceito_perito':          int(registro.get('aceito_perito', 1)),
            'G_original':             registro.get('G_original'),
            'U_original':             registro.get('U_original'),
            'T_original':             registro.get('T_original'),
            'respostas_json':         registro.get('respostas_json'),
            'projeto_id':             registro.get('projeto_id'),
            'timestamp':              registro.get('timestamp'),
        })
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logging.getLogger(__name__).error(f"salvar_gut_historico (standalone): {e}")
        raise


def buscar_historico_similar(
    conn: sqlite3.Connection,
    descricao: str,
    embedding,
    subsistema: str,
    threshold_semantico: float = 0.80,
    threshold_textual: float   = 0.50,
    limite: int                = 10,
    projeto_id                 = None,
) -> List[Dict]:
    """
    Wrapper standalone de DatabaseManager.buscar_historico_similar().
    Chamado por gut_adaptativo.py: from database import buscar_historico_similar

    Args:
        conn:                Conexão SQLite ativa (aberta pelo chamador).
        descricao:           Texto da nova anomalia a comparar.
        embedding:           Vetor semântico da query (pode ser None).
        subsistema:          Subsistema da avaliação atual.
        threshold_semantico: Limiar mínimo de similaridade para modo autônomo.
        threshold_textual:   Limiar mínimo para similaridade por palavras.
        limite:              Número máximo de casos retornados.
        projeto_id:          Se informado, casos do mesmo projeto recebem peso 1.5.

    Returns:
        Lista de dicts com campos do gut_historico + 'similaridade' +
        aliases 'G_final', 'U_final', 'T_final' para compatibilidade.
    """
    import math as _math
    DESCONTO = 0.30
    PESO_PROJ = 1.5

    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, descricao, subsistema, embedding,
               nexo_origem, nexo_mecanismo, nexo_status,
               G_final, U_final, T_final, prioridade_gut, risco_gut,
               fonte_avaliacao, aceito_perito,
               G_original, U_original, T_original,
               respostas_json, projeto_id, timestamp,
               sobreposicao_detectada
        FROM gut_historico
        WHERE aceito_perito = 1
        ORDER BY timestamp DESC
    ''')
    rows = cursor.fetchall()

    if not rows:
        return []

    palavras_q = set(descricao.lower().split())
    resultados = []

    for row in rows:
        (rid, desc_h, sub_h, emb_blob,
         nexo_orig, nexo_mec, nexo_st,
         G, U, T, prio, risco,
         fonte, aceito,
         G_ori, U_ori, T_ori,
         resp_json, proj_id, ts, sobre) = row

        # Jaccard textual
        palavras_h = set(desc_h.lower().split())
        union      = palavras_q | palavras_h
        sim_text   = len(palavras_q & palavras_h) / len(union) if union else 0.0

        # Cosseno semântico
        sim_vec = 0.0
        if embedding and emb_blob:
            try:
                import json as _j
                vec_h = _j.loads(emb_blob) if isinstance(emb_blob, str) else []
                if vec_h and len(vec_h) == len(embedding):
                    dot    = sum(a * b for a, b in zip(embedding, vec_h))
                    norm_q = _math.sqrt(sum(x*x for x in embedding))
                    norm_h = _math.sqrt(sum(x*x for x in vec_h))
                    if norm_q > 0 and norm_h > 0:
                        sim_vec = dot / (norm_q * norm_h)
            except Exception:
                pass

        sim = 0.6 * sim_vec + 0.4 * sim_text if embedding else sim_text
        if sub_h.lower() != subsistema.lower():
            sim *= (1.0 - DESCONTO)
        if projeto_id and proj_id == projeto_id:
            sim = min(1.0, sim * PESO_PROJ)

        thr = threshold_semantico if embedding else threshold_textual
        if sim < thr:
            continue

        resultados.append({
            'id':             rid,
            'descricao':      desc_h,
            'subsistema':     sub_h,
            'nexo_origem':    nexo_orig,
            'nexo_mecanismo': nexo_mec,
            'nexo_status':    nexo_st,
            # Chaves com e sem sufixo _final para compatibilidade total
            'G':       G,   'G_final': G,
            'U':       U,   'U_final': U,
            'T':       T,   'T_final': T,
            'prioridade':    prio,
            'risco':         risco,
            'fonte':         fonte,
            'aceito_perito': aceito,
            'G_original':    G_ori,
            'U_original':    U_ori,
            'T_original':    T_ori,
            'respostas_json': resp_json,
            'projeto_id':    proj_id,
            'timestamp':     ts,
            'similaridade':  round(sim, 4),
            'sobreposicao':  bool(sobre),
        })

    resultados.sort(key=lambda x: x['similaridade'], reverse=True)
    return resultados[:limite]



# =============================================================================
# IDF TÉCNICO ADAPTATIVO — Palavras-Chave v2.0
# Referência: extrair_palavras_chave_v2 | Seção 5.3 da especificação
# =============================================================================

def calcular_idf_termo(
    conn: sqlite3.Connection,
    termo: str,
    total_topicos: Optional[int] = None,
) -> float:
    """
    Calcula IDF técnico para um termo no banco de tópicos.

    Fórmula: IDF = log(N_total / (N_com_termo + 1))
    Intervalo de valores: 0.0 (ubíquo) a ~8.0 (raro no corpus).

    Args:
        conn:          Conexão SQLite ativa (aberta pelo chamador).
        termo:         Termo a calcular (case-insensitive via LIKE).
        total_topicos: Total de tópicos no banco (opcional — otimização
                       para evitar COUNT(*) repetido em batch).
    Returns:
        float IDF (>= 0.0).

    Exemplo de uso:
        conn = sqlite3.connect("cerebro_pericial.db")
        idf = calcular_idf_termo(conn, "fissura")
        # → 2.1  (aparece em ~12% dos tópicos)
        idf_raro = calcular_idf_termo(conn, "pull-off")
        # → 4.0  (aparece em ~2% dos tópicos)
        conn.close()
    """
    try:
        if total_topicos is None:
            total_topicos = conn.execute(
                "SELECT COUNT(*) FROM topicos"
            ).fetchone()[0]

        if total_topicos == 0:
            return 0.0

        freq = conn.execute(
            "SELECT COUNT(*) FROM topicos WHERE palavras_chave LIKE ?",
            (f"%{termo}%",),
        ).fetchone()[0]

        return math.log(total_topicos / (freq + 1))

    except Exception as e:
        logging.getLogger(__name__).warning(
            f"calcular_idf_termo: falha para '{termo}': {e}"
        )
        return 1.5  # IDF médio como fallback seguro


# ══════════════════════════════════════════════════════════════════════════════
# SEÇÃO — BUSCA DE TRECHOS PARA ANOTAÇÕES PERICIAIS (GUT Adaptativo)
# Implementa buscar_trechos_para_anotacao() e funções auxiliares.
# Referência: Prompt de Implementação v1.0 — Seções 4 e 5.
# ══════════════════════════════════════════════════════════════════════════════

# Mapeamento de tipos de fonte para filtro SQL
_TIPO_FONTE_MAP: Dict[str, List[str]] = {
    "norma":  ["norma_abnt", "norma_iso", "norma_outro"],
    "laudo":  ["laudo_judicial", "parecer_tecnico"],
    "todas":  [],
}


def buscar_trechos_para_anotacao(
    db_manager: Any,
    query: str,
    fonte_filtro: Optional[str] = None,
    limite: int = 5,
    projeto_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Busca trechos do banco para uso em anotações periciais.
    Retorna textos COMPLETOS — sem truncamento em nenhum campo.

    Reutiliza busca_hibrida() do DatabaseManager existente.
    Adiciona metadados completos para formatação na anotação.

    Args:
        db_manager:   Instância de DatabaseManager (ou objeto com
                      get_connection() e busca_hibrida()).
        query:        Termos de busca (frase ou palavras-chave).
        fonte_filtro: "norma" | "laudo" | None / "todas" (padrão: todas).
        limite:       Máximo de resultados retornados (1–15).
        projeto_id:   Reservado para filtro futuro por projeto ativo.

    Returns:
        Lista de dicts com campos:
            id, texto (COMPLETO), hierarquia, nome_fonte,
            tipo_fonte, score, ano_edicao, titulo_topico, pagina.
    """
    limite = max(1, min(15, limite))

    # Filtro de tipo de fonte para busca_hibrida
    tipo_fonte_filtro: Optional[str] = None
    tipos_validos = _TIPO_FONTE_MAP.get(fonte_filtro or "todas", [])
    if tipos_validos:
        # busca_hibrida aceita apenas um tipo por vez; usamos o primeiro
        # e depois filtramos os demais manualmente no resultado
        tipo_fonte_filtro = None  # buscar tudo, filtrar depois

    # Tokenizar query
    termos = [t.strip() for t in query.replace(",", " ").split() if len(t.strip()) >= 3]
    if not termos:
        return []

    try:
        # Executar busca_hibrida (sem embedding — offline-first)
        resultados_raw = db_manager.busca_hibrida(
            termos=termos,
            embedding_query=None,
            tipo_fonte=tipo_fonte_filtro,
            n=limite * 3,  # buscar mais para poder filtrar por fonte
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "buscar_trechos_para_anotacao: erro na busca_hibrida: %s", exc
        )
        return []

    # Filtrar por tipos de fonte se necessário
    if tipos_validos:
        resultados_raw = [
            r for r in resultados_raw
            if r.get("tipo_fonte") in tipos_validos
        ]

    resultados: List[Dict[str, Any]] = []
    for r in resultados_raw[:limite]:
        # texto COMPLETO — nunca truncar
        texto_completo = (r.get("texto_original") or r.get("texto_reescrito") or "").strip()
        score = r.get("score_hibrido") or r.get("score_textual") or 0.0
        resultados.append({
            "id":           r.get("id"),
            "texto":        texto_completo,
            "hierarquia":   (r.get("hierarquia") or "").strip(),
            "nome_fonte":   (r.get("nome_arquivo") or "—"),
            "tipo_fonte":   (r.get("tipo_fonte") or "outro"),
            "score":        float(score),
            "ano_edicao":   r.get("ano_edicao") or "",
            "titulo_topico":r.get("titulo_topico") or "",
            "pagina":       r.get("pagina") or 0,
        })

    return resultados


def formatar_trecho_para_anotacao(
    topico: Dict[str, Any],
    numero_selecao: int = 1,
) -> str:
    """
    Formata um tópico do banco para inserção em anotação pericial.
    Inclui cabeçalho rastreável com fonte, hierarquia e score.

    O marcador "─── [" no cabeçalho permite:
      - Detectar quantos trechos foram vinculados (contar_trechos_vinculados)
      - Identificar fontes usadas no laudo
      - Futura exportação de referências automática

    Args:
        topico:          Dict retornado por buscar_trechos_para_anotacao().
        numero_selecao:  Número de ordem na seleção (para referência).

    Returns:
        String formatada com separador, cabeçalho e texto completo.
    """
    sep = "─" * 60
    score_pct = round(topico.get("score", 0) * 100)
    hierarquia = topico.get("hierarquia", "").strip()
    nome_fonte = topico.get("nome_fonte", "—")
    texto = topico.get("texto", "").strip()

    cabecalho = (
        f"\n{sep}\n"
        f"[{nome_fonte}]"
        + (f" {hierarquia}" if hierarquia else "")
        + f" (Score: {score_pct}%)\n"
        f"{sep}\n"
    )
    return cabecalho + texto + f"\n{sep}\n"


def montar_anotacao_final(
    anotacao_anterior: str,
    texto_livre: str,
    trechos_formatados: List[str],
) -> str:
    """
    Combina anotação anterior, texto livre do perito e trechos selecionados.

    Regras de montagem (conforme Seção 2 — Passo 5):
      - Preserva anotação anterior sem alteração
      - Acrescenta texto livre após separação por linha em branco
      - Appenda trechos selecionados em ordem de seleção

    Args:
        anotacao_anterior:   Conteúdo já existente (pode ser vazio).
        texto_livre:         Texto digitado pelo perito na confirmação.
        trechos_formatados:  Lista de strings de formatar_trecho_para_anotacao().

    Returns:
        String com anotação final montada.
    """
    # Montagem conforme Seção 4 v2.0 — sem strip nos trechos
    # para preservar a formatação dos separadores ─────
    partes: List[str] = []

    if anotacao_anterior.strip():
        partes.append(anotacao_anterior.strip())

    if texto_livre.strip():
        partes.append(texto_livre.strip())

    for t in trechos_formatados:
        if t.strip():
            partes.append(t)

    return "\n\n".join(partes)


def contar_trechos_vinculados(anotacao: str) -> int:
    """
    Conta quantos trechos de banco foram vinculados a uma anotação.
    Detecta pelo marcador '─── [' ou '[' após linha de separação.

    Args:
        anotacao: Texto da anotação (pode conter múltiplos trechos).

    Returns:
        Número inteiro de trechos detectados (0 se nenhum).
    """
    if not anotacao:
        return 0
    import re
    # Conta ocorrências do padrão de cabeçalho de trecho
    # Formato: linha de '─' seguida de linha com '[nome_fonte]'
    padrao = re.compile(r"^─{10,}", re.MULTILINE)
    marcadores = padrao.findall(anotacao)
    # formatar_trecho_para_insercao usa 3 separadores por trecho
    # (cabecalho-abertura + cabecalho-fechamento + rodape)
    return max(0, len(marcadores) // 3)


def buscar_trechos_banco(
    db_manager: Any,
    query: str,
    fonte_filtro: Optional[str] = None,
    limite: int = 5,
) -> List[Dict[str, Any]]:
    """
    Busca trechos do banco para consulta e seleção pericial.
    Wrapper sobre buscar_trechos_para_anotacao() com nome
    canônico para o fluxo [C] — Consultar Banco.

    CRITICO: campo 'texto' SEMPRE retornado completo.
    Sem limite de caracteres, sem truncamento.

    Args:
        db_manager:   Instância de DatabaseManager.
        query:        Termos de busca do perito.
        fonte_filtro: "norma" | "laudo" | "livro" | None.
        limite:       Máximo de resultados (1-15).

    Returns:
        list[dict] com campos: id, texto (COMPLETO),
        hierarquia, nome_fonte, tipo_fonte, score, ano_edicao.
    """
    # Mapear filtro de livro para tipo_fonte
    if fonte_filtro == "livro":
        fonte_filtro_interno = "livro"
    else:
        fonte_filtro_interno = fonte_filtro

    # Reutilizar buscar_trechos_para_anotacao existente
    return buscar_trechos_para_anotacao(
        db_manager=db_manager,
        query=query,
        fonte_filtro=fonte_filtro_interno,
        limite=limite,
    )


def formatar_trecho_para_insercao(
    topico: Dict[str, Any],
    modo: str,
    texto_parcial: Optional[str] = None,
) -> str:
    """
    Formata trecho para inserção na anotação.
    Inclui cabeçalho rastreável — nunca omitir a fonte.

    O marcador "─── Fonte:" permite:
      1. Detectar quantos trechos foram inseridos
      2. Extrair automaticamente referências normativas
      3. Auditoria da fundamentação da análise

    Args:
        topico:        Dict de buscar_trechos_banco().
        modo:          "integral" | "parcial".
        texto_parcial: Texto digitado pelo perito (modo parcial).

    Returns:
        String com cabeçalho rastreável + corpo do trecho.
    """
    sep = "─" * 60
    score_pct = round(topico.get("score", 0) * 100)
    hierarquia = (topico.get("hierarquia") or "").strip()
    nome_fonte = topico.get("nome_fonte", "—")
    texto_integral = topico.get("texto", "").strip()

    cabecalho = (
        f"\n{sep}\n"
        f"Fonte: [{nome_fonte}]\n"
        f"Secao: {hierarquia}\n"
        f"Score: {score_pct}%"
        + (" | Trecho parcial" if modo == "parcial" else "")
        + f"\n{sep}\n"
    )
    # NUNCA truncar — usar texto_parcial ou texto_integral completo
    # Nunca truncar — spec v2.0: corpo = texto_parcial OR topico["texto"] sem modificacao
    corpo = texto_parcial if (modo == "parcial" and texto_parcial) else topico.get("texto", "")
    return cabecalho + corpo + f"\n{sep}\n"


def sugerir_sinonimos_busca(
    query: str,
    dicionario: Dict[str, List[str]],
) -> List[str]:
    """
    Sugere sinônimos para termos da query sem resultado.
    Busca no dicionario (DICIONARIO_SINONIMOS de processors.py).

    Args:
        query:       Termos digitados pelo perito.
        dicionario:  Dict {conceito: [sinonimos]}.

    Returns:
        Lista de até 3 sugestões de termos alternativos.
    """
    termos = query.lower().split()
    sugestoes: List[str] = []
    for termo in termos:
        # Checar se termo é variante conhecida
        for conceito, sins in dicionario.items():
            sins_lower = [s.lower() for s in sins]
            if termo in sins_lower and conceito not in sugestoes:
                sugestoes.append(conceito)
                break
            if termo == conceito.lower():
                for s in sins[:2]:
                    if s not in sugestoes:
                        sugestoes.append(s)
                break
        if len(sugestoes) >= 3:
            break
    return sugestoes[:3]

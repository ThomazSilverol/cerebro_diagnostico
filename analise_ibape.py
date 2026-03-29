"""
analise_ibape.py — Módulo de Análise Técnica Normatizada IBAPE
Sistema: Cérebro de Engenharia Diagnóstica v2.0
Versão:  1.0

Implementa os três eixos de descrição técnica de anomalias e falhas
conforme diretrizes do IBAPE Nacional (2025), com banco de dados dedicado
e independente do banco principal do sistema.

Referências normativas:
  IBAPE Nacional (2025) — Diretrizes Técnicas para Perícias Judiciais
  ABNT NBR 13752:2024   — Perícias de Engenharia na Construção Civil
  ABNT NBR 16747:2020   — Inspeção Predial
  ABNT NBR 15575-1:2024 — Desempenho de Edificações
  ABNT NBR 5674:2012    — Manutenção de Edificações
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, date
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 2.1 — ANOMALIA (Item 12.1 IBAPE / NBR 13752:2024 § 7.3.3.4)
# ══════════════════════════════════════════════════════════════════════════════

ANOMALIA_DEFINICAO = (
    "Falhas ou inadequações técnicas ou funcionais que afetam o desempenho "
    "e a durabilidade de sistemas, elementos ou componentes da edificação, "
    "podendo ser de origem endógena, exógena, natural ou funcional.\n"
    "Fonte: IBAPE (2025), item 12.1; NBR 13752:2024, item 7.3.3.4.5.1"
)


class AnomaliaOrigem(str, Enum):
    """
    Classificações de origem da anomalia conforme IBAPE (2025), item 12.1.
    Referência: ABNT NBR 13752:2024, item 7.3.3.4.5.1.
    """
    ENDOGENA   = "Endógena"
    EXOGENA    = "Exógena"
    NATURAL    = "Natural"
    FUNCIONAL  = "Funcional"


class AnomaliaClassificacao(str, Enum):
    """
    Natureza jurídica da anomalia. Conforme IBAPE (2025) e NBR 15575-1:2024.
    """
    VICIO_CONSTRUTIVO = "Vício Construtivo"
    AVARIA            = "Avaria"
    DECREPITUDE       = "Decrepitude"
    DETERIORACAO      = "Deterioração"
    A_CLASSIFICAR     = "A Classificar"


# Mapeamento de origem → configuração de defaults e obrigatoriedades
ANOMALIA_CONFIG: Dict[str, Dict[str, Any]] = {
    "Endógena": {
        "natureza_default":  "Vício Construtivo",
        "naturezas_opcoes":  ["Vício Construtivo"],
        "nexo_obrigatorio":  True,
        "implicacao":        "Responsabilidade do construtor/projetista.",
        "falha_sugerida":    "Verificar se houve agravamento por falha de manutenção.",
        "exemplos": [
            "Cobrimento de armadura inferior ao especificado em projeto",
            "Argamassa de assentamento com traço inadequado",
            "Impermeabilização executada sem primer de aderência",
            "Desplacamento cerâmico por perda de aderência na execução",
            "Recalque diferencial por fundação subdimensionada",
        ],
    },
    "Exógena": {
        "natureza_default":  "Avaria",
        "naturezas_opcoes":  ["Avaria"],
        "nexo_obrigatorio":  True,
        "implicacao":        "Responsabilidade do agente causador externo.",
        "falha_auto":        "Não Aplicável",
        "exemplos": [
            "Fissuração por obras de escavação em terreno vizinho",
            "Perfuração de impermeabilização para instalação de antena",
            "Impacto de veículo em elemento estrutural ou de vedação",
            "Sobrecarga acima do limite de projeto imposta por terceiro",
        ],
    },
    "Natural": {
        "natureza_default":  "A Classificar",
        "naturezas_opcoes":  ["Avaria", "Decrepitude"],
        "nexo_obrigatorio":  True,
        "implicacao":        "Caso fortuito — verificar cobertura de seguro e adequação do projeto ao local.",
        "falha_sugerida":    "Verificar se ausência de proteção ou manutenção agravou o dano.",
        "exemplos": [
            "Fissuração por variação térmica extrema sazonal",
            "Infiltração por chuva de intensidade excepcional (> 50 mm/h)",
            "Dano por sismo, raio, inundação de origem natural",
            "Eflorescência por umidade ascendente natural do solo",
        ],
    },
    "Funcional": {
        "natureza_default":  "A Classificar",
        "naturezas_opcoes":  ["Decrepitude", "Deterioração"],
        "nexo_obrigatorio":  True,
        "implicacao":        "Responsabilidade do proprietário/usuário — verificar aderência ao manual do proprietário.",
        "falha_obrigatoria": True,
        "exemplos": [
            "Perda de estanqueidade de telhado após vida útil esgotada",
            "Deterioração de pintura por ausência de repintura periódica",
            "Entupimento de drenos por falta de limpeza programada",
            "Trinca em revestimento por ausência de manutenção preventiva",
        ],
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 2.2 — FALHA (Item 12.2 IBAPE / ABNT NBR 5674:2012)
# ══════════════════════════════════════════════════════════════════════════════

FALHA_DEFINICAO = (
    "Não conformidades ligadas à manutenção, operação ou uso da edificação. "
    "As falhas são classificadas conforme a natureza de sua origem, que pode "
    "ser de planejamento, execução, operacional ou gerencial.\n"
    "Fonte: IBAPE (2025), item 12.2; ABNT NBR 5674:2012"
)


class FalhaOrigem(str, Enum):
    """
    Classificações de origem da falha de manutenção conforme IBAPE (2025), item 12.2.
    Referência: ABNT NBR 5674:2012.
    """
    PLANEJAMENTO  = "Planejamento"
    EXECUCAO      = "Execução"
    OPERACIONAL   = "Operacional"
    GERENCIAL     = "Gerencial"
    NAO_APLICAVEL = "Não Aplicável"


FALHA_CONFIG: Dict[str, Dict[str, Any]] = {
    "Planejamento": {
        "descricao": "Deficiências no plano de manutenção quanto a critérios técnicos, adequação ao uso, confiabilidade e periodicidades.",
        "perguntas": [
            "Existe plano de manutenção conforme NBR 5674?",
            "As periodicidades estão adequadas ao tipo de sistema?",
            "Os critérios técnicos são compatíveis com o manual?",
        ],
        "exemplos": [
            "Ausência de plano de manutenção preventiva documentado",
            "Plano com periodicidades inferiores às recomendadas",
            "Plano não contempla sistema afetado pela anomalia",
        ],
    },
    "Execução": {
        "descricao": "Realização inadequada das atividades de manutenção programada, incluindo erros técnicos, materiais incompatíveis e negligência.",
        "perguntas": [
            "A manutenção foi realizada conforme especificação?",
            "Os materiais aplicados são compatíveis com o sistema?",
            "Os procedimentos foram executados corretamente?",
        ],
        "exemplos": [
            "Pintura de fachada sem tratamento prévio das fissuras",
            "Impermeabilização de reparação com material incompatível",
            "Serviço de manutenção executado por profissional não habilitado",
        ],
    },
    "Operacional": {
        "descricao": "Deficiências em procedimentos de controle, registros de manutenção, rotinas de verificação e inspeção periódica.",
        "perguntas": [
            "Há registros das manutenções realizadas?",
            "As inspeções periódicas foram documentadas?",
            "As anomalias identificadas foram registradas e tratadas?",
        ],
        "exemplos": [
            "Ausência de livro de registro de manutenções",
            "Inspeções prediais não realizadas no prazo NBR 16747",
            "Anomalias identificadas mas não registradas ou não tratadas",
        ],
    },
    "Gerencial": {
        "descricao": "Ausência de supervisão técnica, controle de qualidade dos serviços, monitoramento de custos e eficiência do plano.",
        "perguntas": [
            "Há responsável técnico pela gestão da manutenção?",
            "Os serviços contratados são fiscalizados tecnicamente?",
            "Há controle de qualidade das manutenções executadas?",
        ],
        "exemplos": [
            "Síndico sem suporte técnico para gestão da manutenção",
            "Contratação de serviços sem especificação técnica adequada",
            "Ausência de controle de qualidade pós-serviço de manutenção",
        ],
    },
    "Não Aplicável": {
        "descricao": "Anomalia sem relação com falha de manutenção/uso (origem exógena ou dados insuficientes).",
        "perguntas": [],
        "exemplos": [],
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 2.3 — GRAU DE RISCO (Item 12.3 IBAPE / NBR 16747:2020)
# ══════════════════════════════════════════════════════════════════════════════

GRAU_RISCO_DEFINICAO = (
    "Metodologia para determinação do grau de risco associado a uma anomalia "
    "ou falha, considerando os potenciais impactos à segurança dos usuários, "
    "à preservação do meio ambiente e à integridade do patrimônio.\n"
    "Fonte: IBAPE (2025), item 12.3; ABNT NBR 16747:2020"
)


class GrauRiscoIBAPE(str, Enum):
    """
    Graus de risco conforme IBAPE (2025), item 12.3 e ABNT NBR 16747:2020.
    """
    CRITICO = "Crítico"
    MEDIO   = "Médio"
    MINIMO  = "Mínimo"


GRAU_RISCO_CONFIG: Dict[str, Dict[str, Any]] = {
    "Crítico": {
        "emoji":  "🔴",
        "prazo":  "Intervenção imediata (horas/dias)",
        "acao":   "Interdição parcial ou total + intervenção imediata + laudo de urgência.",
        "criterios": [
            "Ameaça direta à vida, saúde ou segurança dos usuários",
            "Comprometimento severo da funcionalidade do sistema",
            "Custos de reparo elevados com tendência de agravamento",
            "Redução significativa da vida útil da edificação",
            "Impacto ambiental severo (contaminação, erosão, etc.)",
        ],
    },
    "Médio": {
        "emoji":  "🟡",
        "prazo":  "Até 90 dias",
        "acao":   "Planejamento de reparo + monitoramento periódico.",
        "criterios": [
            "Redução parcial de desempenho ou funcionalidade",
            "Não compromete sistemas essenciais de segurança",
            "Deterioração antecipada com agravamento progressivo",
            "Exige atenção preventiva antes do agravamento crítico",
        ],
    },
    "Mínimo": {
        "emoji":  "🟢",
        "prazo":  "Próximo ciclo de manutenção programada",
        "acao":   "Incluir no próximo ciclo de manutenção preventiva.",
        "criterios": [
            "Impacto limitado, predominantemente estético",
            "Tratável por manutenção programada rotineira",
            "Sem riscos à segurança, saúde ou meio ambiente",
            "Sem impacto relevante sobre valor patrimonial",
            "Não afeta funcionalidade dos sistemas essenciais",
        ],
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 3 — BANCO DE DADOS DEDICADO
# ══════════════════════════════════════════════════════════════════════════════

_DDL_ANALISES = """
CREATE TABLE IF NOT EXISTS analises_ibape (
    id                   INTEGER  PRIMARY KEY AUTOINCREMENT,

    -- IDENTIFICAÇÃO
    codigo_analise       TEXT     NOT NULL UNIQUE,
    titulo               TEXT     NOT NULL,
    data_vistoria        TEXT     DEFAULT NULL,
    perito_responsavel   TEXT     DEFAULT NULL,

    -- ITEM 12.1 — ANOMALIA
    anomalia_origem      TEXT     NOT NULL,
    anomalia_natureza    TEXT     NOT NULL,
    anomalia_sistema     TEXT     DEFAULT NULL,
    anomalia_elemento    TEXT     DEFAULT NULL,
    anomalia_descricao   TEXT     NOT NULL,
    anomalia_sintomas    TEXT     DEFAULT NULL,

    -- ITEM 12.2 — FALHA
    falha_origem         TEXT     NOT NULL,
    falha_descricao      TEXT     DEFAULT NULL,
    falha_evidencias     TEXT     DEFAULT NULL,
    nexo_causal          TEXT     DEFAULT NULL,

    -- ITEM 12.3 — GRAU DE RISCO
    grau_risco           TEXT     NOT NULL,
    grau_justificativa   TEXT     NOT NULL,
    grau_impacto_seg     TEXT     DEFAULT NULL,
    grau_impacto_amb     TEXT     DEFAULT NULL,
    grau_impacto_pat     TEXT     DEFAULT NULL,
    prazo_intervencao    TEXT     DEFAULT NULL,
    acao_recomendada     TEXT     NOT NULL,

    -- REFERÊNCIAS NORMATIVAS
    normas_referencias   TEXT     DEFAULT NULL,
    topicos_banco        TEXT     DEFAULT NULL,

    -- SEÇÕES DESCRITIVAS DO LAUDO (NBR 13752)
    reclamacao_cliente       TEXT     DEFAULT '',
    ensaios_realizados       TEXT     DEFAULT '',
    metodologia_inspecao     TEXT     DEFAULT '',
    normas_descumpridas      TEXT     DEFAULT '',
    explicacao_classificacao TEXT     DEFAULT '',
    consequencias_risco      TEXT     DEFAULT '',

    -- VÍNCULOS COM OUTROS MÓDULOS
    item_laudo_id        INTEGER  DEFAULT NULL,
    gut_historico_id     INTEGER  DEFAULT NULL,
    G_gut                INTEGER  DEFAULT NULL,
    U_gut                INTEGER  DEFAULT NULL,
    T_gut                INTEGER  DEFAULT NULL,
    prioridade_gut       INTEGER  DEFAULT NULL,

    -- TEXTO FINAL PARA LAUDO
    texto_laudo          TEXT     DEFAULT NULL,
    texto_recomendacao   TEXT     DEFAULT NULL,

    -- RASTREABILIDADE
    projeto_id           INTEGER  DEFAULT NULL,
    revisao              INTEGER  DEFAULT 1,
    status               TEXT     DEFAULT 'rascunho',
    flags_inconsistencia TEXT     DEFAULT NULL,
    timestamp_criacao    TEXT     NOT NULL,
    timestamp_edicao     TEXT     DEFAULT NULL
);
"""

_DDL_HISTORICO = """
CREATE TABLE IF NOT EXISTS historico_analises_ibape (
    id             INTEGER  PRIMARY KEY AUTOINCREMENT,
    analise_id     INTEGER  NOT NULL,
    revisao        INTEGER  NOT NULL,
    campo_alterado TEXT     NOT NULL,
    valor_anterior TEXT     DEFAULT NULL,
    valor_novo     TEXT     DEFAULT NULL,
    timestamp      TEXT     NOT NULL
);
"""


def inicializar_banco(caminho: str = "analise_ibape.db") -> sqlite3.Connection:
    """
    Cria ou abre o banco dedicado analise_ibape.db.
    Cria as tabelas analises_ibape e historico_analises_ibape se não existirem.

    Args:
        caminho: Caminho completo do arquivo .db.
                 Padrão: mesma pasta do script.
    Returns:
        sqlite3.Connection com check_same_thread=False.
    Conforme IBAPE (2025) — princípio de banco dedicado e rastreabilidade.
    """
    try:
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(caminho, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute(_DDL_ANALISES)
        conn.execute(_DDL_HISTORICO)
        # Migração para bancos existentes — adiciona colunas NBR 13752 se ausentes
        _novos_campos = [
            ("reclamacao_cliente",       "TEXT DEFAULT ''"),
            ("ensaios_realizados",       "TEXT DEFAULT ''"),
            ("metodologia_inspecao",     "TEXT DEFAULT ''"),
            ("normas_descumpridas",      "TEXT DEFAULT ''"),
            ("explicacao_classificacao", "TEXT DEFAULT ''"),
            ("consequencias_risco",      "TEXT DEFAULT ''"),
        ]
        for _col, _tipo in _novos_campos:
            try:
                conn.execute(f"ALTER TABLE analises_ibape ADD COLUMN {_col} {_tipo}")
            except sqlite3.OperationalError:
                pass  # coluna já existe
        conn.commit()
        logger.info("Banco analise_ibape inicializado: %s", caminho)
        return conn
    except sqlite3.Error as exc:
        logger.error("Erro ao inicializar banco IBAPE: %s", exc)
        raise


def salvar_analise(conn: sqlite3.Connection, analise: dict) -> int:
    """
    Insere nova análise em analises_ibape.
    Gera codigo_analise automático no formato 'IBAPE-{ANO}-{SEQUENCIAL:04d}'.
    Serializa normas_referencias e topicos_banco como JSON.

    Args:
        conn:    Conexão ao analise_ibape.db.
        analise: dict com os campos da análise (campos opcionais podem estar ausentes).
    Returns:
        ID do registro inserido (int).
    Conforme IBAPE (2025), item 12 — rastreabilidade e codificação de análises.
    """
    try:
        now = datetime.now().isoformat(timespec="seconds")
        codigo = _gerar_codigo_analise(conn)

        normas = analise.get("normas_referencias") or []
        if isinstance(normas, list):
            normas = json.dumps(normas, ensure_ascii=False)

        topicos = analise.get("topicos_banco") or []
        if isinstance(topicos, list):
            topicos = json.dumps(topicos, ensure_ascii=False)

        flags = analise.get("flags_inconsistencia") or []
        if isinstance(flags, list):
            flags = json.dumps(flags, ensure_ascii=False)

        grau_cfg = GRAU_RISCO_CONFIG.get(analise.get("grau_risco", ""), {})
        prazo = analise.get("prazo_intervencao") or grau_cfg.get("prazo", "")

        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO analises_ibape (
                codigo_analise, titulo, data_vistoria, perito_responsavel,
                anomalia_origem, anomalia_natureza, anomalia_sistema,
                anomalia_elemento, anomalia_descricao, anomalia_sintomas,
                falha_origem, falha_descricao, falha_evidencias, nexo_causal,
                grau_risco, grau_justificativa, grau_impacto_seg,
                grau_impacto_amb, grau_impacto_pat, prazo_intervencao,
                acao_recomendada, normas_referencias, topicos_banco,
                item_laudo_id, gut_historico_id,
                G_gut, U_gut, T_gut, prioridade_gut,
                texto_laudo, texto_recomendacao,
                projeto_id, revisao, status,
                flags_inconsistencia, timestamp_criacao,
                reclamacao_cliente, ensaios_realizados, metodologia_inspecao,
                normas_descumpridas, explicacao_classificacao, consequencias_risco
            ) VALUES (
                :codigo_analise, :titulo, :data_vistoria, :perito_responsavel,
                :anomalia_origem, :anomalia_natureza, :anomalia_sistema,
                :anomalia_elemento, :anomalia_descricao, :anomalia_sintomas,
                :falha_origem, :falha_descricao, :falha_evidencias, :nexo_causal,
                :grau_risco, :grau_justificativa, :grau_impacto_seg,
                :grau_impacto_amb, :grau_impacto_pat, :prazo_intervencao,
                :acao_recomendada, :normas_referencias, :topicos_banco,
                :item_laudo_id, :gut_historico_id,
                :G_gut, :U_gut, :T_gut, :prioridade_gut,
                :texto_laudo, :texto_recomendacao,
                :projeto_id, 1, :status,
                :flags_inconsistencia, :timestamp_criacao,
                :reclamacao_cliente, :ensaios_realizados, :metodologia_inspecao,
                :normas_descumpridas, :explicacao_classificacao, :consequencias_risco
            )
        """, {
            "codigo_analise":    codigo,
            "titulo":            analise.get("titulo", ""),
            "data_vistoria":     analise.get("data_vistoria"),
            "perito_responsavel":analise.get("perito_responsavel"),
            "anomalia_origem":   analise.get("anomalia_origem", ""),
            "anomalia_natureza": analise.get("anomalia_natureza", "A Classificar"),
            "anomalia_sistema":  analise.get("anomalia_sistema"),
            "anomalia_elemento": analise.get("anomalia_elemento"),
            "anomalia_descricao":analise.get("anomalia_descricao", ""),
            "anomalia_sintomas": analise.get("anomalia_sintomas"),
            "falha_origem":      analise.get("falha_origem", "Não Aplicável"),
            "falha_descricao":   analise.get("falha_descricao"),
            "falha_evidencias":  analise.get("falha_evidencias"),
            "nexo_causal":       analise.get("nexo_causal"),
            "grau_risco":        analise.get("grau_risco", ""),
            "grau_justificativa":analise.get("grau_justificativa", ""),
            "grau_impacto_seg":  analise.get("grau_impacto_seg"),
            "grau_impacto_amb":  analise.get("grau_impacto_amb"),
            "grau_impacto_pat":  analise.get("grau_impacto_pat"),
            "prazo_intervencao": prazo,
            "acao_recomendada":  analise.get("acao_recomendada", ""),
            "normas_referencias":normas,
            "topicos_banco":     topicos,
            "item_laudo_id":     analise.get("item_laudo_id"),
            "gut_historico_id":  analise.get("gut_historico_id"),
            "G_gut":             analise.get("G_gut"),
            "U_gut":             analise.get("U_gut"),
            "T_gut":             analise.get("T_gut"),
            "prioridade_gut":    analise.get("prioridade_gut"),
            "texto_laudo":       analise.get("texto_laudo"),
            "texto_recomendacao":analise.get("texto_recomendacao"),
            "projeto_id":        analise.get("projeto_id"),
            "status":            analise.get("status", "rascunho"),
            "flags_inconsistencia": flags,
            "timestamp_criacao": now,
            "reclamacao_cliente":       analise.get("reclamacao_cliente", ""),
            "ensaios_realizados":       analise.get("ensaios_realizados", ""),
            "metodologia_inspecao":     analise.get("metodologia_inspecao", ""),
            "normas_descumpridas":      analise.get("normas_descumpridas", ""),
            "explicacao_classificacao": analise.get("explicacao_classificacao", ""),
            "consequencias_risco":      analise.get("consequencias_risco", ""),
        })
        conn.commit()
        lid = cursor.lastrowid
        logger.info("Análise IBAPE salva: %s (id=%d)", codigo, lid)
        return lid
    except sqlite3.Error as exc:
        logger.error("Erro ao salvar análise IBAPE: %s", exc)
        raise


def atualizar_analise(
    conn: sqlite3.Connection,
    analise_id: int,
    campos: dict,
) -> bool:
    """
    Atualiza campos específicos de uma análise existente.
    Registra cada campo alterado em historico_analises_ibape com valor anterior e novo.
    Incrementa o campo 'revisao'.

    Args:
        conn:       Conexão ao analise_ibape.db.
        analise_id: ID da análise a atualizar.
        campos:     dict com apenas os campos a alterar.
    Returns:
        True se atualizado com sucesso, False se análise não encontrada.
    Conforme IBAPE (2025) — rastreabilidade de revisões.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM analises_ibape WHERE id = ?", (analise_id,)
        )
        row = cursor.fetchone()
        if not row:
            logger.warning("atualizar_analise: id=%d não encontrado.", analise_id)
            return False

        revisao_atual = row["revisao"]
        now = datetime.now().isoformat(timespec="seconds")

        for campo, valor_novo in campos.items():
            if campo in ("id", "codigo_analise", "timestamp_criacao", "revisao"):
                continue
            valor_anterior = row[campo] if campo in row.keys() else None
            if valor_anterior == valor_novo:
                continue
            cursor.execute(
                """INSERT INTO historico_analises_ibape
                   (analise_id, revisao, campo_alterado, valor_anterior, valor_novo, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (analise_id, revisao_atual + 1,
                 campo, str(valor_anterior) if valor_anterior is not None else None,
                 str(valor_novo) if valor_novo is not None else None, now),
            )

        # Serializar listas antes de salvar
        for key in ("normas_referencias", "topicos_banco", "flags_inconsistencia"):
            if key in campos and isinstance(campos[key], list):
                campos[key] = json.dumps(campos[key], ensure_ascii=False)

        set_clause = ", ".join(f"{c} = :{c}" for c in campos if c not in
                               ("id", "codigo_analise", "timestamp_criacao", "revisao"))
        if not set_clause:
            conn.commit()
            return True

        params = {**campos, "id": analise_id, "ts": now, "rev": revisao_atual + 1}
        cursor.execute(
            f"UPDATE analises_ibape SET {set_clause}, revisao = :rev, "
            f"timestamp_edicao = :ts WHERE id = :id",
            params,
        )
        conn.commit()
        logger.info("Análise IBAPE id=%d atualizada para revisão %d.", analise_id, revisao_atual + 1)
        return True
    except sqlite3.Error as exc:
        logger.error("Erro ao atualizar análise IBAPE id=%d: %s", analise_id, exc)
        raise


def buscar_analises(
    conn: sqlite3.Connection,
    projeto_id: Optional[int] = None,
    grau_risco: Optional[str] = None,
    anomalia_origem: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict]:
    """
    Busca análises IBAPE com múltiplos critérios opcionais.
    Todos os parâmetros são combinados com AND quando fornecidos.

    Returns:
        Lista de dicts com todos os campos de analises_ibape.
    Conforme IBAPE (2025) — consulta e gestão de análises.
    """
    try:
        filtros, params = [], {}
        if projeto_id is not None:
            filtros.append("projeto_id = :projeto_id")
            params["projeto_id"] = projeto_id
        if grau_risco:
            filtros.append("grau_risco = :grau_risco")
            params["grau_risco"] = grau_risco
        if anomalia_origem:
            filtros.append("anomalia_origem = :anomalia_origem")
            params["anomalia_origem"] = anomalia_origem
        if status:
            filtros.append("status = :status")
            params["status"] = status

        where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM analises_ibape {where} ORDER BY timestamp_criacao DESC",
            params,
        )
        return [dict(r) for r in cursor.fetchall()]
    except sqlite3.Error as exc:
        logger.error("Erro ao buscar análises IBAPE: %s", exc)
        return []


def buscar_topicos_relacionados(
    conn_principal,
    texto_anomalia: str,
    normas: Optional[List[str]] = None,
    limite: int = 5,
) -> List[Dict]:
    """
    Consulta o banco PRINCIPAL (cerebro_pericial.db) via busca textual
    para recuperar trechos de normas relacionados à anomalia descrita.
    Retorna até `limite` resultados mais relevantes.

    Args:
        conn_principal: DatabaseManager do banco principal, ou None.
                        Se None, retorna lista vazia sem erro.
        texto_anomalia: Texto descritivo da anomalia.
        normas:         Lista de siglas de norma para filtro adicional.
        limite:         Número máximo de resultados (padrão 5).
    Returns:
        Lista de dicts com campos: titulo_topico, hierarquia, texto_original,
        nome_arquivo, tipo_fonte, score.
    Conforme IBAPE (2025) — fundamentação normativa da análise.
    """
    if conn_principal is None:
        return []
    try:
        palavras = [p.lower() for p in texto_anomalia.split()
                    if len(p) > 3][:10]
        if normas:
            for n in normas:
                palavras.append(n.lower().replace(" ", ""))

        if hasattr(conn_principal, "busca_textual"):
            resultados = conn_principal.busca_textual(palavras, tipo_fonte=None)
        else:
            return []

        saida = []
        for r in resultados[:limite]:
            saida.append({
                "titulo_topico": r.get("titulo_topico", ""),
                "hierarquia":    r.get("hierarquia", ""),
                "texto_original":r.get("texto_original", ""),
                "nome_arquivo":  r.get("nome_arquivo", ""),
                "tipo_fonte":    r.get("tipo_fonte", ""),
                "score":         r.get("score_textual", 0),
                "id":            r.get("id"),
            })
        return saida
    except Exception as exc:
        logger.warning("buscar_topicos_relacionados: %s", exc)
        return []


def _gerar_codigo_analise(conn: sqlite3.Connection) -> str:
    """Gera código único 'IBAPE-{ANO}-{SEQUENCIAL:04d}'."""
    ano = datetime.now().year
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM analises_ibape WHERE codigo_analise LIKE ?",
        (f"IBAPE-{ano}-%",),
    )
    seq = cursor.fetchone()[0] + 1
    return f"IBAPE-{ano}-{seq:04d}"


def _row_to_dict(row) -> dict:
    """Converte sqlite3.Row ou dict para dict Python com JSON desserializado."""
    d = dict(row) if not isinstance(row, dict) else dict(row)
    for key in ("normas_referencias", "topicos_banco", "flags_inconsistencia"):
        if d.get(key) and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 5 — CLASSE AnaliseIBAPE
# ══════════════════════════════════════════════════════════════════════════════

class AnaliseIBAPE:
    """
    Módulo de Análise Técnica Normatizada IBAPE.
    Implementa os três eixos: 12.1 Anomalia, 12.2 Falha, 12.3 Grau de Risco.

    Conforme IBAPE Nacional (2025) — Diretrizes Técnicas para Perícias Judiciais.
    """

    ANOMALIA_CONFIG = ANOMALIA_CONFIG

    # Config padrão (sobrescrita por config_pericial.yaml quando disponível)
    NEXO_CAUSAL_OBRIGATORIO: bool  = True
    MIN_CHARS_DESCRICAO: int       = 100
    MIN_CHARS_NEXO: int            = 50
    BUSCA_AUTO_NORMAS: bool        = True
    MAX_RESULTADOS_BUSCA: int      = 5
    EXPORTAR_FINALIZADAS_APENAS: bool = False
    PASTA_EXPORTACAO: str          = "exportacoes/"

    def __init__(
        self,
        conn_ibape: sqlite3.Connection,
        conn_principal: Optional[Any] = None,
        projeto_id: Optional[int] = None,
    ) -> None:
        """
        Args:
            conn_ibape:     Conexão ao analise_ibape.db (banco dedicado). Obrigatório.
            conn_principal: DatabaseManager do banco principal (cerebro_pericial.db).
                            Opcional — sem ele, busca de normas fica inativa.
            projeto_id:     ID do projeto pericial ativo (opcional).
        """
        self.conn     = conn_ibape
        self.conn_p   = conn_principal
        self.proj_id  = projeto_id
        self._carregar_config_yaml()

    # ─────────────────────────────────────────────────────────────────────────
    # CONFIG
    # ─────────────────────────────────────────────────────────────────────────

    def _carregar_config_yaml(
        self,
        config_path: str = "config_pericial.yaml",
    ) -> None:
        """Lê config_pericial.yaml e sobrescreve parâmetros do módulo analise_ibape."""
        try:
            import yaml as _yaml
            if not os.path.exists(config_path):
                return
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = _yaml.safe_load(f) or {}
            ai = cfg.get("analise_ibape", {})
            if not ai:
                return
            self.NEXO_CAUSAL_OBRIGATORIO      = bool(ai.get("nexo_causal_obrigatorio",     self.NEXO_CAUSAL_OBRIGATORIO))
            self.MIN_CHARS_DESCRICAO          = int(ai.get("min_chars_descricao",           self.MIN_CHARS_DESCRICAO))
            self.MIN_CHARS_NEXO               = int(ai.get("min_chars_nexo_causal",         self.MIN_CHARS_NEXO))
            self.BUSCA_AUTO_NORMAS            = bool(ai.get("busca_normas_automatica",      self.BUSCA_AUTO_NORMAS))
            self.MAX_RESULTADOS_BUSCA         = int(ai.get("max_resultados_busca",          self.MAX_RESULTADOS_BUSCA))
            self.EXPORTAR_FINALIZADAS_APENAS  = bool(ai.get("exportar_finalizadas_apenas",  self.EXPORTAR_FINALIZADAS_APENAS))
            self.PASTA_EXPORTACAO             = str(ai.get("pasta_exportacao",              self.PASTA_EXPORTACAO))
            logger.debug("Config analise_ibape carregada de '%s'.", config_path)
        except Exception as exc:
            logger.warning("Config YAML analise_ibape: %s — usando padrões.", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # GERAÇÃO DE CÓDIGO
    # ─────────────────────────────────────────────────────────────────────────

    def gerar_codigo_analise(self, conn: Optional[sqlite3.Connection] = None) -> str:
        """
        Gera código único no formato 'IBAPE-{ANO}-{SEQUENCIAL:04d}'.
        Ex: IBAPE-2025-0001, IBAPE-2025-0002, ...
        Conforme IBAPE (2025) — identificação e rastreabilidade de análises.
        """
        return _gerar_codigo_analise(conn or self.conn)

    # ─────────────────────────────────────────────────────────────────────────
    # VERIFICAÇÕES DE CONSISTÊNCIA (Seção 4.2 Fase 4)
    # ─────────────────────────────────────────────────────────────────────────

    def verificar_consistencia_ibape(self, analise: dict) -> List[str]:
        """
        Aplica as 5 regras de consistência da Seção 4.2 Fase 4.
        Retorna lista de strings com alertas.
        Itens com prefixo 'BLOQUEIO:' impedem o salvamento.

        Regras:
          R1 — Anomalia Exógena + falha de manutenção
          R2 — Anomalia Funcional sem falha (Não Aplicável)
          R3 — Grau Crítico com GUT < 200
          R4 — Anomalia Endógena sem nexo causal (BLOQUEIO)
          R5 — Descrição da anomalia muito curta

        Conforme IBAPE (2025) — consistência e qualidade do laudo pericial.
        """
        alertas: List[str] = []

        origem  = analise.get("anomalia_origem", "")
        falha   = analise.get("falha_origem", "")
        grau    = analise.get("grau_risco", "")
        nexo    = (analise.get("nexo_causal") or "").strip()
        descr   = (analise.get("anomalia_descricao") or "").strip()
        gut_p   = analise.get("prioridade_gut")

        # R1 — Exógena + falha de manutenção
        if origem == "Exógena" and falha not in ("Não Aplicável", "", None):
            alertas.append(
                "⚠️  R1 — Anomalia exógena não tem relação com falha de manutenção. "
                "Revisar classificação da falha (deveria ser 'Não Aplicável')."
            )

        # R2 — Funcional sem falha
        if origem == "Funcional" and falha in ("Não Aplicável", "", None):
            alertas.append(
                "⚠️  R2 — Anomalia funcional geralmente está associada a falha de "
                "manutenção ou uso. Confirmar classificação 'Não Aplicável'?"
            )

        # R3 — Grau Crítico com GUT baixo
        if grau == "Crítico" and gut_p is not None:
            try:
                if int(gut_p) < 200:
                    alertas.append(
                        f"⚠️  R3 — Grau Crítico mas GUT indica prioridade baixa "
                        f"(GUT={gut_p}). Verificar consistência entre as avaliações."
                    )
            except (TypeError, ValueError):
                pass

        # R4 — Endógena sem nexo causal (BLOQUEIO)
        if origem == "Endógena" and (not nexo or len(nexo) < self.MIN_CHARS_NEXO):
            alertas.append(
                "BLOQUEIO: R4 — Nexo causal é obrigatório para anomalias endógenas "
                f"em laudos judiciais (mínimo {self.MIN_CHARS_NEXO} caracteres). "
                "Preencha o campo Nexo Causal antes de salvar."
            )

        # R5 — Descrição muito curta
        if len(descr) < self.MIN_CHARS_DESCRICAO:
            alertas.append(
                f"⚠️  R5 — Descrição técnica muito curta ({len(descr)} chars). "
                f"Recomendado mínimo de {self.MIN_CHARS_DESCRICAO} caracteres para um laudo técnico."
            )

        return alertas

    # ─────────────────────────────────────────────────────────────────────────
    # FORMATAÇÃO DO TEXTO PARA LAUDO
    # ─────────────────────────────────────────────────────────────────────────

    def formatar_texto_laudo(self, analise: dict) -> str:
        """
        Gera bloco de texto estruturado com os 3 eixos IBAPE,
        pronto para inserção no laudo judicial.
        Contém obrigatoriamente os cabeçalhos:
          '12.1 ANOMALIA', '12.2 FALHA', '12.3 GRAU DE RISCO'

        Conforme IBAPE (2025), itens 12.1, 12.2 e 12.3.
        """
        if isinstance(analise, sqlite3.Row):
            analise = _row_to_dict(analise)

        codigo = analise.get("codigo_analise", "—")
        titulo = analise.get("titulo", "")
        data   = analise.get("data_vistoria", "") or ""
        sep    = "═" * 54

        grau   = analise.get("grau_risco", "")
        emoji  = GRAU_RISCO_CONFIG.get(grau, {}).get("emoji", "")
        normas = analise.get("normas_referencias") or []
        if isinstance(normas, str):
            try:
                normas = json.loads(normas)
            except Exception:
                normas = [normas]
        normas_str = ", ".join(normas) if normas else "—"

        gut_str = ""
        g, u, t, p = (analise.get(k) for k in ("G_gut", "U_gut", "T_gut", "prioridade_gut"))
        if any(v is not None for v in (g, u, t)):
            gut_str = f"\nGUT vinculado: G:{g} U:{u} T:{t} = Prioridade {p}"

        falha_bloco = ""
        if analise.get("falha_origem") not in ("Não Aplicável", "", None):
            falha_bloco = (
                f"\nClassificação: {analise.get('falha_origem', '—')}\n\n"
                f"{analise.get('falha_descricao') or ''}"
            )
        else:
            falha_bloco = f"\nClassificação: {analise.get('falha_origem', '—')}"

        texto = (
            f"\n{sep}\n"
            f"ANÁLISE TÉCNICA — {codigo}\n"
            f"{titulo}\n"
            f"Data da vistoria: {data}\n"
            f"{sep}\n\n"
            f"12.1 ANOMALIA\n"
            f"Origem: {analise.get('anomalia_origem', '—')} — "
            f"{analise.get('anomalia_natureza', '—')}\n"
            f"Sistema/Elemento: {analise.get('anomalia_sistema', '—')} — "
            f"{analise.get('anomalia_elemento', '—')}\n\n"
            f"Sintomas observados:\n"
            f"{analise.get('anomalia_sintomas') or '—'}\n\n"
            f"Descrição técnica:\n"
            f"{analise.get('anomalia_descricao', '—')}\n\n"
            f"12.2 FALHA\n"
            f"{falha_bloco}\n\n"
            f"Nexo Causal:\n"
            f"{analise.get('nexo_causal') or '—'}\n\n"
            f"12.3 GRAU DE RISCO\n"
            f"Classificação: {emoji} {grau}\n\n"
            f"Justificativa:\n"
            f"{analise.get('grau_justificativa', '—')}\n\n"
            f"Ação recomendada: {analise.get('acao_recomendada', '—')}\n"
            f"Prazo: {analise.get('prazo_intervencao', '—')}\n\n"
            f"Referências normativas: {normas_str}"
            f"{gut_str}\n"
            f"{sep}\n"
        )
        return texto

    # ─────────────────────────────────────────────────────────────────────────
    # MENU PRINCIPAL
    # ─────────────────────────────────────────────────────────────────────────

    def executar(self, pre_dados: Optional[dict] = None) -> None:
        """
        Método principal — exibe menu e orquestra todos os fluxos do módulo.
        Quando chamado com pre_dados (do fluxo analise_img), abre diretamente
        o fluxo de nova análise com os campos pré-preenchidos e retorna
        imediatamente após salvar, sem exibir o menu de revisão.
        Conforme Seção 4.1 do prompt de implementação.
        """
        if pre_dados:
            print("\n  ℹ️  Abrindo análise IBAPE com dados do GUT pré-carregados.")
            print("     Revise e complemente os campos conforme necessário.\n")
            result = self._fluxo_nova_analise(prefill=pre_dados)
            if result is not None:
                print("\n  ✅ Análise IBAPE salva. Retornando ao fluxo de análise da imagem.")
            else:
                print("\n  ⚠️  Análise IBAPE não salva (cancelada ou com bloqueio).")
            return

        while True:
            self._exibir_menu()
            op = input("\n  Escolha [0-9]: ").strip().upper()

            # Aceita número OU letra para cada opção
            if op in ("0",):
                break
            elif op in ("1", "N"):
                self._fluxo_nova_analise()
            elif op in ("2", "I"):
                self._fluxo_importar_item_laudo()
            elif op in ("3", "L"):
                self._fluxo_listar_com_selecao()
            elif op in ("4", "V"):
                self._fluxo_visualizar()
            elif op in ("5", "E"):
                self._fluxo_editar()
            elif op in ("6", "F"):
                self._fluxo_finalizar()
            elif op in ("7", "X"):
                self._fluxo_exportar()
            elif op in ("8", "B"):
                self._fluxo_buscar_normas()
            elif op in ("9", "D"):
                self._fluxo_deletar()
            else:
                print("  Opcao invalida. Digite um numero de 0 a 9.")

    # ─────────────────────────────────────────────────────────────────────────
    # EXIBIÇÃO DO MENU
    # ─────────────────────────────────────────────────────────────────────────

    def _exibir_menu(self) -> None:
        """Exibe menu principal com opcoes numeradas para uso mais simples."""
        analises = buscar_analises(self.conn, projeto_id=self.proj_id)
        n_total  = len(analises)
        n_fin    = sum(1 for a in analises if a.get("status") == "finalizado")
        n_ras    = n_total - n_fin
        sep = "=" * 65
        print("\n" + sep)
        print("  ANALISE IBAPE — DESCRICAO TECNICA DE ANOMALIAS")
        print("  Ref: IBAPE (2025) | NBR 13752:2024 | NBR 16747:2020")
        print(f"  Total: {n_total} analise(s)  |  Rascunhos: {n_ras}  |  Finalizadas: {n_fin}")
        print(sep)
        print("  [1] Nova analise              [2] Importar do laudo/GUT")
        print("  [3] Listar e selecionar       [4] Visualizar analise")
        print("  [5] Editar analise            [6] Finalizar analise")
        print("  [7] Exportar (Word/Excel/TXT) [8] Buscar normas no banco")
        print("  [9] Excluir analise           [0] Voltar")
        print(sep)

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS DE INPUT
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _input_texto(
        prompt: str,
        obrigatorio: bool = True,
        max_chars: int = 5000,
        multilinhas: bool = False,
        default: str = "",
        pre_preenchido: str = "",
    ) -> str:
        """
        Coleta texto do usuário com validação de comprimento.
        Suporta entrada multilinha (termine com linha vazia).
        """
        if pre_preenchido:
            print(f"  (Pré-preenchido: {pre_preenchido[:60]}{'...' if len(pre_preenchido)>60 else ''})")
            resp = input(f"  {prompt}[ENTER para manter] > ").strip()
            return resp if resp else pre_preenchido

        if multilinhas:
            print(f"  {prompt}")
            print("  (Digite o texto. Linha vazia para finalizar.)")
            linhas = []
            while True:
                linha = input("  > ")
                if linha == "" and linhas:
                    break
                linhas.append(linha)
            texto = "\n".join(linhas).strip()
        else:
            if default:
                texto = input(f"  {prompt}[{default}] > ").strip() or default
            else:
                texto = input(f"  {prompt}").strip()

        if len(texto) > max_chars:
            texto = texto[:max_chars]
            print(f"  ⚠️  Texto truncado para {max_chars} caracteres.")

        if obrigatorio and not texto:
            print("  ⚠️  Campo obrigatório.")
            return AnaliseIBAPE._input_texto(
                prompt, obrigatorio, max_chars, multilinhas, default
            )
        return texto

    @staticmethod
    def _escolher_opcao(opcoes: List[str], prompt: str = "Escolha: ") -> Optional[str]:
        """Apresenta lista numerada e retorna o item escolhido."""
        for i, op in enumerate(opcoes, 1):
            print(f"    [{i}] {op}")
        while True:
            resp = input(f"  {prompt}").strip()
            if resp.isdigit() and 1 <= int(resp) <= len(opcoes):
                return opcoes[int(resp) - 1]
            if not resp:
                return None
            print(f"  ⚠️  Digite um número de 1 a {len(opcoes)}.")

    # ─────────────────────────────────────────────────────────────────────────
    # FLUXO [N] — NOVA ANÁLISE
    # ─────────────────────────────────────────────────────────────────────────

    def _fluxo_nova_analise(
        self,
        prefill: Optional[dict] = None,
    ) -> Optional[int]:
        """
        Fluxo completo de coleta de uma nova análise IBAPE.
        Fases 0-5 conforme Seção 4.2.
        Retorna o ID salvo ou None se cancelado.
        """
        pf = prefill or {}
        analise: Dict[str, Any] = {"projeto_id": self.proj_id}
        normas_auto: List[dict] = []

        print("\n" + "═" * 65)
        print("  📐 NOVA ANÁLISE IBAPE — Seção 12 (IBAPE 2025)")
        print("  (Digite CANCELAR em qualquer campo para abortar)")
        print("═" * 65)

        # ── FASE 0 — IDENTIFICAÇÃO ─────────────────────────────────────────
        print("\n  ── FASE 0 — IDENTIFICAÇÃO ──")
        titulo = self._input_texto(
            "Título da análise (ex: Fissuras em laje do 3º pavimento): ",
            max_chars=200, pre_preenchido=pf.get("titulo", ""),
        )
        if titulo.upper() == "CANCELAR":
            return None
        analise["titulo"] = titulo

        hoje = date.today().strftime("%d/%m/%Y")
        dv = input(f"  Data da vistoria [ENTER = hoje ({hoje})]: ").strip() or hoje
        analise["data_vistoria"] = dv

        if pf.get("item_laudo_id"):
            analise["item_laudo_id"] = pf["item_laudo_id"]
            print(f"  📎 Importado do Item #{pf['item_laudo_id']}")

        if pf.get("G_gut"):
            analise.update({
                "G_gut": pf.get("G_gut"), "U_gut": pf.get("U_gut"),
                "T_gut": pf.get("T_gut"), "prioridade_gut": pf.get("prioridade_gut"),
                "gut_historico_id": pf.get("gut_historico_id"),
            })

        # ── FASE 1 — ANOMALIA (12.1) ──────────────────────────────────────
        print("\n  ── FASE 1 — ANOMALIA (Item 12.1 IBAPE) ──")
        print(f"\n  DEFINIÇÃO:\n  {ANOMALIA_DEFINICAO[:200]}...\n")
        origem = self._coletar_origem_anomalia(prefill=pf.get("anomalia_origem"))
        if not origem:
            return None
        analise["anomalia_origem"] = origem

        cfg_o = ANOMALIA_CONFIG[origem]

        # Natureza
        if len(cfg_o.get("naturezas_opcoes", [])) == 1:
            analise["anomalia_natureza"] = cfg_o["naturezas_opcoes"][0]
            print(f"\n  Natureza classificada automaticamente: {analise['anomalia_natureza']}")
        elif cfg_o.get("natureza_default") and not cfg_o.get("naturezas_opcoes"):
            analise["anomalia_natureza"] = cfg_o["natureza_default"]
        else:
            print(f"\n  Natureza da anomalia ({origem}):")
            nat = self._escolher_opcao(cfg_o.get("naturezas_opcoes", []))
            analise["anomalia_natureza"] = nat or cfg_o.get("natureza_default", "A Classificar")

        # Sistema
        sistema = self._coletar_sistema(prefill=pf.get("anomalia_sistema"))
        analise["anomalia_sistema"] = sistema

        # Elemento
        elemento = self._input_texto(
            "Elemento construtivo específico\n"
            "  (ex: 'Laje de cobertura do 3º pavimento'): ",
            obrigatorio=False, max_chars=200,
            pre_preenchido=pf.get("anomalia_elemento", ""),
        )
        analise["anomalia_elemento"] = elemento

        # Sintomas
        print("\n  Campo 8 — Sintomas observados em vistoria:")
        print("  ex: 'Fissuras mapeadas de 0,3 a 0,8 mm, ativas, com pó de concreto nas bordas'")
        if pf.get("anomalia_sintomas"):
            print(f"  Referência (análise visual): {pf['anomalia_sintomas'][:150]}")
        sintomas = self._input_texto("", obrigatorio=False, max_chars=2000, multilinhas=True)
        analise["anomalia_sintomas"] = sintomas

        print("\n  Campo 8.1 — Ensaios e metodologia de inspeção [ENTER para pular]")
        print("  ex: 'Inspeção visual com nível de bolha, percussão e medidor de umidade'")
        ensaios = self._input_texto("  Ensaios realizados: ", obrigatorio=False, max_chars=1000)
        analise["ensaios_realizados"] = ensaios

        print("\n  Campo 8.2 — Resultados da inspeção / metodologia [ENTER para pular]")
        print("  ex: 'Constatou-se caimento insuficiente. Medição indicou 0,2% em vez de 1% mínimo.'")
        metod = self._input_texto("", obrigatorio=False, max_chars=2000, multilinhas=True)
        analise["metodologia_inspecao"] = metod

        # Descrição técnica
        print(f"\n  Campo 9 — Descrição técnica fundamentada da anomalia")
        print("  (texto para inserção no laudo — mínimo 3 linhas)")
        if pf.get("anomalia_descricao"):
            print(f"  Referência (análise visual): {pf['anomalia_descricao'][:200]}")
        descricao = self._input_texto("", obrigatorio=True, max_chars=5000, multilinhas=True)
        print(f"  ({len(descricao)}/5000 caracteres)")
        analise["anomalia_descricao"] = descricao

        print("\n  Campo 9.1 — Reclamação do solicitante [ENTER para pular]")
        print("  ex: 'Proprietário relata infiltração na sala após chuvas intensas'")
        reclam = self._input_texto("  Reclamação: ", obrigatorio=False, max_chars=1000)
        analise["reclamacao_cliente"] = reclam

        # Busca automática de normas — usa descrição + sintomas como texto de consulta
        _texto_busca = descricao if len(descricao) >= 25 else f"{sintomas} {descricao}".strip()
        if self.BUSCA_AUTO_NORMAS and self.conn_p and len(_texto_busca) >= 25:
            print("\n  🔍 Buscando normas relacionadas no banco...")
            normas_auto = buscar_topicos_relacionados(
                self.conn_p, _texto_busca, limite=self.MAX_RESULTADOS_BUSCA
            )
            if normas_auto:
                print(f"  ✅ {len(normas_auto)} trecho(s) encontrado(s) — serão exibidos na Fase 3.")
            else:
                print("  📭 Nenhum trecho encontrado no banco para este tema.")

        # ── FASE 2 — FALHA (12.2) ─────────────────────────────────────────
        print("\n  ── FASE 2 — FALHA (Item 12.2 IBAPE) ──")
        falha_origem, falha_desc = self._coletar_falha(origem, prefill=pf.get("falha_origem"))
        analise["falha_origem"]    = falha_origem
        analise["falha_descricao"] = falha_desc

        # Nexo causal
        print("\n  Campo 12 — Nexo Causal")
        print("  O nexo causal deve responder:")
        print("    • O QUÊ causou a anomalia?")
        print("    • COMO o mecanismo de degradação se desenvolveu?")
        print("    • QUAL a relação entre causa e efeito observado?")
        print("  Referência: NBR 13752:2024, item 7.3.3.5.3")
        nexo = self._input_texto("", obrigatorio=True, max_chars=3000, multilinhas=True,
                                 pre_preenchido=pf.get("nexo_causal", ""))
        analise["nexo_causal"] = nexo

        print("\n  Campo 12.1 — Explicação da classificação de anomalia [ENTER para pular]")
        print("  ex: 'Classificada como funcional pois decorre de ausência de manutenção preventiva'")
        expl = self._input_texto("", obrigatorio=False, max_chars=1000, multilinhas=True)
        analise["explicacao_classificacao"] = expl

        print("\n  Campo 12.2 — Normas descumpridas [ENTER para pular]")
        print("  ex: 'NBR 5674 — manutenção de edificações; NBR 15575-4 — estanqueidade'")
        ndesc = self._input_texto("  Normas descumpridas: ", obrigatorio=False, max_chars=500)
        analise["normas_descumpridas"] = ndesc

        # ── FASE 2.5 — GUT VINCULADO (Pedidos 04 e 05) ──────────────────
        print("\n  -- FASE 2.5 — GUT (Gravidade, Urgência, Tendência) --")
        gut_data = self._coletar_gut_vinculado(pf)
        if gut_data:
            analise.update(gut_data)

        # ── FASE 3 — GRAU DE RISCO (12.3) ────────────────────────────────
        print("\n  ── FASE 3 — GRAU DE RISCO (Item 12.3 IBAPE) ──")

        if normas_auto:
            print("\n  🔍 Normas encontradas no banco relacionadas à anomalia:")
            ids_todos = []
            for i, r in enumerate(normas_auto, 1):
                trecho = (r.get("texto_original") or "")[:100]
                print(f"  [{i}] {r.get('hierarquia','—')} — {trecho}... [{r.get('nome_arquivo','')}]")
                ids_todos.append(r.get("id"))
            print("\n  Quais deseja referenciar na análise?")
            print("  [T] Todos  |  [N] Nenhum  |  Números separados por vírgula (ex: 1,3)")
            resp_ref = input("  > ").strip().upper()
            ids_topicos = []
            if resp_ref in ("T", "S"):
                ids_topicos = [i for i in ids_todos if i]
            elif resp_ref not in ("N", ""):
                for parte in resp_ref.replace(" ", "").split(","):
                    if parte.isdigit():
                        idx = int(parte) - 1
                        if 0 <= idx < len(ids_todos) and ids_todos[idx]:
                            ids_topicos.append(ids_todos[idx])
            if ids_topicos:
                analise["topicos_banco"] = ids_topicos

        grau = self._coletar_grau_risco(prefill=pf.get("grau_risco"))
        analise["grau_risco"] = grau

        print("\n  Campo 14 — Justificativa técnica do grau de risco")
        print("  Abordar obrigatoriamente os 3 eixos:")
        print("    • Segurança dos usuários | • Preservação ambiental | • Integridade do patrimônio")
        if pf.get("grau_justificativa"):
            print(f"  Referência (GUT): {pf['grau_justificativa'][:200]}")
        justif = self._input_texto("", obrigatorio=True, max_chars=2000, multilinhas=True,
                                   pre_preenchido=pf.get("grau_justificativa", ""))
        analise["grau_justificativa"] = justif

        acao = self._input_texto(
            "Ação técnica recomendada (com prazo e responsável): ",
            obrigatorio=True, max_chars=1000,
            pre_preenchido=pf.get("acao_recomendada", ""),
        )
        analise["acao_recomendada"] = acao

        print("\n  Campo 14.1 — Consequências sem intervenção [ENTER para pular]")
        print("  ex: 'Deterioração progressiva da alvenaria, manchas e mofo no interior'")
        conseq = self._input_texto("", obrigatorio=False, max_chars=1000, multilinhas=True)
        analise["consequencias_risco"] = conseq

        # Normas de referência
        sugestao = ", ".join(r.get("nome_arquivo", "") for r in normas_auto[:3]) if normas_auto else ""
        print(f"\n  Normas técnicas aplicáveis (separar por vírgula):")
        if sugestao:
            print(f"  Sugeridas pelo banco: {sugestao}")
        normas_str = input("  > ").strip()
        if normas_str:
            analise["normas_referencias"] = [n.strip() for n in normas_str.split(",") if n.strip()]

        # ── FASE 4 — CONSISTÊNCIA ─────────────────────────────────────────
        alertas = self.verificar_consistencia_ibape(analise)
        tem_bloqueio = any(a.startswith("BLOQUEIO:") for a in alertas)

        # ── FASE 5 — PREVIEW E CONFIRMAÇÃO ───────────────────────────────
        self._exibir_preview(analise, alertas)

        if tem_bloqueio:
            print("\n  ❌ Existem BLOQUEIOS que impedem o salvamento. Corrija e tente novamente.")
            corrigir = input("  Deseja editar o nexo causal agora? [S/N]: ").strip().upper()
            if corrigir == "S":
                print("\n  Novo nexo causal:")
                analise["nexo_causal"] = self._input_texto(
                    "", obrigatorio=True, max_chars=3000, multilinhas=True
                )
                alertas = self.verificar_consistencia_ibape(analise)
                tem_bloqueio = any(a.startswith("BLOQUEIO:") for a in alertas)
                if tem_bloqueio:
                    print("  ❌ Bloqueio persiste. Análise não salva.")
                    return None
            else:
                return None

        analise["flags_inconsistencia"] = alertas
        analise["texto_laudo"]          = self.formatar_texto_laudo(analise)

        while True:
            resp = input("\n  [1] Salvar rascunho  [2] Salvar finalizada  [0] Cancelar: ").strip()
            if resp == "0":
                return None
            elif resp in ("1", "2"):
                analise["status"] = "finalizado" if resp == "2" else "rascunho"
                lid = salvar_analise(self.conn, analise)
                st  = "FINALIZADA" if resp == "2" else "RASCUNHO"
                codigo = self.conn.execute(
                    "SELECT codigo_analise FROM analises_ibape WHERE id=?", (lid,)
                ).fetchone()[0]
                print(f"\n  Analise salva como {st}: {codigo} (id={lid})")
                exp = input("  Exportar agora em Word (DOCX)? [1=Sim / 2=Nao]: ").strip()
                if exp == "1":
                    row = self.conn.execute(
                        "SELECT * FROM analises_ibape WHERE id=?", (lid,)
                    ).fetchone()
                    if row:
                        self._exportar_docx_analise(_row_to_dict(row))
                return lid
            else:
                print("  Opcao invalida.")

    # ─────────────────────────────────────────────────────────────────────────
    # COLETA DE CAMPOS ESPECÍFICOS
    # ─────────────────────────────────────────────────────────────────────────

    def _coletar_origem_anomalia(self, prefill: Optional[str] = None) -> Optional[str]:
        """Exibe as 4 classificações de anomalia com definição e exemplos.
        Quando há prefill (do fluxo analise_img), confirma antes de exibir o menu."""
        dados = [
            ("1", "ENDÓGENA",  "Falha de projeto, materiais ou execução",
             "Natureza: Vício Construtivo",
             "cobrimento insuficiente, argamassa mal dosada"),
            ("2", "EXÓGENA",   "Ação de terceiros ou agente externo",
             "Natureza: Avaria",
             "perfuração por terceiro, impacto de veículo"),
            ("3", "NATURAL",   "Fenômeno ambiental não previsto",
             "Natureza: Avaria ou Decrepitude",
             "sismo, chuva excepcional, variação térmica extrema"),
            ("4", "FUNCIONAL", "Desgaste, envelhecimento ou falha de uso",
             "Natureza: Decrepitude ou Deterioração",
             "telhado com VU esgotada, falta de manutenção"),
        ]
        mapa = {str(i): d[1].title() for i, d in enumerate(dados, 1)}
        mapa.update({"ENDOGENA": "Endógena", "EXOGENA": "Exógena",
                     "NATURAL": "Natural", "FUNCIONAL": "Funcional"})

        if prefill:
            print(f"\n  CLASSIFICAÇÃO DA ANOMALIA — Item 12.1 IBAPE")
            print(f"  (Pré-preenchido pelo GUT: {prefill})")
            resp = input("  ENTER para confirmar | [1-4] para alterar: ").strip().upper()
            if not resp:
                return prefill
            if resp in ("1", "2", "3", "4"):
                return mapa[resp]
            if resp == "CANCELAR":
                return None
            return prefill

        print("\n  CLASSIFICAÇÃO DA ANOMALIA — Item 12.1 IBAPE")
        print("  " + "─" * 60)
        for num, nome, defin, nat, ex in dados:
            print(f"\n  [{num}] {nome} — {defin}")
            print(f"       {nat}")
            print(f"       ex: {ex}")

        while True:
            resp = input("\n  Origem da anomalia [1-4]: ").strip().upper()
            if resp in ("1", "2", "3", "4"):
                return mapa[resp]
            if resp == "CANCELAR":
                return None
            print("  ⚠️  Digite 1, 2, 3 ou 4.")

    def _coletar_sistema(self, prefill: Optional[str] = None) -> str:
        """Coleta o sistema construtivo afetado."""
        sistemas = [
            "Estrutural", "Acabamento/Revestimento", "Hidrossanitário",
            "Cobertura", "Elétrico/SPDA", "Impermeabilização",
            "Esquadrias/Fachada", "Outro/Não especificado",
        ]
        print("\n  Sistema construtivo afetado:")
        if prefill:
            print(f"  (Pré-preenchido: {prefill})")
            resp = input("  ENTER para manter ou novo número [1-8]: ").strip()
            if not resp:
                return prefill
            if resp.isdigit() and 1 <= int(resp) <= len(sistemas):
                return sistemas[int(resp) - 1]
        for i, s in enumerate(sistemas, 1):
            print(f"  [{i}] {s}")
        resp = input("  [1-8]: ").strip()
        if resp.isdigit() and 1 <= int(resp) <= len(sistemas):
            return sistemas[int(resp) - 1]
        return prefill or "Outro/Não especificado"

    def _coletar_falha(
        self,
        anomalia_origem: str,
        prefill: Optional[str] = None,
    ) -> tuple:
        """
        Coleta origem e descrição da falha conforme lógica filtrada
        pela origem da anomalia. Retorna (falha_origem, falha_descricao).
        """
        print("\n  Campo 10 — Classificação da Falha (Item 12.2 IBAPE)")

        if anomalia_origem == "Exógena":
            print("\n  ℹ️  Anomalia exógena — falha de manutenção não se aplica.")
            print("     Origem em agente terceiro externo.")
            return "Não Aplicável", None

        if anomalia_origem in ("Endógena", "Natural"):
            print(f"\n  A anomalia {anomalia_origem.lower()} foi agravada por falha de manutenção?")
            r = input("  [S] Sim | [N] Não: ").strip().upper()
            if r != "S":
                return "Não Aplicável", None

        # Funcional (obrigatória) ou escolha livre
        print("\n  Classificação da falha de manutenção:")
        categorias = ["Planejamento", "Execução", "Operacional", "Gerencial"]
        for i, cat in enumerate(categorias, 1):
            cfg = FALHA_CONFIG[cat]
            print(f"\n  [{i}] {cat.upper()} — {cfg['descricao'][:60]}...")
            print(f"       ex: {cfg['exemplos'][0]}")

        if prefill and prefill in categorias:
            print(f"\n  (Pré-preenchido: {prefill})")
            resp = input("  ENTER para manter ou novo número [1-4]: ").strip()
            falha_origem = prefill if not resp else (
                categorias[int(resp) - 1] if resp.isdigit() and 1 <= int(resp) <= 4 else prefill
            )
        else:
            while True:
                resp = input("\n  Origem da falha [1-4]: ").strip()
                if resp.isdigit() and 1 <= int(resp) <= 4:
                    falha_origem = categorias[int(resp) - 1]
                    break
                print("  ⚠️  Digite 1, 2, 3 ou 4.")

        # Exibir perguntas diagnósticas
        print(f"\n  Perguntas diagnósticas para {falha_origem}:")
        for q in FALHA_CONFIG[falha_origem]["perguntas"]:
            print(f"    ▸ {q}")

        print("\n  Campo 11 — Descrição da falha identificada:")
        print("  (como foi determinada, evidências encontradas)")
        falha_desc = self._input_texto("", obrigatorio=False, max_chars=3000, multilinhas=True)
        return falha_origem, falha_desc

    def _coletar_grau_risco(self, prefill: Optional[str] = None) -> str:
        """
        Exibe critérios completos de cada nível de risco e coleta escolha.

        Comportamento com prefill (vindo do GUT via analise_img):
          — exibe apenas o grau pré-selecionado e aguarda ENTER para confirmar
          — o menu completo NÃO é exibido, para não reperguntar o que o GUT já definiu
          — o perito pode digitar [1-3] para alterar se desejar

        Comportamento sem prefill (uso direto via [analise_ibape]):
          — exibe o menu completo como antes (sem alteração)
        """
        ordem = ["Crítico", "Médio", "Mínimo"]

        # ── Com prefill: confirmar sem exibir menu completo ────────────────
        if prefill and prefill in ordem:
            cfg   = GRAU_RISCO_CONFIG.get(prefill, {})
            emoji = cfg.get("emoji", "")
            prazo = cfg.get("prazo", "")
            print(f"\n  GRAU DE RISCO — Item 12.3 IBAPE / NBR 16747:2020")
            print(f"  (Classificação GUT: {emoji} {prefill.upper()} — Prazo: {prazo})")
            resp = input("  ENTER para confirmar | [1-3] para alterar: ").strip()
            if not resp:
                return prefill
            if resp.isdigit() and 1 <= int(resp) <= 3:
                return ordem[int(resp) - 1]
            return prefill

        # ── Sem prefill: menu completo (comportamento original) ────────────
        print("\n  GRAU DE RISCO — Item 12.3 IBAPE / NBR 16747:2020")
        print("  " + "─" * 60)
        for i, grau in enumerate(ordem, 1):
            cfg = GRAU_RISCO_CONFIG[grau]
            print(f"\n  [{i}] {cfg['emoji']} {grau.upper()}")
            for c in cfg["criterios"]:
                print(f"       - {c}")
            print(f"       Prazo: {cfg['prazo']}")
        while True:
            resp = input("\n  Grau de risco [1-3]: ").strip()
            if resp.isdigit() and 1 <= int(resp) <= 3:
                return ordem[int(resp) - 1]
            print("  Digite 1, 2 ou 3.")

    def _coletar_gut_vinculado(self, pf: dict) -> dict:
        """
        Pedidos 04 e 05: Busca ou coleta dados GUT (G, U, T) para vincular à análise.
        Fluxo:
          1. Se já tem dados GUT no prefill (importado de item_laudo), usa diretamente.
          2. Oferece buscar em gut_historico (banco principal).
          3. Ou preencher manualmente G, U, T (escala 1-10).
          4. Ou pular (análise sem GUT vinculado).
        """
        # Já tem GUT do prefill (importado)
        if pf.get("G_gut") and pf.get("U_gut") and pf.get("T_gut"):
            g, u, t = pf["G_gut"], pf["U_gut"], pf["T_gut"]
            p = pf.get("prioridade_gut") or g * u * t
            print(f"\n  GUT importado: G={g}  U={u}  T={t}  Prioridade={p}")
            conf = input("  Confirmar estes valores? [ENTER/S=Sim | 2=Alterar | 3=Pular]: ").strip().upper()
            if conf in ("1", "S", "SIM", ""):
                return {"G_gut": g, "U_gut": u, "T_gut": t, "prioridade_gut": p,
                        "gut_historico_id": pf.get("gut_historico_id")}
            elif conf == "3":
                return {}
            # Cai para coleta manual abaixo

        print("\n  Vincular avaliacao GUT a esta analise?")
        print("  [1] Buscar avaliacao existente no banco GUT Adaptativo")
        print("  [2] Inserir G, U, T manualmente")
        print("  [3] Pular (analise sem GUT vinculado)")
        op = input("  Escolha [1/2/3]: ").strip()

        if op == "1":
            return self._buscar_gut_historico()
        elif op == "2":
            return self._inserir_gut_manual()
        else:
            return {}

    def _buscar_gut_historico(self) -> dict:
        """Busca avaliações GUT no banco principal (tabela gut_historico)."""
        if self.conn_p is None:
            print("  Banco principal nao conectado. Use opcao 2 para inserir manualmente.")
            return self._inserir_gut_manual()
        try:
            conn_raw = self.conn_p.get_connection()
            cursor   = conn_raw.cursor()
            # Tenta gut_historico primeiro (GUT Adaptativo), depois gut_adaptativo
            try:
                cursor.execute("""
                    SELECT id, descricao, subsistema, G_final, U_final, T_final,
                           prioridade_gut, risco_gut, timestamp
                    FROM gut_historico
                    WHERE aceito_perito = 1
                    ORDER BY timestamp DESC LIMIT 20
                """)
                rows = cursor.fetchall()
                tabela = "gut_historico"
            except Exception:
                rows = []
                tabela = None
            conn_raw.close()
        except Exception as exc:
            print(f"  Nao foi possivel acessar o banco GUT: {exc}")
            return self._inserir_gut_manual()

        if not rows:
            print("  Nenhuma avaliacao GUT encontrada. Preencha manualmente:")
            return self._inserir_gut_manual()

        print(f"\n  Avaliacoes GUT disponiveis ({tabela}):")
        print(f"  {'ID':<6} {'G':<4} {'U':<4} {'T':<4} {'Prio':<6} {'Risco':<10} {'Descricao'}")
        print("  " + "─" * 72)
        for r in rows:
            desc = str(r[1] or "")[:35]
            print(f"  {r[0]:<6} {(r[3] or '?'):<4} {(r[4] or '?'):<4} {(r[5] or '?'):<4} "
                  f"{(r[6] or '?'):<6} {(r[7] or '?'):<10} {desc}")

        try:
            gid = int(input("\n  ID da avaliacao GUT para vincular (0=manual): ").strip())
        except ValueError:
            return {}

        if gid == 0:
            return self._inserir_gut_manual()

        item = next((r for r in rows if r[0] == gid), None)
        if not item:
            print(f"  ID {gid} nao encontrado.")
            return self._inserir_gut_manual()

        g, u, t = item[3] or 5, item[4] or 5, item[5] or 5
        p = item[6] or g * u * t
        print(f"\n  GUT selecionado: G={g}  U={u}  T={t}  Prioridade={p}  Risco={item[7]}")
        return {
            "G_gut": g, "U_gut": u, "T_gut": t,
            "prioridade_gut": p, "gut_historico_id": item[0],
        }

    def _inserir_gut_manual(self) -> dict:
        """Coleta G, U, T manualmente (escala 1-10)."""
        print("\n  Insira os valores GUT (escala 1-10 cada):")
        print("  G = Gravidade (impacto/severidade do dano)")
        print("  U = Urgencia  (velocidade de agravamento)")
        print("  T = Tendencia (probabilidade de piora)")
        try:
            g = int(input("  G [1-10]: ").strip())
            u = int(input("  U [1-10]: ").strip())
            t = int(input("  T [1-10]: ").strip())
            g = max(1, min(10, g))
            u = max(1, min(10, u))
            t = max(1, min(10, t))
            p = g * u * t
            risco = "Crítico" if p >= 200 else ("Médio" if p >= 50 else "Mínimo")
            print(f"  GUT calculado: G={g}  U={u}  T={t}  Prioridade={p}  ({risco})")
            return {"G_gut": g, "U_gut": u, "T_gut": t, "prioridade_gut": p}
        except ValueError:
            print("  Valores invalidos. GUT nao vinculado.")
            return {}

    # ─────────────────────────────────────────────────────────────────────────
    # PREVIEW DA ANÁLISE
    # ─────────────────────────────────────────────────────────────────────────

    def _exibir_preview(self, analise: dict, alertas: List[str]) -> None:
        """
        Pedido 07 — Exibe QUADRO DE CARACTERIZACAO como ficha tecnica
        estruturada, sem truncamento de campos criticos.
        """
        grau   = analise.get("grau_risco", "")
        emoji  = GRAU_RISCO_CONFIG.get(grau, {}).get("emoji", "")
        prazo  = GRAU_RISCO_CONFIG.get(grau, {}).get("prazo", "")
        normas = analise.get("normas_referencias") or []
        if isinstance(normas, list):
            normas_str = ", ".join(normas) if normas else "Nao informadas"
        else:
            normas_str = str(normas) or "Nao informadas"

        g  = analise.get("G_gut")
        u  = analise.get("U_gut")
        t  = analise.get("T_gut")
        p  = analise.get("prioridade_gut")
        gut_str = f"G:{g}  U:{u}  T:{t}  Prioridade:{p}" if g else "Nao vinculado"

        def _linha(label: str, valor: str, largura: int = 55) -> None:
            valor_str = str(valor or "—").strip()
            # Quebra em múltiplas linhas se necessário
            while valor_str:
                trecho = valor_str[:largura]
                if len(valor_str) > largura:
                    # Quebra na última palavra
                    idx = trecho.rfind(" ")
                    if idx > 0:
                        trecho = trecho[:idx]
                print(f"  {label:<22} {trecho}")
                valor_str = valor_str[len(trecho):].strip()
                label = ""  # Só imprime label na primeira linha

        W = 75
        print("\n" + "=" * W)
        print(f"  QUADRO DE CARACTERIZACAO — ANALISE IBAPE")
        print("=" * W)
        _linha("Titulo:",              analise.get("titulo", ""))
        _linha("Data Vistoria:",        analise.get("data_vistoria", ""))
        print("  " + "-" * (W - 2))
        print("  12.1 ANOMALIA")
        print("  " + "-" * (W - 2))
        _linha("  Origem:",            analise.get("anomalia_origem", ""))
        _linha("  Natureza:",          analise.get("anomalia_natureza", ""))
        _linha("  Sistema:",           analise.get("anomalia_sistema", ""))
        _linha("  Elemento:",          analise.get("anomalia_elemento", ""))
        print()
        _linha("  Sintomas:", analise.get("anomalia_sintomas") or "—", largura=52)
        print()
        _linha("  Descricao:", analise.get("anomalia_descricao") or "—", largura=52)
        print("  " + "-" * (W - 2))
        print("  12.2 FALHA")
        print("  " + "-" * (W - 2))
        _linha("  Origem da Falha:",   analise.get("falha_origem", ""))
        if analise.get("falha_descricao"):
            _linha("  Descricao:", analise.get("falha_descricao"), largura=52)
        print()
        _linha("  Nexo Causal:", analise.get("nexo_causal") or "—", largura=52)
        print("  " + "-" * (W - 2))
        print("  12.3 GRAU DE RISCO")
        print("  " + "-" * (W - 2))
        _linha("  Grau:",              f"{emoji} {grau}")
        _linha("  Prazo:",             prazo)
        _linha("  Acao Recomendada:",  analise.get("acao_recomendada", ""))
        print()
        _linha("  Justificativa:", analise.get("grau_justificativa") or "—", largura=52)
        print("  " + "-" * (W - 2))
        _linha("  Normas:",            normas_str)
        _linha("  GUT Vinculado:",     gut_str)
        if analise.get("item_laudo_id"):
            _linha("  Item de Laudo:", f"#{analise['item_laudo_id']}")
        if alertas:
            print("  " + "-" * (W - 2))
            print("  ALERTAS DE CONSISTENCIA:")
            for a in alertas:
                _linha("  >>", a, largura=52)
        print("=" * W)

    # ─────────────────────────────────────────────────────────────────────────
    # FLUXO [L] — LISTAR
    # ─────────────────────────────────────────────────────────────────────────

    def _fluxo_listar(self) -> Optional[int]:
        """Lista análises com filtros. Retorna ID selecionado ou None."""
        print("\n  Filtrar por grau de risco? [1=Critico 2=Medio 3=Minimo ENTER=todos]: ", end="")
        f_grau = input().strip()
        grau_map = {"1": "Crítico", "2": "Médio", "3": "Mínimo", "C": "Crítico", "M": "Médio"}
        grau_filtro = grau_map.get(f_grau.upper())

        analises = buscar_analises(self.conn, projeto_id=self.proj_id, grau_risco=grau_filtro)
        if not analises:
            print("  Nenhuma analise encontrada.")
            return None

        sep = "─" * 80
        print(f"\n  {len(analises)} analise(s) encontrada(s)\n  {sep}")
        print(f"  {'Nr':<4} {'ID':<5} {'Codigo':<17} {'Grau':<10} {'Origem':<12} {'Status':<12} {'Titulo'}")
        print(f"  {sep}")
        for idx, a in enumerate(analises, 1):
            grau  = a.get("grau_risco", "")
            emoji = GRAU_RISCO_CONFIG.get(grau, {}).get("emoji", "")
            print(
                f"  {idx:<4} {a['id']:<5} {a['codigo_analise']:<17} "
                f"{emoji}{grau:<9} {a.get('anomalia_origem',''):<12} "
                f"{a.get('status',''):<12} {(a.get('titulo',''))[:28]}"
            )
        return analises

    def _fluxo_listar_com_selecao(self) -> None:
        """
        Pedido 03 — Lista analises e permite selecionar uma para operar.
        Após listar, oferece: Visualizar / Editar / Finalizar / Exportar DOCX.
        """
        analises = self._fluxo_listar()
        if not analises:
            return

        print("\n  Digite o NUMERO DA LINHA para selecionar (ou 0 para voltar): ", end="")
        try:
            sel = int(input().strip())
        except ValueError:
            return
        if sel == 0 or sel < 1 or sel > len(analises):
            return

        a   = analises[sel - 1]
        aid = a["id"]
        cod = a.get("codigo_analise", "")
        tit = a.get("titulo", "")
        print(f"\n  Selecionado: [{cod}] {tit}")
        print("  [1] Visualizar  [2] Editar  [3] Finalizar  [4] Exportar DOCX  [0] Voltar")
        op = input("  Escolha: ").strip()
        if op == "1":
            row = self.conn.execute("SELECT * FROM analises_ibape WHERE id=?", (aid,)).fetchone()
            if row:
                print(self.formatar_texto_laudo(_row_to_dict(row)))
        elif op == "2":
            self._fluxo_editar(analise_id=aid)
        elif op == "3":
            self._fluxo_finalizar(analise_id=aid)
        elif op == "4":
            row = self.conn.execute("SELECT * FROM analises_ibape WHERE id=?", (aid,)).fetchone()
            if row:
                self._exportar_docx_analise(_row_to_dict(row))

    # ─────────────────────────────────────────────────────────────────────────
    # FLUXO [V] — VISUALIZAR
    # ─────────────────────────────────────────────────────────────────────────

    def _fluxo_visualizar(self) -> None:
        """Exibe texto completo formatado de uma análise."""
        analises = self._fluxo_listar()
        if not analises:
            return
        try:
            sel = int(input("\n  Numero da linha para visualizar: ").strip())
            if sel < 1 or sel > len(analises):
                return
            aid = analises[sel - 1]["id"]
        except ValueError:
            print("  Entrada invalida.")
            return
        row = self.conn.execute("SELECT * FROM analises_ibape WHERE id=?", (aid,)).fetchone()
        if not row:
            print(f"  Analise {aid} nao encontrada.")
            return
        print(self.formatar_texto_laudo(_row_to_dict(row)))

    def _fluxo_editar(self, analise_id: Optional[int] = None) -> None:
        """Edita campos individuais de uma análise existente."""
        if analise_id is None:
            analises = self._fluxo_listar()
            if not analises:
                return
            try:
                sel = int(input("\n  Numero da linha para editar: ").strip())
                if sel < 1 or sel > len(analises):
                    return
                analise_id = analises[sel - 1]["id"]
            except ValueError:
                print("  Entrada invalida.")
                return

        row = self.conn.execute("SELECT * FROM analises_ibape WHERE id=?", (analise_id,)).fetchone()
        if not row:
            print(f"  Analise {analise_id} nao encontrada.")
            return

        campos_editaveis = [
            ("titulo",             "Titulo"),
            ("data_vistoria",      "Data da vistoria"),
            ("anomalia_descricao", "Descricao tecnica da anomalia"),
            ("anomalia_sintomas",  "Sintomas observados"),
            ("anomalia_elemento",  "Elemento construtivo"),
            ("falha_descricao",    "Descricao da falha"),
            ("nexo_causal",        "Nexo causal"),
            ("grau_justificativa", "Justificativa do grau de risco"),
            ("acao_recomendada",   "Acao recomendada"),
            ("normas_referencias", "Normas de referencia"),
            ("G_gut",              "G (Gravidade)"),
            ("U_gut",              "U (Urgencia)"),
            ("T_gut",              "T (Tendencia)"),
        ]
        print(f"\n  Editando: {row['codigo_analise']} — {row['titulo']}")
        print("  Campos editaveis:")
        for i, (campo, label) in enumerate(campos_editaveis, 1):
            val = str(row[campo] or "")[:50]
            print(f"  [{i:>2}] {label:<30} = {val}")

        try:
            idx = int(input("\n  Numero do campo: ").strip()) - 1
            if not (0 <= idx < len(campos_editaveis)):
                print("  Numero fora do intervalo.")
                return
        except ValueError:
            print("  Entrada invalida.")
            return

        campo, label = campos_editaveis[idx]
        print(f"\n  Editando: {label}")
        print(f"  Valor atual: {str(row[campo] or '')[:300]}")
        novo_valor = self._input_texto("  Novo valor: ", obrigatorio=False, max_chars=5000, multilinhas=True)

        if atualizar_analise(self.conn, analise_id, {campo: novo_valor}):
            print(f"\n  Campo '{label}' atualizado com sucesso.")
            # Regenerar texto_laudo
            row_up = _row_to_dict(
                self.conn.execute("SELECT * FROM analises_ibape WHERE id=?", (analise_id,)).fetchone()
            )
            atualizar_analise(self.conn, analise_id, {"texto_laudo": self.formatar_texto_laudo(row_up)})
            print(f"  Texto do laudo regenerado automaticamente.")
        else:
            print(f"  Nao foi possivel atualizar o campo '{label}'.")

    # ─────────────────────────────────────────────────────────────────────────
    # FLUXO [F] — FINALIZAR
    # ─────────────────────────────────────────────────────────────────────────

    def _fluxo_finalizar(self, analise_id: Optional[int] = None) -> None:
        """Finaliza uma análise verificando campos obrigatórios."""
        if analise_id is None:
            analises = self._fluxo_listar()
            if not analises:
                return
            try:
                sel = int(input("\n  Numero da linha para finalizar: ").strip())
                if sel < 1 or sel > len(analises):
                    return
                analise_id = analises[sel - 1]["id"]
            except ValueError:
                print("  Entrada invalida.")
                return

        row = self.conn.execute("SELECT * FROM analises_ibape WHERE id=?", (analise_id,)).fetchone()
        if not row:
            print(f"  Analise {analise_id} nao encontrada.")
            return

        analise = _row_to_dict(row)
        if analise.get("status") == "finalizado":
            print(f"  Analise {analise['codigo_analise']} ja esta FINALIZADA.")
            return

        campos_obrigatorios = {
            "titulo":            "Titulo",
            "anomalia_origem":   "Origem da anomalia",
            "anomalia_natureza": "Natureza da anomalia",
            "anomalia_descricao":"Descricao tecnica",
            "falha_origem":      "Origem da falha",
            "nexo_causal":       "Nexo causal",
            "grau_risco":        "Grau de risco",
            "grau_justificativa":"Justificativa do risco",
            "acao_recomendada":  "Acao recomendada",
        }
        pendentes = [v for k, v in campos_obrigatorios.items() if not analise.get(k)]
        if pendentes:
            print(f"\n  Campos obrigatorios pendentes:")
            for p in pendentes:
                print(f"    - {p}")
            return

        alertas = self.verificar_consistencia_ibape(analise)
        bloqueios = [a for a in alertas if a.startswith("BLOQUEIO:")]
        if bloqueios:
            print("\n  Bloqueios impedem a finalizacao:")
            for b in bloqueios:
                print(f"    - {b}")
            return

        if atualizar_analise(self.conn, analise_id, {"status": "finalizado"}):
            print(f"\n  Analise {analise['codigo_analise']} FINALIZADA com sucesso.")
            resp = input("  Deseja exportar em Word (DOCX) agora? [1=Sim / 2=Nao]: ").strip()
            if resp == "1":
                self._exportar_docx_analise(analise)
        else:
            print(f"  Nao foi possivel finalizar a analise.")

    # ─────────────────────────────────────────────────────────────────────────
    # FLUXO [9/D] — EXCLUIR (Pedido 02 — mensagem de confirmacao)
    # ─────────────────────────────────────────────────────────────────────────

    def _fluxo_deletar(self) -> None:
        """
        Pedido 02 — Exclui uma analise com mensagem clara de confirmacao e resultado.
        """
        analises = self._fluxo_listar()
        if not analises:
            return
        try:
            sel = int(input("\n  Numero da linha para EXCLUIR (0=cancelar): ").strip())
        except ValueError:
            print("  Entrada invalida. Exclusao cancelada.")
            return
        if sel == 0 or sel < 1 or sel > len(analises):
            print("  Exclusao cancelada.")
            return

        a   = analises[sel - 1]
        aid = a["id"]
        cod = a.get("codigo_analise", "")
        tit = a.get("titulo", "")
        print(f"\n  Voce esta prestes a EXCLUIR permanentemente:")
        print(f"  [{cod}] {tit}")
        print(f"  Status: {a.get('status','')}  |  Grau: {a.get('grau_risco','')}")
        conf = input("\n  Confirmar exclusao? [1=Sim, excluir / 2=Nao, cancelar]: ").strip()
        if conf != "1":
            print("  Exclusao cancelada. Nenhuma alteracao realizada.")
            return

        try:
            self.conn.execute("DELETE FROM analises_ibape WHERE id=?", (aid,))
            self.conn.execute("DELETE FROM historico_analises_ibape WHERE analise_id=?", (aid,))
            self.conn.commit()
            print(f"\n  Analise [{cod}] excluida com sucesso.")
            print(f"  O historico de revisoes tambem foi removido.")
        except sqlite3.Error as exc:
            print(f"\n  Erro ao excluir: {exc}")

    # ─────────────────────────────────────────────────────────────────────────
    # FLUXO [I] — IMPORTAR DE [item_laudo]
    # ─────────────────────────────────────────────────────────────────────────

    def _fluxo_importar_item_laudo(self) -> None:
        """
        Tenta importar um item de laudo do banco principal.
        Conforme Seção 4.3 do prompt de implementação.
        """
        if self.conn_p is None:
            print("\n  ⚠️  Banco principal não conectado. Importação indisponível.")
            return

        try:
            conn_raw = self.conn_p.get_connection()
            cursor   = conn_raw.cursor()
            cursor.execute("""
                SELECT id, numero_topico, titulo_topico, grau_risco,
                       matriz_gut, avaliacao_gut_usuario
                FROM topicos
                WHERE grau_risco IS NOT NULL AND grau_risco != '-'
                ORDER BY id DESC LIMIT 30
            """)
            rows = cursor.fetchall()
            conn_raw.close()
        except Exception as exc:
            print(f"\n  ⚠️  Não foi possível acessar itens de laudo: {exc}")
            return

        if not rows:
            print("\n  📭 Nenhum item de laudo com grau de risco encontrado.")
            return

        print("\n  Itens de laudo disponíveis:")
        print(f"  {'ID':<6} {'Risco':<10} {'GUT':<20} {'Título'}")
        print("  " + "─" * 70)
        for r in rows:
            gut_str = r[4] or r[5] or "—"
            print(f"  {r[0]:<6} {(r[3] or '—'):<10} {gut_str:<20} {str(r[2] or '')[:35]}")

        try:
            tid = int(input("\n  ID do item para importar: ").strip())
        except ValueError:
            print("  ⚠️  ID inválido.")
            return

        item = next((r for r in rows if r[0] == tid), None)
        if not item:
            print(f"  ⚠️  Item {tid} não encontrado.")
            return

        # Tentar extrair G, U, T do campo gut
        gut_str = item[4] or item[5] or ""
        g_val = u_val = t_val = p_val = None
        try:
            import re
            nums = re.findall(r"\d+", gut_str)
            if len(nums) >= 3:
                g_val, u_val, t_val = int(nums[0]), int(nums[1]), int(nums[2])
                p_val = g_val * u_val * t_val
        except Exception:
            pass

        prefill = {
            "titulo":         str(item[2] or ""),
            "grau_risco":     item[3] or "",
            "anomalia_sistema":"",
            "item_laudo_id":  item[0],
            "G_gut":          g_val, "U_gut": u_val,
            "T_gut":          t_val, "prioridade_gut": p_val,
        }
        print(f"\n  📎 Importando Item #{tid}: {item[2]}")
        self._fluxo_nova_analise(prefill=prefill)

    # ─────────────────────────────────────────────────────────────────────────
    # FLUXO [B] — BUSCAR NORMAS
    # ─────────────────────────────────────────────────────────────────────────

    def _fluxo_buscar_normas(self) -> None:
        """
        Busca trechos de normas no banco principal relacionados a um tema.
        Conforme Seção 4.4 do prompt de implementação.
        """
        if self.conn_p is None:
            print("\n  ⚠️  Banco principal não conectado. Busca indisponível.")
            return
        tema = input("\n  Digite o tema ou anomalia para buscar normas: ").strip()
        if not tema:
            return
        resultados = buscar_topicos_relacionados(self.conn_p, tema, limite=10)
        if not resultados:
            print("  📭 Nenhum resultado encontrado no banco.")
            return

        print(f"\n  🔍 {len(resultados)} resultado(s) para '{tema}':")
        sep = "─" * 70
        for i, r in enumerate(resultados, 1):
            score = int((r.get("score") or 0) * 100)
            trecho = (r.get("texto_original") or "")[:200]
            print(f"\n  [{i}] {r.get('hierarquia','—')}")
            print(f"       Fonte: {r.get('nome_arquivo','?')} | Relevância: {score}%")
            print(f"       {sep}")
            print(f"       {trecho}...")

        print("\n  (Para copiar uma referência, anote o número acima.)")

    # ─────────────────────────────────────────────────────────────────────────
    # FLUXO [X] — EXPORTAR
    # ─────────────────────────────────────────────────────────────────────────

    def _fluxo_exportar(self) -> None:
        """
        Exportação em Word (DOCX), Excel ou texto para laudo.
        Pedido 06: incluída exportação em DOCX.
        """
        analises = buscar_analises(
            self.conn,
            projeto_id=self.proj_id,
            status="finalizado" if self.EXPORTAR_FINALIZADAS_APENAS else None,
        )
        n = len(analises)
        print(f"\n  {n} analise(s) disponivel(is) para exportação.")
        print("  [1] Word (DOCX) — laudo formatado por analise")
        print("  [2] Word (DOCX) — todas as analises em um documento")
        print("  [3] Excel — planilha estruturada com cores")
        print("  [4] Texto (.txt) — bloco estruturado para colar no laudo")
        print("  [0] Cancelar")
        op = input("  Escolha: ").strip()

        if op == "1":
            # Exportar DOCX individual — selecionar análise
            if not analises:
                print("  Nenhuma analise encontrada.")
                return
            for idx, a in enumerate(analises, 1):
                print(f"  [{idx}] {a.get('codigo_analise','')} — {a.get('titulo','')[:50]}")
            try:
                sel = int(input("  Numero da linha: ").strip())
                if 1 <= sel <= len(analises):
                    row = self.conn.execute("SELECT * FROM analises_ibape WHERE id=?",
                                           (analises[sel-1]["id"],)).fetchone()
                    if row:
                        self._exportar_docx_analise(_row_to_dict(row))
            except (ValueError, IndexError):
                print("  Selecao invalida.")
        elif op == "2":
            self._exportar_docx_todas(analises)
        elif op == "3":
            self._exportar_excel()
        elif op == "4":
            self._exportar_texto_laudo()
        elif op == "0":
            return
        else:
            print("  Opcao invalida.")

    def _exportar_excel(self) -> None:
        """Exporta análises para planilha Excel com cores por grau de risco."""
        try:
            import openpyxl
            from openpyxl.styles import PatternFill, Font
        except ImportError:
            print("  ❌ openpyxl não instalado. Execute: pip install openpyxl")
            return

        analises = buscar_analises(
            self.conn,
            projeto_id=self.proj_id,
            status="finalizado" if self.EXPORTAR_FINALIZADAS_APENAS else None,
        )
        if not analises:
            print("  📭 Nenhuma análise para exportar.")
            return

        cores = {"Crítico": "FFCCCC", "Médio": "FFFFCC", "Mínimo": "CCFFCC"}
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Análises IBAPE"

        colunas = [
            "Código", "Título", "Data Vistoria", "Anomalia Origem",
            "Anomalia Natureza", "Sistema", "Elemento",
            "Falha Origem", "Grau Risco", "G", "U", "T", "GUT",
            "Ação Recomendada", "Prazo", "Normas", "Status",
        ]
        ws.append(colunas)
        for c in ws[1]:
            c.font = Font(bold=True)

        for a in analises:
            grau    = a.get("grau_risco", "")
            gut_p   = a.get("prioridade_gut")
            normas  = a.get("normas_referencias") or []
            if isinstance(normas, list):
                normas_str = ", ".join(normas)
            else:
                normas_str = str(normas)
            prazo = GRAU_RISCO_CONFIG.get(grau, {}).get("prazo", "")
            linha = [
                a.get("codigo_analise", ""),
                a.get("titulo", ""),
                a.get("data_vistoria", ""),
                a.get("anomalia_origem", ""),
                a.get("anomalia_natureza", ""),
                a.get("anomalia_sistema", ""),
                a.get("anomalia_elemento", ""),
                a.get("falha_origem", ""),
                grau,
                a.get("G_gut"), a.get("U_gut"), a.get("T_gut"), gut_p,
                a.get("acao_recomendada", ""),
                prazo,
                normas_str,
                a.get("status", ""),
            ]
            ws.append(linha)
            if grau in cores:
                fill = PatternFill("solid", fgColor=cores[grau])
                for cell in ws[ws.max_row]:
                    cell.fill = fill

        os.makedirs(self.PASTA_EXPORTACAO, exist_ok=True)
        data_str = date.today().strftime("%Y%m%d")
        proj_str = str(self.proj_id or "geral")
        fname    = os.path.join(
            self.PASTA_EXPORTACAO,
            f"Analises_IBAPE_{proj_str}_{data_str}.xlsx",
        )
        wb.save(fname)
        print(f"  ✅ Excel exportado: {fname} ({len(analises)} análise(s))")

    def _exportar_texto_laudo(self) -> None:
        """Exporta texto estruturado para laudo em arquivo .txt."""
        analises = buscar_analises(
            self.conn,
            projeto_id=self.proj_id,
            status="finalizado" if self.EXPORTAR_FINALIZADAS_APENAS else None,
        )
        if not analises:
            print("  📭 Nenhuma análise para exportar.")
            return

        blocos = []
        for a in analises:
            row = self.conn.execute(
                "SELECT * FROM analises_ibape WHERE id=?", (a["id"],)
            ).fetchone()
            if row:
                blocos.append(self.formatar_texto_laudo(_row_to_dict(row)))

        os.makedirs(self.PASTA_EXPORTACAO, exist_ok=True)
        data_str = date.today().strftime("%Y%m%d")
        proj_str = str(self.proj_id or "geral")
        fname    = os.path.join(
            self.PASTA_EXPORTACAO,
            f"Laudo_Analises_IBAPE_{proj_str}_{data_str}.txt",
        )
        with open(fname, "w", encoding="utf-8") as f:
            f.write("\n\n".join(blocos))
        print(f"  Texto para laudo exportado: {fname} ({len(blocos)} analise(s))")

    def _exportar_docx_analise(self, analise: dict) -> Optional[str]:
        """
        Pedido 06 — Exporta uma análise como documento Word (.docx) formatado.
        Retorna o caminho do arquivo gerado, ou None em caso de erro.
        """
        try:
            from docx import Document as DocxDocument
            from docx.shared import Pt, RGBColor, Inches
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            print("  python-docx nao instalado. Execute: pip install python-docx")
            return None

        grau   = analise.get("grau_risco", "")
        codigo = analise.get("codigo_analise", "IBAPE")
        titulo = analise.get("titulo", "")

        # Cores por grau de risco
        cores_rgb = {
            "Crítico": RGBColor(0xCC, 0x00, 0x00),
            "Médio":   RGBColor(0xB8, 0x86, 0x00),
            "Mínimo":  RGBColor(0x1A, 0x80, 0x1A),
        }
        cor_grau = cores_rgb.get(grau, RGBColor(0x00, 0x00, 0x00))

        doc = DocxDocument()

        # Configuração de margens
        from docx.shared import Cm
        for section in doc.sections:
            section.top_margin    = Cm(2.5)
            section.bottom_margin = Cm(2.5)
            section.left_margin   = Cm(3.0)
            section.right_margin  = Cm(2.0)

        # Título do documento
        h = doc.add_heading("ANÁLISE TÉCNICA IBAPE", level=1)
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_codigo = doc.add_paragraph()
        run_codigo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = run_codigo.add_run(f"{codigo}  —  {titulo}")
        r.bold = True
        r.font.size = Pt(12)

        doc.add_paragraph()

        # Função auxiliar para adicionar campo
        def campo(label: str, valor: str, negrito_label: bool = True) -> None:
            p = doc.add_paragraph()
            r_label = p.add_run(f"{label}: ")
            r_label.bold = negrito_label
            r_label.font.size = Pt(11)
            r_valor = p.add_run(str(valor or "—"))
            r_valor.font.size = Pt(11)
            p.paragraph_format.space_after = Pt(3)

        def secao(titulo_sec: str) -> None:
            h = doc.add_heading(titulo_sec, level=2)
            h.runs[0].font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)

        # Identificação
        secao("Identificação")
        campo("Código",          analise.get("codigo_analise", ""))
        campo("Data da Vistoria",analise.get("data_vistoria", ""))
        if analise.get("perito_responsavel"):
            campo("Perito",      analise.get("perito_responsavel", ""))

        # 12.1 Anomalia
        doc.add_paragraph()
        secao("12.1  ANOMALIA  (IBAPE 2025 / NBR 13752:2024)")
        campo("Origem",   analise.get("anomalia_origem", ""))
        campo("Natureza", analise.get("anomalia_natureza", ""))
        campo("Sistema",  analise.get("anomalia_sistema", ""))
        campo("Elemento", analise.get("anomalia_elemento", ""))
        if analise.get("anomalia_sintomas"):
            p = doc.add_paragraph()
            p.add_run("Sintomas observados:").bold = True
            doc.add_paragraph(str(analise.get("anomalia_sintomas", "")))
        p = doc.add_paragraph()
        p.add_run("Descrição técnica:").bold = True
        doc.add_paragraph(str(analise.get("anomalia_descricao", "")))

        # 12.2 Falha
        doc.add_paragraph()
        secao("12.2  FALHA  (IBAPE 2025 / NBR 5674:2012)")
        campo("Classificação da Falha", analise.get("falha_origem", ""))
        if analise.get("falha_descricao"):
            p = doc.add_paragraph()
            p.add_run("Descrição da falha:").bold = True
            doc.add_paragraph(str(analise.get("falha_descricao", "")))
        p = doc.add_paragraph()
        p.add_run("Nexo Causal:").bold = True
        doc.add_paragraph(str(analise.get("nexo_causal", "") or "—"))

        # 12.3 Grau de Risco
        doc.add_paragraph()
        secao("12.3  GRAU DE RISCO  (IBAPE 2025 / NBR 16747:2020)")
        emoji = GRAU_RISCO_CONFIG.get(grau, {}).get("emoji", "")
        prazo = GRAU_RISCO_CONFIG.get(grau, {}).get("prazo", "")
        # Grau em destaque colorido
        p_grau = doc.add_paragraph()
        p_grau.add_run("Classificação: ").bold = True
        r_grau = p_grau.add_run(f"{emoji}  {grau}")
        r_grau.bold = True
        r_grau.font.size = Pt(13)
        r_grau.font.color.rgb = cor_grau

        campo("Prazo de Intervenção", prazo)
        campo("Ação Recomendada", analise.get("acao_recomendada", ""))
        p = doc.add_paragraph()
        p.add_run("Justificativa:").bold = True
        doc.add_paragraph(str(analise.get("grau_justificativa", "") or "—"))

        # GUT Vinculado
        g = analise.get("G_gut")
        if g is not None:
            doc.add_paragraph()
            secao("GUT Vinculado")
            u, t, prio = analise.get("U_gut"), analise.get("T_gut"), analise.get("prioridade_gut")
            campo("Valores GUT", f"G={g}  U={u}  T={t}  Prioridade={prio}")

        # Referências Normativas
        normas = analise.get("normas_referencias") or []
        if isinstance(normas, str):
            try:
                normas = json.loads(normas)
            except Exception:
                normas = [normas]
        if normas:
            doc.add_paragraph()
            secao("Referências Normativas")
            for n in normas:
                doc.add_paragraph(f"• {n}", style="List Bullet")

        # Rodapé com data de geração
        doc.add_paragraph()
        p_rod = doc.add_paragraph()
        p_rod.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r_rod = p_rod.add_run(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} — "
            f"Cérebro de Engenharia Diagnóstica v2.0"
        )
        r_rod.font.size = Pt(8)
        r_rod.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

        # Salvar
        os.makedirs(self.PASTA_EXPORTACAO, exist_ok=True)
        data_str  = date.today().strftime("%Y%m%d")
        safe_cod  = codigo.replace("/", "-").replace(":", "")
        fname     = os.path.join(self.PASTA_EXPORTACAO, f"IBAPE_{safe_cod}_{data_str}.docx")
        doc.save(fname)
        print(f"\n  Analise exportada em Word: {fname}")
        return fname

    def _exportar_docx_todas(self, analises: List[dict]) -> None:
        """
        Pedido 06 — Exporta todas as análises em um único documento Word.
        Cada análise inicia em nova página.
        """
        if not analises:
            print("  Nenhuma analise para exportar.")
            return
        try:
            from docx import Document as DocxDocument
            from docx.shared import Pt, RGBColor, Cm
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.oxml.ns import qn
            import copy
        except ImportError:
            print("  python-docx nao instalado. Execute: pip install python-docx")
            return

        doc = DocxDocument()
        for section in doc.sections:
            section.top_margin    = Cm(2.5)
            section.bottom_margin = Cm(2.5)
            section.left_margin   = Cm(3.0)
            section.right_margin  = Cm(2.0)

        for idx, a in enumerate(analises):
            row = self.conn.execute("SELECT * FROM analises_ibape WHERE id=?", (a["id"],)).fetchone()
            if not row:
                continue
            ad = _row_to_dict(row)
            grau  = ad.get("grau_risco", "")
            emoji = GRAU_RISCO_CONFIG.get(grau, {}).get("emoji", "")
            prazo = GRAU_RISCO_CONFIG.get(grau, {}).get("prazo", "")

            if idx > 0:
                # Quebra de página entre análises
                doc.add_page_break()

            h = doc.add_heading(f"ANÁLISE {ad.get('codigo_analise', '')} — {grau}", level=1)
            doc.add_paragraph(str(ad.get("titulo", "")))
            doc.add_paragraph(f"Data: {ad.get('data_vistoria', '')} | Status: {ad.get('status', '')}")
            doc.add_paragraph()

            for sec_titulo, campos in [
                ("12.1 ANOMALIA", [
                    ("Origem",     ad.get("anomalia_origem", "")),
                    ("Natureza",   ad.get("anomalia_natureza", "")),
                    ("Sistema",    ad.get("anomalia_sistema", "")),
                    ("Elemento",   ad.get("anomalia_elemento", "")),
                    ("Sintomas",   ad.get("anomalia_sintomas", "")),
                    ("Descricao",  ad.get("anomalia_descricao", "")),
                ]),
                ("12.2 FALHA", [
                    ("Classif.",   ad.get("falha_origem", "")),
                    ("Descricao",  ad.get("falha_descricao", "")),
                    ("Nexo Causal",ad.get("nexo_causal", "")),
                ]),
                ("12.3 GRAU DE RISCO", [
                    ("Classificacao", f"{emoji} {grau}"),
                    ("Prazo",         prazo),
                    ("Acao",          ad.get("acao_recomendada", "")),
                    ("Justificativa", ad.get("grau_justificativa", "")),
                ]),
            ]:
                doc.add_heading(sec_titulo, level=2)
                for label, valor in campos:
                    if valor:
                        p = doc.add_paragraph()
                        p.add_run(f"{label}: ").bold = True
                        p.add_run(str(valor))
                doc.add_paragraph()

        os.makedirs(self.PASTA_EXPORTACAO, exist_ok=True)
        data_str = date.today().strftime("%Y%m%d")
        proj_str = str(self.proj_id or "geral")
        fname    = os.path.join(
            self.PASTA_EXPORTACAO,
            f"Analises_IBAPE_{proj_str}_{data_str}_completo.docx",
        )
        doc.save(fname)
        print(f"\n  {len(analises)} analise(s) exportadas em Word: {fname}")


# ══════════════════════════════════════════════════════════════════════════════
# PONTO DE ENTRADA CLI (chamado por main.py via analise_ibape_cli)
# ══════════════════════════════════════════════════════════════════════════════

def analise_ibape_cli(
    conn_principal: Optional[Any] = None,
    projeto_id: Optional[int] = None,
) -> None:
    """
    Ponto de entrada para integração com main.py.
    Inicializa o banco dedicado e abre o menu do módulo.

    Args:
        conn_principal: DatabaseManager do banco principal (opcional).
        projeto_id:     ID do projeto ativo (opcional).
    """
    try:
        db_path = "analise_ibape.db"
        conn_ib = inicializar_banco(db_path)
        modulo  = AnaliseIBAPE(conn_ib, conn_principal, projeto_id)
        modulo.executar()
    except Exception as exc:
        logger.exception("analise_ibape_cli: %s", exc)
        print(f"\n  ❌ Erro no módulo IBAPE: {exc}")
    finally:
        try:
            conn_ib.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 8 — TESTES UNITÁRIOS OBRIGATÓRIOS
# ══════════════════════════════════════════════════════════════════════════════

def _rodar_testes() -> None:
    """
    5 testes unitários conforme Seção 8 do prompt de implementação.
    Executa sem dependências externas (usa :memory:).
    """
    import tempfile, os

    print("\n" + "=" * 65)
    print("  TESTES UNITÁRIOS — analise_ibape.py v1.0")
    print("=" * 65)

    # Banco de testes em memória
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL_ANALISES)
    conn.execute(_DDL_HISTORICO)
    conn.commit()

    modulo = AnaliseIBAPE(conn_ibape=conn, conn_principal=None)
    passou = 0
    falhou = 0

    def _ok(nome: str, cond: bool, detalhe: str = "") -> None:
        nonlocal passou, falhou
        status = "PASSOU" if cond else "FALHOU"
        mark   = "✅" if cond else "❌"
        print(f"\n  {mark}  [{status}]  {nome}")
        if detalhe:
            print(f"         {detalhe}")
        if cond:
            passou += 1
        else:
            falhou += 1

    analise_base = {
        "titulo":             "Fissuras mapeadas em laje do 3º pavimento",
        "anomalia_origem":    "Endógena",
        "anomalia_natureza":  "Vício Construtivo",
        "anomalia_descricao": "X" * 150,
        "falha_origem":       "Execução",
        "nexo_causal":        "O cobrimento insuficiente da armadura, em decorrência de falha de execução, permitiu a carbonatação prematura do concreto, desencadeando a corrosão das barras e o consequente fissuramento do revestimento.",
        "grau_risco":         "Crítico",
        "grau_justificativa": "Risco à segurança dos usuários.",
        "acao_recomendada":   "Interditar e intervir imediatamente.",
        "prioridade_gut":     None,
    }

    # T1 — Consistência R1 (Exógena + falha de manutenção)
    a1 = {**analise_base, "anomalia_origem": "Exógena", "falha_origem": "Planejamento", "nexo_causal": "nexo " * 10}
    alertas1 = modulo.verificar_consistencia_ibape(a1)
    tem_r1 = any("R1" in a for a in alertas1)
    _ok("T1 — Consistência R1 (Exógena + falha de manutenção)", tem_r1,
        f"Alertas: {alertas1}")

    # T2 — Bloqueio R4 (Endógena sem nexo causal)
    a2 = {**analise_base, "anomalia_origem": "Endógena", "nexo_causal": ""}
    alertas2 = modulo.verificar_consistencia_ibape(a2)
    tem_bloqueio = any(a.startswith("BLOQUEIO:") for a in alertas2)
    _ok("T2 — Bloqueio R4 (Endógena sem nexo causal)", tem_bloqueio,
        f"Alertas: {alertas2}")

    # T3 — Análise válida sem alertas
    alertas3 = modulo.verificar_consistencia_ibape(analise_base)
    _ok("T3 — Análise válida Endógena + Execução + Crítico", len(alertas3) == 0,
        f"Alertas (deve ser 0): {alertas3}")

    # T4 — Geração de código único e sequencial
    c1 = _gerar_codigo_analise(conn)
    ano = datetime.now().year
    lid = salvar_analise(conn, {**analise_base, "titulo": "Teste T4-1"})
    c2  = _gerar_codigo_analise(conn)
    lid2= salvar_analise(conn, {**analise_base, "titulo": "Teste T4-2"})
    c3  = _gerar_codigo_analise(conn)
    import re as _re
    formatos_ok = all(_re.match(rf"IBAPE-{ano}-\d{{4}}", c) for c in (c1, c2, c3))
    seq_ok = (c1 != c2 != c3)
    _ok("T4 — Geração de código único e sequencial", formatos_ok and seq_ok,
        f"Códigos gerados: {c1}, {c2}, {c3}")

    # T5 — Texto para laudo contém os 3 cabeçalhos
    analise_fin = {**analise_base, "codigo_analise": "IBAPE-TEST-0001",
                   "data_vistoria": "01/01/2025"}
    texto = modulo.formatar_texto_laudo(analise_fin)
    tem_12_1 = "12.1 ANOMALIA" in texto
    tem_12_2 = "12.2 FALHA" in texto
    tem_12_3 = "12.3 GRAU DE RISCO" in texto
    _ok("T5 — Texto para laudo contém os 3 cabeçalhos IBAPE",
        tem_12_1 and tem_12_2 and tem_12_3,
        f"12.1={tem_12_1} | 12.2={tem_12_2} | 12.3={tem_12_3}")

    print(f"\n{'-' * 65}")
    print(f"  Total: {passou + falhou}/5 | ✅ {passou} passaram | ❌ {falhou} falharam")
    print("=" * 65 + "\n")
    conn.close()


if __name__ == "__main__":
    _rodar_testes()

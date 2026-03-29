"""
analise_imagem.py — Módulo de Análise Integrada de Imagens de Patologia
Sistema: Cérebro de Engenharia Diagnóstica v2.0

Fluxo completo:
  1. Detecta imagens em img_patologias_entrada/
  2. Para cada imagem: executa GUT Adaptativo → análise IBAPE
  3. Usa os dados dos dois módulos para consultar o banco de textos normativos
  4. Chama a API para consolidar tecnicamente a anomalia (homogeneização, não decisão)
  5. Grava resultado no banco e move imagem para img_patologias_processadas/

Regras fundamentais (do prompt de integração):
  - A API NÃO decide sozinha a classificação base
  - GUT adaptativo define a lógica principal de resposta
  - IBAPE complementa com segmentação e enquadramento técnico
  - API homogeneíza, interpreta e retorna consolidação no padrão GUT + IBAPE
  - Cada imagem tem análise independente

Referências:
  IBAPE Nacional (2025) — Diretrizes Técnicas para Perícias Judiciais
  ABNT NBR 13752:2024   — Perícias de Engenharia na Construção Civil
  ABNT NBR 16747:2020   — Inspeção Predial
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("analise_imagem")

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════════════════

PASTA_ENTRADA    = "img_patologias_entrada"
PASTA_SAIDA      = "img_patologias_processadas"
PASTA_ERROS      = "img_patologias_erros"
EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
DB_IBAPE         = "analise_ibape.db"
DB_LAUDOS_IMG    = "laudos_imagem.db"   # banco de laudos de imagem (projetos)

# DDL banco de laudos de imagem
_DDL_LAUDOS_IMG = """
CREATE TABLE IF NOT EXISTS laudos_img (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_laudo      TEXT NOT NULL,
    descricao       TEXT DEFAULT '',
    perito          TEXT DEFAULT '',
    data_criacao    TEXT NOT NULL,
    data_edicao     TEXT NOT NULL,
    status          TEXT DEFAULT 'aberto'
);
CREATE TABLE IF NOT EXISTS imagens_laudo_img (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    laudo_id        INTEGER NOT NULL,
    nome_imagem     TEXT NOT NULL,
    imagem_id       TEXT NOT NULL,
    codigo_ibape    TEXT DEFAULT '',
    grau_risco      TEXT DEFAULT '',
    dados_json      TEXT DEFAULT '{}',
    data_analise    TEXT NOT NULL,
    FOREIGN KEY(laudo_id) REFERENCES laudos_img(id)
);
"""

def _get_conn_laudos() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_LAUDOS_IMG)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL_LAUDOS_IMG)
    conn.commit()
    return conn


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT DE CONSOLIDAÇÃO — enviado à API com os dados preenchidos
# ══════════════════════════════════════════════════════════════════════════════

_PROMPT_CONSOLIDACAO = """
Você é o motor de consolidação técnica do módulo de análise de anomalias por imagem.

Sua função é integrar os dados do GUT Adaptativo com a segmentação da análise IBAPE,
considerar os textos técnicos recuperados do banco e consolidar tecnicamente a anomalia,
produzindo as 5 seções descritivas exigidas pela ABNT NBR 13752 para laudos periciais.

REGRAS OBRIGATÓRIAS:
1. O GUT Adaptativo define a lógica principal — NÃO altere G, U, T, prioridade ou risco.
2. O módulo IBAPE fornece a segmentação técnica complementar (origem, natureza, nexo causal).
3. Homogeneíze os dois módulos SEM romper a coerência do GUT adaptativo.
4. Use os textos do banco APENAS como fundamentação técnica — não sobrescreva formulários.
5. Se houver divergência entre GUT e IBAPE, registre tecnicamente e priorize o GUT.
6. Não invente anomalias não suportadas pelos dados.
7. Não conclua causa definitiva com base apenas em indícios visuais.
8. Indique sempre se a caracterização é preliminar.

INSTRUÇÕES PARA AS 5 SEÇÕES DESCRITIVAS (campos secao_*):
- Cada seção deve ter MÍNIMO 3 frases técnicas completas em prosa corrida.
- Use linguagem formal de laudo pericial (terceira pessoa, voz técnica).
- NÃO use listas com marcadores — use parágrafos descritivos contínuos.
- Fundamente cada seção nos dados concretos fornecidos (GUT, IBAPE, banco).
- Na seção de normas, cite o número da NBR e o critério específico descumprido.
- Na seção de anomalia, defina tecnicamente o que significa a classificação escolhida.
- Na seção de risco, inclua os valores G, U, T e prioridade explicitamente.
- Os textos devem ser suficientes para integrar diretamente um laudo pericial judicial.

DADOS DA ANÁLISE:
{dados_analise}

TEXTOS TÉCNICOS RECUPERADOS DO BANCO:
{textos_banco}

Retorne SOMENTE o JSON abaixo, sem markdown, sem texto adicional:
{{
  "imagem_id": "{imagem_id}",
  "tipo_anomalia_consolidado": "",
  "descricao_tecnica_breve": "",
  "consolidacao_tecnica": "",
  "secao_localizacao_reclamacao": "Texto em prosa descrevendo a localização exata da anomalia no imóvel, o que foi observado e qual a reclamação do solicitante, com referência aos registros fotográficos e dados visuais fornecidos.",
  "secao_ensaios_metodologia": "Texto em prosa descrevendo os ensaios realizados, instrumentos utilizados, procedimento de inspeção e resultados técnicos obtidos.",
  "secao_literatura_normas": "Texto em prosa referenciando as normas ABNT aplicáveis com número e critério específico, e como os textos técnicos recuperados do banco fundamentam a análise.",
  "secao_classificacao_anomalia": "Texto em prosa explicando o motivo da classificação da anomalia (endógena/exógena/natural/funcional), o nexo causal e a relação com a fase construtiva ou de uso.",
  "secao_grau_risco_gut": "Texto em prosa justificando o grau de risco atribuído com os valores G, U, T e prioridade, as consequências potenciais se não houver intervenção e a ação corretiva recomendada.",
  "fundamentacao_gut_adaptativo": {{
    "perguntas_e_respostas_utilizadas": [],
    "gravidade": "",
    "urgencia": "",
    "tendencia": "",
    "classificacao_final": ""
  }},
  "integracao_ibap": {{
    "segmentacao_aplicada": "",
    "enquadramento_tecnico": "",
    "observacao_metodologica": ""
  }},
  "correlacao_com_banco": {{
    "textos_utilizados": [],
    "sintese_correlata": ""
  }},
  "divergencias_identificadas": "",
  "necessita_inspecao_complementar": true,
  "nivel_de_confianca": "alto"
}}
"""


# ══════════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS
# ══════════════════════════════════════════════════════════════════════════════

def _imagem_para_base64(caminho: str) -> Tuple[str, str]:
    """Converte imagem para base64 e retorna (base64_data, mime_type)."""
    ext = Path(caminho).suffix.lower()
    mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".bmp":  "image/bmp",
        ".tiff": "image/tiff", ".tif": "image/tiff",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")
    with open(caminho, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return data, mime


def _listar_imagens(pasta: str) -> List[str]:
    """Lista imagens válidas na pasta de entrada, ordenadas por data de modificação."""
    if not os.path.exists(pasta):
        os.makedirs(pasta, exist_ok=True)
        return []
    arquivos = [
        f for f in os.listdir(pasta)
        if Path(f).suffix.lower() in EXTENSOES_IMAGEM
    ]
    arquivos.sort(key=lambda f: os.path.getmtime(os.path.join(pasta, f)))
    return arquivos


def _mover_imagem(origem: str, pasta_destino: str, nome: str) -> bool:
    """Move imagem para pasta de destino, com sufixo de timestamp se já existir."""
    os.makedirs(pasta_destino, exist_ok=True)
    destino = os.path.join(pasta_destino, nome)
    if os.path.exists(destino):
        base, ext = os.path.splitext(nome)
        destino = os.path.join(pasta_destino, f"{base}_{int(time.time())}{ext}")
    try:
        shutil.move(origem, destino)
        return True
    except Exception as e:
        logger.error("Erro ao mover imagem '%s': %s", nome, e)
        return False


def _limpar_json_resposta(texto: str) -> str:
    """Remove markdown de JSON retornado pela API."""
    t = texto.strip()
    if t.startswith("```"):
        partes = t.split("```")
        # pegar o conteúdo entre as marcações
        for parte in partes:
            parte = parte.strip()
            if parte.startswith("json"):
                parte = parte[4:].strip()
            if parte.startswith("{"):
                return parte
    return t


# ══════════════════════════════════════════════════════════════════════════════
# ANÁLISE DE IMAGEM VIA IA — descrição visual inicial
# ══════════════════════════════════════════════════════════════════════════════

def analisar_imagem_visual(
    caminho_imagem: str,
    ai_engine: Any,
) -> Dict[str, str]:
    """
    Envia a imagem para o modelo multimodal e obtém a descrição visual
    da anomalia observada. Retorna dict com os campos básicos para
    pre-preenchimento do GUT e IBAPE.

    Esta é a PRIMEIRA etapa — não classifica risco nem GUT.
    Apenas descreve o que foi observado visualmente.
    """
    if not getattr(ai_engine, "ia_disponivel", False):
        return {
            "descricao_visual": "[IA indisponível — descrição manual necessária]",
            "tipo_provavel":    "Não identificado",
            "elemento":         "Não identificado",
            "subtipo":          "Não identificado",
        }

    try:
        img_b64, mime = _imagem_para_base64(caminho_imagem)
        nome = Path(caminho_imagem).name

        prompt = (
            f"Você é um engenheiro perito especialista em patologias construtivas.\n"
            f"Analise visualmente a imagem '{nome}' e descreva objetivamente a anomalia observada.\n\n"
            f"Retorne APENAS este JSON (sem markdown):\n"
            f'{{"descricao_visual":"","tipo_provavel":"","subtipo":"","elemento_afetado":"","localizacao_aparente":"","indicios_progressao":"","observacoes_preliminares":""}}\n\n'
            f"Campos:\n"
            f"- descricao_visual: o que é visivelmente observado (2-4 frases técnicas)\n"
            f"- tipo_provavel: ex: fissura, infiltração, corrosão, desplacamento, eflorescência\n"
            f"- subtipo: ex: fissura diagonal, mancha de umidade, corrosão de armadura\n"
            f"- elemento_afetado: ex: laje, pilar, parede, piso, fachada\n"
            f"- localizacao_aparente: ex: canto superior direito, base da parede\n"
            f"- indicios_progressao: o que indica que pode estar evoluindo\n"
            f"- observacoes_preliminares: limitações da análise visual\n"
            f"NÃO classifique risco, GUT ou causa definitiva — apenas descreva."
        )

        # Chamar API com visão multimodal
        resposta = ai_engine._chamar_llm_com_imagem(prompt, img_b64, mime)
        if not resposta:
            raise ValueError("API retornou resposta vazia")

        dados = json.loads(_limpar_json_resposta(resposta))
        return dados

    except Exception as e:
        logger.warning("Análise visual falhou para '%s': %s", caminho_imagem, e)
        return {
            "descricao_visual": f"[Análise visual indisponível: {e}]",
            "tipo_provavel":    "Não identificado",
            "subtipo":          "Não identificado",
            "elemento_afetado": "Não identificado",
            "localizacao_aparente": "Não identificado",
            "indicios_progressao":  "Não avaliado",
            "observacoes_preliminares": "Análise visual não concluída.",
        }


# ══════════════════════════════════════════════════════════════════════════════
# CONSOLIDAÇÃO VIA API — homogeneização GUT + IBAPE + banco
# ══════════════════════════════════════════════════════════════════════════════

def consolidar_via_api(
    imagem_id:      str,
    dados_gut:      Dict[str, Any],
    dados_ibape:    Dict[str, Any],
    textos_banco:   List[Dict[str, Any]],
    ai_engine:      Any,
) -> Dict[str, Any]:
    """
    Envia os dados preenchidos nos dois módulos para a API consolidar.

    A API NÃO decide a classificação base — ela homogeneíza GUT + IBAPE,
    interpreta tecnicamente e retorna a consolidação no padrão estruturado.

    Args:
        imagem_id:    Identificador da imagem.
        dados_gut:    Resultado completo do GUT Adaptativo (ResultadoGUT serializado).
        dados_ibape:  Dados da análise IBAPE (anomalia, falha, nexo, risco).
        textos_banco: Trechos recuperados da busca híbrida no banco.
        ai_engine:    Instância de AIEngine com IA disponível.

    Returns:
        dict com a consolidação no formato estruturado do prompt.
        Em caso de falha retorna estrutura com nivel_de_confianca='baixo'.
    """
    _fallback = {
        "imagem_id":                 imagem_id,
        "tipo_anomalia_consolidado": dados_gut.get("risco", "Não classificado"),
        "descricao_tecnica_breve":   dados_ibape.get("anomalia_descricao", ""),
        "consolidacao_tecnica":      "[Consolidação via API indisponível — dados brutos preservados]",
        "fundamentacao_gut_adaptativo": {
            "perguntas_e_respostas_utilizadas": [],
            "gravidade":          str(dados_gut.get("G", "-")),
            "urgencia":           str(dados_gut.get("U", "-")),
            "tendencia":          str(dados_gut.get("T", "-")),
            "classificacao_final": dados_gut.get("risco", "-"),
        },
        "integracao_ibap": {
            "segmentacao_aplicada":    dados_ibape.get("anomalia_origem", ""),
            "enquadramento_tecnico":   dados_ibape.get("anomalia_natureza", ""),
            "observacao_metodologica": "Consolidação API indisponível.",
        },
        "correlacao_com_banco": {
            "textos_utilizados": [t.get("titulo_topico", "") for t in textos_banco[:3]],
            "sintese_correlata": "",
        },
        "divergencias_identificadas":   "",
        "necessita_inspecao_complementar": True,
        "nivel_de_confianca":           "baixo",
    }

    if not getattr(ai_engine, "ia_disponivel", False):
        return _fallback

    try:
        # Montar bloco de dados para o prompt
        dados_analise = json.dumps({
            "GUT_Adaptativo": {
                "G":          dados_gut.get("G"),
                "U":          dados_gut.get("U"),
                "T":          dados_gut.get("T"),
                "prioridade": dados_gut.get("prioridade"),
                "risco":      dados_gut.get("risco"),
                "subsistema": dados_gut.get("subsistema"),
                "nexo_causal": {
                    "origem":    dados_gut.get("nexo", {}).get("origem") if dados_gut.get("nexo") else None,
                    "mecanismo": dados_gut.get("nexo", {}).get("mecanismo") if dados_gut.get("nexo") else None,
                    "descricao": dados_gut.get("nexo", {}).get("descricao") if dados_gut.get("nexo") else None,
                },
                "justificativa_G":   dados_gut.get("justificativa_G"),
                "justificativa_U":   dados_gut.get("justificativa_U"),
                "justificativa_T":   dados_gut.get("justificativa_T"),
                "acao_recomendada":  dados_gut.get("acao_recomendada"),
                "normas_sugeridas":  dados_gut.get("normas_sugeridas"),
                "confianca":         dados_gut.get("confianca"),
                "fonte":             dados_gut.get("fonte"),
                "respostas_json":    dados_gut.get("respostas_json"),
            },
            "Analise_IBAPE": {
                "anomalia_origem":    dados_ibape.get("anomalia_origem"),
                "anomalia_natureza":  dados_ibape.get("anomalia_natureza"),
                "anomalia_sistema":   dados_ibape.get("anomalia_sistema"),
                "anomalia_elemento":  dados_ibape.get("anomalia_elemento"),
                "anomalia_descricao": dados_ibape.get("anomalia_descricao"),
                "anomalia_sintomas":  dados_ibape.get("anomalia_sintomas"),
                "falha_origem":       dados_ibape.get("falha_origem"),
                "falha_descricao":    dados_ibape.get("falha_descricao"),
                "nexo_causal":        dados_ibape.get("nexo_causal"),
                "grau_risco":         dados_ibape.get("grau_risco"),
                "grau_justificativa": dados_ibape.get("grau_justificativa"),
                "acao_recomendada":   dados_ibape.get("acao_recomendada"),
                "normas_referencias": dados_ibape.get("normas_referencias"),
            },
            "Imagem": {
                "id":                     imagem_id,
                "descricao_visual":       dados_ibape.get("_descricao_visual", ""),
                "tipo_provavel":          dados_ibape.get("_tipo_provavel", ""),
                "observacoes_preliminares": dados_ibape.get("_observacoes_preliminares", ""),
            },
        }, ensure_ascii=False, indent=2)

        # Montar bloco de textos do banco
        textos_formatados = []
        for i, t in enumerate(textos_banco[:5], 1):
            textos_formatados.append(
                f"[{i}] Fonte: {t.get('nome_arquivo','?')} | Item {t.get('numero_topico','')}\n"
                f"    Seção: {t.get('titulo_topico','')}\n"
                f"    {str(t.get('texto_original',''))[:400]}"
            )
        textos_str = "\n\n".join(textos_formatados) or "Nenhum texto correlato recuperado."

        prompt = _PROMPT_CONSOLIDACAO.format(
            dados_analise=dados_analise,
            textos_banco=textos_str,
            imagem_id=imagem_id,
        )

        sistema = (
            "Você é o motor de consolidação técnica do módulo de análise de anomalias "
            "por imagem de um sistema pericial judicial. Responda APENAS com JSON válido."
        )

        resposta = ai_engine._chamar_llm(sistema, prompt)
        if not resposta:
            raise ValueError("API retornou resposta vazia")

        resultado = json.loads(_limpar_json_resposta(resposta))

        # Normalizar nivel_de_confianca — Ollama às vezes ecoa o placeholder do prompt
        nc = str(resultado.get("nivel_de_confianca", "") or "").lower()
        if "|" in nc or nc.strip() not in ("baixo", "medio", "médio", "alto"):
            if "alto" in nc:
                resultado["nivel_de_confianca"] = "alto"
            elif "medio" in nc or "médio" in nc:
                resultado["nivel_de_confianca"] = "médio"
            else:
                resultado["nivel_de_confianca"] = "baixo"

        return resultado

    except Exception as e:
        logger.warning("Consolidação API falhou para '%s': %s", imagem_id, e)
        _fallback["consolidacao_tecnica"] = f"[Consolidação indisponível: {e}]"
        return _fallback


# ══════════════════════════════════════════════════════════════════════════════
# BUSCA DE TEXTOS NO BANCO — usando termos do GUT + IBAPE
# ══════════════════════════════════════════════════════════════════════════════

def buscar_textos_correlatos(
    db_manager:   Any,
    dados_gut:    Dict[str, Any],
    dados_ibape:  Dict[str, Any],
    descricao_visual: str = "",
    n: int = 8,
) -> List[Dict[str, Any]]:
    """
    Busca trechos correlatos no banco usando APENAS busca textual offline.

    MELHORIA 4 (revisada): usa exclusivamente busca_textual() com termos_anchor,
    sem embedding e sem qualquer chamada de IA.
    Isso mantém a Etapa 4 totalmente offline e sem custo de API.

    A qualidade da busca é garantida pelo sistema de âncoras e score ponderado
    já implementado em busca_textual() — mesma lógica do [evidencias].

    Args:
        db_manager:       Instância de DatabaseManager.
        dados_gut:        Resultado do GUT Adaptativo.
        dados_ibape:      Dados da análise IBAPE.
        descricao_visual: Descrição visual inicial da imagem.
        n:                Número máximo de resultados.

    Returns:
        Lista de dicts com os trechos recuperados, ou [] em caso de falha.
    """
    import re as _re

    # ── Stopwords a excluir dos termos de busca ────────────────────────────
    _SW = {
        "de","da","do","das","dos","em","no","na","um","uma","o","a","e",
        "que","se","por","para","com","não","como","foi","são","ser","ter",
        "pode","deve","este","esta","pelo","pela","sua","seu","mais","também",
        "endógena","exógena","natural","funcional","construtivo","pelo","pela",
        "ausencia","presença","através","conforme","segundo","mediante",
        "entre","após","sobre","sob","assim","então","sendo","tendo",
    }

    termos_set: set = set()

    # ── 1. Termos técnicos do GUT ─────────────────────────────────────────
    subsistema = (dados_gut.get("subsistema") or "").lower()
    if subsistema and len(subsistema) > 3:
        termos_set.add(subsistema)

    for norma in (dados_gut.get("normas_sugeridas") or []):
        norma_lower = norma.lower().strip()
        if norma_lower:
            termos_set.add(norma_lower)

    nexo_gut = dados_gut.get("nexo") or {}
    if isinstance(nexo_gut, dict):
        texto_nexo_gut = str(nexo_gut.get("texto_livre","") or nexo_gut.get("descricao","") or "")
        for tok in _re.findall(r'[a-záéíóúàâêôãõüç]{5,}', texto_nexo_gut.lower()):
            if tok not in _SW:
                termos_set.add(tok)

    # ── 2. Termos técnicos do IBAPE ───────────────────────────────────────
    # Campos curtos: adicionar diretamente
    for campo in ["anomalia_sistema", "anomalia_elemento", "anomalia_origem"]:
        v = (dados_ibape.get(campo) or "").lower().strip()
        if v and len(v) > 3 and v not in _SW:
            termos_set.add(v)

    # Campos longos: extrair tokens técnicos (≥ 5 chars, sem stopwords)
    for campo in ["anomalia_sintomas", "nexo_causal", "anomalia_descricao"]:
        v = dados_ibape.get(campo) or ""
        for tok in _re.findall(r'[a-záéíóúàâêôãõüç]{5,}', v.lower()):
            if tok not in _SW:
                termos_set.add(tok)
                if len(termos_set) >= 20:
                    break

    # ── 3. Termos da descrição visual ─────────────────────────────────────
    for campo in ["_tipo_provavel", "_elemento_afetado"]:
        v = (dados_ibape.get(campo) or descricao_visual).lower().strip()
        for tok in v.replace("-","").split():
            if len(tok) > 3 and tok not in _SW:
                termos_set.add(tok)

    # ── 4. Limpar e ordenar ────────────────────────────────────────────────
    termos = [t for t in termos_set if len(t) > 3]
    # Priorizar normas e termos mais específicos no início (âncoras)
    normas_termos = [t for t in termos if any(
        t.startswith(p) for p in ["nbr","abnt","iso","ibape","astm"]
    )]
    outros_termos = [t for t in termos if t not in normas_termos]
    termos_ordenados = (normas_termos + outros_termos)[:15]

    if not termos_ordenados:
        logger.warning("buscar_textos_correlatos: nenhum termo extraído.")
        return []

    # ── 5. Busca EXCLUSIVAMENTE TEXTUAL — sem embedding, sem IA ──────────
    # Nota: termos_anchor foi removido intencionalmente. O filtro de 2 âncoras
    # em busca_textual() descartava documentos relevantes quando os códigos de
    # norma incluíam número de parte (ex: "nbr 15575-4" ≠ "nbr 15575" do banco).
    # O scoring natural pelos 15 termos já garante ordenação por relevância.
    try:
        if hasattr(db_manager, "busca_textual"):
            resultados = db_manager.busca_textual(
                termos=termos_ordenados,
                tipo_fonte=None,
            )
        else:
            logger.warning("buscar_textos_correlatos: db_manager sem busca_textual.")
            return []

        filtrados = [r for r in (resultados or [])
                     if not (r.get("hierarquia") or "").startswith("ANÁLISE DE IMAGEM")]
        return filtrados[:n]

    except Exception as e:
        logger.error("buscar_textos_correlatos: erro na busca: %s", e)
        return []


def _fetch_topicos_by_ids(db_manager: Any, ids: List[int]) -> List[Dict[str, Any]]:
    """
    Busca trechos no banco principal pelos IDs salvos em topicos_banco (IBAPE).
    Retorna lista de dicts no mesmo formato de buscar_textos_correlatos.
    """
    if not ids or db_manager is None:
        return []
    try:
        conn = db_manager.get_connection()
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT t.id, t.titulo_topico, t.hierarquia, t.texto_original, "
            f"l.nome_arquivo, l.tipo_fonte "
            f"FROM topicos t JOIN laudos l ON t.laudo_id = l.id "
            f"WHERE t.id IN ({placeholders}) "
            f"AND (t.hierarquia IS NULL OR t.hierarquia NOT LIKE 'ANÁLISE DE IMAGEM%')",
            ids,
        ).fetchall()
        result = []
        for row in rows:
            result.append({
                "id":             row[0],
                "titulo_topico":  row[1] or "",
                "hierarquia":     row[2] or "",
                "texto_original": row[3] or "",
                "nome_arquivo":   row[4] or "",
                "tipo_fonte":     row[5] or "",
                "score":          0,
            })
        return result
    except Exception as e:
        logger.warning("_fetch_topicos_by_ids: %s", e)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# FLUXO PRINCIPAL — AnalisadorImagem
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# CONSOLIDAÇÃO OFFLINE — produz resultado estruturado sem IA
# ══════════════════════════════════════════════════════════════════════════════

def _consolidar_offline(
    imagem_id:    str,
    dados_gut:    Dict[str, Any],
    dados_ibape:  Dict[str, Any],
    textos_banco: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Produz a consolidação técnica completa usando APENAS os dados dos módulos
    GUT e IBAPE preenchidos pelo perito. Sem IA, sem API, sem custo.

    A consolidação offline é baseada em:
      - G, U, T e risco do GUT Adaptativo (classificação do perito)
      - Origem, natureza, nexo causal e grau de risco da análise IBAPE
      - Normas sugeridas pelo GUT e pelo banco
      - Textos correlatos recuperados do banco

    Produz o mesmo formato JSON que consolidar_via_api() retornaria,
    garantindo que o restante do fluxo funcione sem alteração.
    """
    # ── Extrair dados do GUT ──────────────────────────────────────────────
    G        = dados_gut.get("G") or "-"
    U        = dados_gut.get("U") or "-"
    T        = dados_gut.get("T") or "-"
    prio     = dados_gut.get("prioridade") or "-"
    risco    = dados_gut.get("risco") or "Não classificado"
    subsist  = dados_gut.get("subsistema") or ""
    acao_gut = dados_gut.get("acao_recomendada") or ""
    normas_gut = dados_gut.get("normas_sugeridas") or []

    nexo_gut = dados_gut.get("nexo") or {}
    if isinstance(nexo_gut, dict):
        origem_gut  = str(nexo_gut.get("origem","") or "")
        mec_gut     = str(nexo_gut.get("mecanismo","") or "")
        texto_nexo  = str(nexo_gut.get("texto_livre","") or nexo_gut.get("descricao","") or "")
    else:
        origem_gut = mec_gut = texto_nexo = ""

    # ── Extrair dados do IBAPE ────────────────────────────────────────────
    orig_ib  = dados_ibape.get("anomalia_origem","")     or ""
    nat_ib   = dados_ibape.get("anomalia_natureza","")   or ""
    sist_ib  = dados_ibape.get("anomalia_sistema","")    or ""
    elem_ib  = dados_ibape.get("anomalia_elemento","")   or ""
    sint_ib  = dados_ibape.get("anomalia_sintomas","")   or ""
    desc_ib  = dados_ibape.get("anomalia_descricao","")  or ""
    nexo_ib  = dados_ibape.get("nexo_causal","")         or ""
    grau_ib  = dados_ibape.get("grau_risco","")          or risco
    just_ib  = dados_ibape.get("grau_justificativa","")  or ""
    acao_ib  = dados_ibape.get("acao_recomendada","")    or acao_gut
    normas_ib = dados_ibape.get("normas_referencias","") or []
    if isinstance(normas_ib, str):
        normas_ib = [n.strip() for n in normas_ib.split(",") if n.strip()]

    visual  = dados_ibape.get("_descricao_visual","")    or ""
    tipo    = dados_ibape.get("_tipo_provavel","")        or orig_ib

    # ── Tipo consolidado ──────────────────────────────────────────────────
    tipo_consolidado = " — ".join(filter(None, [tipo, elem_ib, nat_ib])) or risco

    # ── Descrição técnica breve ───────────────────────────────────────────
    descricao_breve = (
        (desc_ib or sint_ib or visual)[:200].strip() or
        f"{tipo_consolidado}. Avaliação GUT: G={G} U={U} T={T} → {risco}."
    )

    # ── Consolidação técnica (texto estruturado) ──────────────────────────
    partes = []

    if desc_ib:
        partes.append(f"ANOMALIA: {desc_ib[:400]}")
    elif visual:
        partes.append(f"DESCRIÇÃO VISUAL: {visual[:300]}")

    if sint_ib:
        partes.append(f"SINTOMAS: {sint_ib[:200]}")

    partes.append(
        f"CLASSIFICAÇÃO GUT: G={G} | U={U} | T={T} | "
        f"Prioridade={prio} | Risco={risco}"
    )

    partes.append(
        f"ANÁLISE IBAPE: Origem={orig_ib} | Natureza={nat_ib} | "
        f"Sistema={sist_ib} | Elemento={elem_ib}"
    )

    nexo_final = nexo_ib or texto_nexo
    if nexo_final:
        partes.append(f"NEXO CAUSAL: {nexo_final[:400]}")

    partes.append(f"GRAU DE RISCO: {grau_ib}")
    if just_ib:
        partes.append(f"JUSTIFICATIVA: {just_ib[:200]}")
    if acao_ib:
        partes.append(f"AÇÃO RECOMENDADA: {acao_ib[:200]}")

    if normas_gut or normas_ib:
        todas_normas = list(dict.fromkeys(
            list(normas_gut) + (normas_ib if isinstance(normas_ib, list) else [])
        ))
        partes.append(f"NORMAS APLICÁVEIS: {', '.join(todas_normas[:8])}")

    consolidacao_tecnica = "\n\n".join(partes)

    # ── Textos do banco utilizados ────────────────────────────────────────
    textos_usados = [
        f"{t.get('nome_arquivo','?')[:40]} — {t.get('titulo_topico','')[:50]}"
        for t in textos_banco[:5]
    ]
    sintese = ""
    if textos_banco:
        fontes = list({t.get("nome_arquivo","") for t in textos_banco[:5]})
        sintese = (
            f"{len(textos_banco)} trecho(s) recuperado(s) do banco para fundamentação: "
            f"{', '.join(fontes[:3])}."
        )

    # ── Perguntas e respostas do GUT ──────────────────────────────────────
    import json as _json
    respostas_json = dados_gut.get("respostas_json","{}") or "{}"
    try:
        respostas = _json.loads(respostas_json)
        pq_resp = [f"{k}: {v}" for k, v in respostas.items()][:8]
    except Exception:
        pq_resp = []

    # ── Divergências entre GUT e IBAPE ───────────────────────────────────
    div = []
    if risco and grau_ib and risco.lower() != grau_ib.lower():
        div.append(
            f"GUT classifica '{risco}' mas IBAPE registra '{grau_ib}' — "
            f"verificar consistência."
        )
    if orig_ib and origem_gut and not orig_ib.lower().startswith(origem_gut.lower().split()[0]):
        div.append(
            f"Origem GUT ('{origem_gut}') diverge da origem IBAPE ('{orig_ib}')."
        )
    divergencias = " | ".join(div) if div else "Nenhuma divergência identificada."

    # ── Nível de confiança ────────────────────────────────────────────────
    # Alto: GUT e IBAPE completos com nexo causal
    # Médio: módulos completos sem nexo ou sem normas
    # Baixo: campos essenciais ausentes
    campos_ok = sum([
        bool(desc_ib or visual),
        bool(nexo_ib or texto_nexo),
        bool(grau_ib),
        bool(normas_gut or normas_ib),
        bool(G != "-" and U != "-" and T != "-"),
    ])
    confianca = "alto" if campos_ok >= 4 else ("medio" if campos_ok >= 2 else "baixo")

    # ── Seções descritivas NBR 13752 (geradas offline) ───────────────────
    _dv_fake: Dict[str, Any] = {}  # _consolidar_offline não recebe dados_visual separados
    return {
        "imagem_id":                    imagem_id,
        "tipo_anomalia_consolidado":    tipo_consolidado,
        "descricao_tecnica_breve":      descricao_breve,
        "consolidacao_tecnica":         consolidacao_tecnica,
        "secao_localizacao_reclamacao": _gerar_secao1_offline(dados_ibape, _dv_fake),
        "secao_ensaios_metodologia":    _gerar_secao2_offline(dados_ibape),
        "secao_literatura_normas":      _gerar_secao3_offline(textos_banco, dados_ibape, dados_gut),
        "secao_classificacao_anomalia": _gerar_secao4_offline(dados_ibape, dados_gut),
        "secao_grau_risco_gut":         _gerar_secao5_offline(dados_gut, dados_ibape),
        "fundamentacao_gut_adaptativo": {
            "perguntas_e_respostas_utilizadas": pq_resp,
            "gravidade":          str(G),
            "urgencia":           str(U),
            "tendencia":          str(T),
            "classificacao_final": risco,
        },
        "integracao_ibap": {
            "segmentacao_aplicada":    f"{orig_ib} — {nat_ib}",
            "enquadramento_tecnico":   f"Sistema: {sist_ib} | Elemento: {elem_ib}",
            "observacao_metodologica": (
                "Consolidação gerada em modo offline com base nos dados "
                "preenchidos pelo perito nos módulos GUT Adaptativo e IBAPE. "
                "Nenhuma chamada de IA foi realizada nesta etapa."
            ),
        },
        "correlacao_com_banco": {
            "textos_utilizados": textos_usados,
            "sintese_correlata": sintese,
        },
        "divergencias_identificadas":        divergencias,
        "necessita_inspecao_complementar":   True,
        "nivel_de_confianca":                confianca,
        "_modo_consolidacao":               "offline",
    }


_DEFINICOES_ORIGEM = {
    "Endógena":    "originária de fatores inerentes à própria edificação, relacionados a falhas de projeto ou de execução",
    "Exógena":     "provocada por agentes externos à edificação, como ação de terceiros ou fenômenos não previstos no projeto",
    "Natural":     "decorrente de fenômenos naturais ou agentes ambientais que atuam sobre a edificação ao longo do tempo",
    "Funcional":   "resultante do uso, operação ou ausência de manutenção adequada dos sistemas construtivos",
    "A Determinar":"cuja origem requer investigação diagnóstica complementar para caracterização definitiva",
}


def _gerar_secao1_offline(dados_ibape: dict, dados_visual: dict = None) -> str:
    """Seção 1 — Localização, descrição da anomalia e reclamação do solicitante."""
    dv = dados_visual or {}
    elemento   = (dados_ibape.get("anomalia_elemento") or dv.get("elemento_afetado")
                  or dados_ibape.get("_elemento_afetado") or "elemento construtivo")
    local      = (dv.get("localizacao_aparente") or dados_ibape.get("titulo") or "")
    tipo       = (dv.get("tipo_provavel") or dados_ibape.get("_tipo_provavel") or
                  dados_ibape.get("anomalia_sistema") or "anomalia")
    descr      = (dados_ibape.get("anomalia_descricao") or dv.get("descricao_visual")
                  or dados_ibape.get("_descricao_visual") or "")
    sint       = dados_ibape.get("anomalia_sintomas") or ""
    reclam     = dados_ibape.get("reclamacao_cliente") or ""

    base = f"Os registros fotográficos referem-se a {elemento.lower()}"
    if local and local.lower() not in elemento.lower():
        base += f", situado em {local.lower()}"
    base += f", onde foi identificada a ocorrência de {tipo.lower()}."

    partes = [base]
    if descr:
        partes.append(descr[:500])
    if sint:
        partes.append(f"Os principais sintomas observados compreendem: {sint[:300]}.")
    if reclam:
        partes.append(f"Conforme relatado pelo solicitante: {reclam[:400]}.")
    else:
        partes.append(
            "A anomalia foi identificada durante vistoria técnica in loco "
            "e registrada por meio de documentação fotográfica."
        )
    return " ".join(partes)


def _gerar_secao2_offline(dados_ibape: dict) -> str:
    """Seção 2 — Ensaios, metodologia de inspeção e resultados obtidos."""
    ensaios  = dados_ibape.get("ensaios_realizados") or ""
    metod    = dados_ibape.get("metodologia_inspecao") or ""
    sistema  = dados_ibape.get("anomalia_sistema") or "acabamento"
    elemento = dados_ibape.get("anomalia_elemento") or "elemento construtivo"

    partes = [
        f"Durante a vistoria técnica, foi realizada inspeção detalhada do "
        f"{elemento.lower()} afetado, pertencente ao sistema de {sistema.lower()}."
    ]
    if ensaios:
        partes.append(f"Os seguintes ensaios e verificações foram realizados: {ensaios}.")
    else:
        partes.append(
            "A inspeção foi conduzida por metodologia visual sistemática, "
            "com registro fotográfico das manifestações patológicas observadas."
        )
    if metod:
        partes.append(metod[:600])
    else:
        partes.append(
            "O procedimento incluiu exame das condições superficiais do sistema construtivo, "
            "identificação dos pontos de manifestação patológica e avaliação qualitativa "
            "da extensão e severidade das anomalias constatadas."
        )
    return " ".join(partes)


def _gerar_secao3_offline(textos_banco: list, dados_ibape: dict, dados_gut: dict) -> str:
    """Seção 3 — Literatura técnica e normas que fundamentam o item."""
    import json as _j
    normas_ib  = dados_ibape.get("normas_referencias") or []
    if isinstance(normas_ib, str):
        try:    normas_ib = _j.loads(normas_ib)
        except: normas_ib = [n.strip() for n in normas_ib.split(",") if n.strip()]
    normas_gut = dados_gut.get("normas_sugeridas") or []
    ndesc      = dados_ibape.get("normas_descumpridas") or ""
    todas      = list(dict.fromkeys([n for n in list(normas_gut) + list(normas_ib) if n]))

    partes = []
    if todas:
        partes.append(
            f"A condição técnica identificada deve ser avaliada à luz das seguintes "
            f"referências normativas: {', '.join(todas[:6])}."
        )
    else:
        partes.append(
            "A condição técnica identificada deve ser avaliada conforme as normas "
            "ABNT aplicáveis ao sistema construtivo afetado."
        )
    if ndesc:
        partes.append(f"Foram identificadas as seguintes não conformidades normativas: {ndesc}.")
    if textos_banco:
        fontes = list(dict.fromkeys(
            t.get("nome_arquivo", "") for t in textos_banco[:3] if t.get("nome_arquivo")
        ))
        if fontes:
            partes.append(
                f"O banco técnico-pericial do sistema contém referências correlatas "
                f"recuperadas de: {', '.join(fontes)}. "
                f"Esses trechos complementam a fundamentação técnica desta análise."
            )
    else:
        partes.append(
            "Recomenda-se consultar as normas técnicas aplicáveis e a literatura "
            "especializada para complementar a fundamentação desta análise."
        )
    return " ".join(partes)


def _gerar_secao4_offline(dados_ibape: dict, dados_gut: dict) -> str:
    """Seção 4 — Explicação da classificação de anomalia e nexo causal."""
    origem   = dados_ibape.get("anomalia_origem") or "A Determinar"
    natureza = dados_ibape.get("anomalia_natureza") or ""
    nexo     = dados_ibape.get("nexo_causal") or ""
    expl     = dados_ibape.get("explicacao_classificacao") or ""
    nexo_gut = dados_gut.get("nexo") or {}
    mec_gut  = str(nexo_gut.get("mecanismo", "") or "") if isinstance(nexo_gut, dict) else ""

    defn   = _DEFINICOES_ORIGEM.get(origem, "cuja natureza requer investigação complementar")
    partes = [f"A manifestação patológica foi classificada como anomalia {origem.lower()}, {defn}."]

    if expl:
        partes.append(expl[:500])
    if nexo:
        partes.append(f"O nexo causal identificado indica que: {nexo[:400]}.")
    if natureza:
        partes.append(
            f"Quanto à natureza, a anomalia foi enquadrada como {natureza.lower()}, "
            f"conforme os critérios do Item 12.1 da metodologia IBAPE (2025)."
        )
    if mec_gut:
        partes.append(
            f"O mecanismo de degradação avaliado pelo GUT Adaptativo foi "
            f"classificado como: {mec_gut.lower()}."
        )
    return " ".join(partes)


def _gerar_secao5_offline(dados_gut: dict, dados_ibape: dict) -> str:
    """Seção 5 — Grau de risco e Matriz GUT."""
    G       = dados_gut.get("G") or "-"
    U       = dados_gut.get("U") or "-"
    T       = dados_gut.get("T") or "-"
    prio    = dados_gut.get("prioridade") or "-"
    grau    = dados_ibape.get("grau_risco") or dados_gut.get("risco") or "A classificar"
    just    = dados_ibape.get("grau_justificativa") or ""
    acao    = dados_ibape.get("acao_recomendada") or ""
    prazo   = dados_ibape.get("prazo_intervencao") or ""
    conseq  = dados_ibape.get("consequencias_risco") or ""

    partes = [
        f"Quanto à avaliação de risco, a situação foi enquadrada como de grau "
        f"{grau.lower()}, com base na Matriz GUT "
        f"(Gravidade={G}, Urgência={U}, Tendência={T}, Prioridade={prio})."
    ]
    if just:
        partes.append(just[:600])
    if conseq:
        partes.append(f"Caso não haja intervenção em prazo adequado: {conseq[:400]}.")
    else:
        partes.append(
            "A ausência de intervenção pode resultar no agravamento progressivo "
            "das condições da anomalia, com potencial comprometimento da integridade "
            "do sistema construtivo e de seus componentes adjacentes."
        )
    if acao:
        prazo_str = f" no prazo de {prazo}" if prazo else ""
        partes.append(f"Recomenda-se{prazo_str}: {acao}.")
    return " ".join(partes)


def _escrever_secoes_observacao(
    p_obs,
    consolidacao: dict,
    dados_visual: dict,
    dados_ibape: dict,
    dados_gut: dict,
    textos_banco: list,
) -> None:
    """
    Escreve as 5 seções descritivas NBR 13752 no parágrafo da célula de observação.
    Usa os campos secao_* da consolidação (IA) se disponíveis; caso contrário,
    gera os textos via funções offline.
    """
    from docx.shared import Pt as _Pt

    def _bloco(titulo: str, texto: str, ultimo: bool = False):
        r = p_obs.add_run(titulo + "\n")
        r.bold = True
        r.font.size = _Pt(9)
        r2 = p_obs.add_run((texto or "—") + ("" if ultimo else "\n\n"))
        r2.font.size = _Pt(9)

    s1 = (consolidacao.get("secao_localizacao_reclamacao") or
          _gerar_secao1_offline(dados_ibape, dados_visual))
    s2 = (consolidacao.get("secao_ensaios_metodologia") or
          _gerar_secao2_offline(dados_ibape))
    s3 = (consolidacao.get("secao_literatura_normas") or
          _gerar_secao3_offline(textos_banco, dados_ibape, dados_gut))
    s4 = (consolidacao.get("secao_classificacao_anomalia") or
          _gerar_secao4_offline(dados_ibape, dados_gut))
    s5 = (consolidacao.get("secao_grau_risco_gut") or
          _gerar_secao5_offline(dados_gut, dados_ibape))

    _bloco("Observação: DESCRIÇÃO DA LOCALIZAÇÃO, O QUE É A ANOMALIA ESTUDADA, E QUAL A RECLAMAÇÃO:", s1)
    _bloco("QUAIS FORAM OS ENSAIOS, METODOLOGIA DA INSPEÇÃO E RESULTADOS DA INSPEÇÃO:", s2)
    _bloco("LITERATURA E NORMAS QUE FUNDAMENTAM O ITEM:", s3)
    _bloco("EXPLICAÇÃO DO MOTIVO DA CLASSIFICAÇÃO DE ANOMALIA:", s4)
    _bloco("DESCRIÇÃO E EXPLICAÇÃO DO MOTIVO DA CLASSIFICAÇÃO DE GRAU DE RISCO (ADICIONA A INFORMAÇÃO DO GUT):", s5, ultimo=True)


def _serializar_gut(dados_gut: dict) -> dict:
    """Serializa resultado GUT para JSON: extrai G/U/T e converte Enums do nexo."""
    result = {
        "G":               dados_gut.get("G"),
        "U":               dados_gut.get("U"),
        "T":               dados_gut.get("T"),
        "prioridade":      dados_gut.get("prioridade"),
        "risco":           str(dados_gut.get("risco","") or ""),
        "subsistema":      str(dados_gut.get("subsistema","") or ""),
        "acao_recomendada":  str(dados_gut.get("acao_recomendada","") or ""),
        "justificativa_G":   str(dados_gut.get("justificativa_G","") or ""),
        "justificativa_U":   str(dados_gut.get("justificativa_U","") or ""),
        "justificativa_T":   str(dados_gut.get("justificativa_T","") or ""),
        "normas_sugeridas":  list(dados_gut.get("normas_sugeridas") or []),
        "fonte":             str(dados_gut.get("fonte","") or ""),
        "confianca":         dados_gut.get("confianca"),
    }
    nexo = dados_gut.get("nexo")
    if nexo is not None:
        if isinstance(nexo, dict):
            result["nexo"] = {
                "origem":      str(nexo.get("origem","") or ""),
                "mecanismo":   str(nexo.get("mecanismo","") or ""),
                "texto_livre": str(nexo.get("texto_livre","") or nexo.get("descricao","") or ""),
            }
        else:
            def _ev(v): return v.value if hasattr(v, "value") else (str(v) if v else "")
            result["nexo"] = {
                "origem":      _ev(getattr(nexo, "origem", "")),
                "mecanismo":   _ev(getattr(nexo, "mecanismo", "")),
                "texto_livre": str(getattr(nexo, "texto_livre", "") or ""),
            }
    return result


class AnalisadorImagem:
    """
    Coordena o fluxo completo de análise de imagens de patologia:
      1. Descrição visual inicial via IA multimodal
      2. GUT Adaptativo interativo (perito responde as perguntas)
      3. Análise IBAPE interativa (perito preenche os campos)
      4. Busca de textos correlatos no banco (automática, baseada nos dados dos módulos)
      5. Consolidação via API (homogeneização, não decisão)
      6. Gravação do resultado e movimentação da imagem

    Cada imagem tem análise independente.
    """

    def __init__(
        self,
        db_manager: Any,
        ai_engine:  Any,
        conn_ibape: Optional[sqlite3.Connection] = None,
        conn_principal_gut: Optional[sqlite3.Connection] = None,
    ):
        self.db         = db_manager
        self.ai         = ai_engine
        self.conn_ibape = conn_ibape
        self.conn_gut   = conn_principal_gut

    # ─────────────────────────────────────────────────────────────────────
    # PONTO DE ENTRADA — processar todas as imagens da pasta
    # ─────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────
    # GESTÃO DE LAUDOS
    # ─────────────────────────────────────────────────────────────────────

    def _selecionar_laudo(self) -> Optional[Dict[str, Any]]:
        """
        Menu inicial: laudo novo ou retomar existente.
        Retorna dict do laudo ativo ou None se cancelado.
        """
        conn = _get_conn_laudos()
        laudos = conn.execute(
            "SELECT * FROM laudos_img WHERE status='aberto' ORDER BY data_edicao DESC LIMIT 20"
        ).fetchall()
        laudos = [dict(r) for r in laudos]
        conn.close()

        print("\n" + "═"*68)
        print("  📋 GESTÃO DE LAUDOS — Análise de Imagens de Patologia")
        print("═"*68)

        if laudos:
            print(f"\n  Laudos em aberto ({len(laudos)}):")
            for i, l in enumerate(laudos, 1):
                print(f"  [{i:2d}] {l['nome_laudo']:<40} | {l['data_edicao'][:10]}")
                if l.get("descricao"):
                    print(f"       {l['descricao'][:60]}")
            print()
            print("  [N] Novo laudo")
            print("  [0] Cancelar")
            print()
            resp = input("  Escolha o número do laudo ou [N] para novo: ").strip().upper()

            if resp == "0":
                return None
            if resp != "N":
                try:
                    idx = int(resp) - 1
                    if 0 <= idx < len(laudos):
                        laudo = laudos[idx]
                        print(f"\n  ✅ Laudo retomado: {laudo['nome_laudo']}")
                        return laudo
                except ValueError:
                    pass
                print("  ⚠️  Opção inválida. Criando novo laudo.")
        else:
            print("\n  Nenhum laudo em aberto. Criando novo.")

        # Criar novo laudo
        return self._criar_laudo()

    def _criar_laudo(self) -> Optional[Dict[str, Any]]:
        """Cria um novo laudo de imagens e o retorna."""
        print("\n  ─── NOVO LAUDO ─────────────────────────────────────────────")
        try:
            nome = input("  Nome do laudo (ex: Laudo 001-2026 Rua das Flores): ").strip()
            if not nome:
                nome = f"Laudo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            descr  = input("  Descrição (ENTER para pular): ").strip()
            perito = input("  Perito responsável (ENTER para pular): ").strip()
        except (EOFError, KeyboardInterrupt):
            nome, descr, perito = f"Laudo_{datetime.now().strftime('%Y%m%d')}", "", ""

        agora = datetime.now().isoformat(timespec="seconds")
        conn  = _get_conn_laudos()
        cur   = conn.execute(
            "INSERT INTO laudos_img (nome_laudo, descricao, perito, data_criacao, data_edicao) "
            "VALUES (?,?,?,?,?)",
            (nome, descr, perito, agora, agora)
        )
        conn.commit()
        lid = cur.lastrowid
        laudo = dict(conn.execute("SELECT * FROM laudos_img WHERE id=?", (lid,)).fetchone())
        conn.close()
        print(f"  ✅ Laudo criado: {nome} (ID {lid})")
        return laudo

    def _registrar_imagem_laudo(self, laudo_id: int, nome: str, imagem_id: str,
                                dados: Dict[str, Any]) -> None:
        """Registra a análise de uma imagem no banco do laudo."""
        import json as _j
        agora = datetime.now().isoformat(timespec="seconds")
        # Serializar dados (excluir objetos não-serializáveis)
        dados_safe = {k: v for k, v in dados.items()
                      if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
        try:
            conn = _get_conn_laudos()
            conn.execute(
                "INSERT OR REPLACE INTO imagens_laudo_img "
                "(laudo_id, nome_imagem, imagem_id, codigo_ibape, grau_risco, dados_json, data_analise) "
                "VALUES (?,?,?,?,?,?,?)",
                (laudo_id, nome, imagem_id,
                 dados.get("codigo_ibape",""), dados.get("grau_risco",""),
                 _j.dumps(dados_safe, ensure_ascii=False)[:8000], agora)
            )
            # Atualizar data_edicao do laudo
            conn.execute("UPDATE laudos_img SET data_edicao=? WHERE id=?", (agora, laudo_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("_registrar_imagem_laudo: %s", e)

    def _encerrar_laudo(self, laudo: Dict[str, Any]) -> None:
        """
        Menu final do laudo: exportar DOCX completo com todas as imagens,
        manter aberto ou encerrar.
        """
        laudo_id = laudo["id"]
        conn = _get_conn_laudos()
        imagens = [dict(r) for r in conn.execute(
            "SELECT * FROM imagens_laudo_img WHERE laudo_id=? ORDER BY id",
            (laudo_id,)
        ).fetchall()]
        conn.close()

        print(f"\n{'═'*68}")
        print(f"  📋 LAUDO: {laudo['nome_laudo']}")
        print(f"  {len(imagens)} imagem(ns) analisada(s) neste laudo")
        print("═"*68)
        print("  O que deseja fazer?")
        print("  [1] Exportar DOCX completo do laudo (todas as imagens)")
        print("  [2] Manter laudo aberto (continuar depois)")
        print("  [3] Encerrar laudo (marca como finalizado)")
        print("  [0] Sair sem alterar")
        op = input("  > ").strip()

        if op == "1":
            print("  ⏳ Gerando DOCX completo do laudo...")
            caminho = self._exportar_docx_laudo_completo(laudo, imagens)
            if caminho:
                print(f"  ✅ DOCX exportado: {caminho}")
            else:
                print("  ⚠️  Falha na exportação. Verifique: pip install python-docx")

        elif op == "3":
            conn = _get_conn_laudos()
            conn.execute("UPDATE laudos_img SET status='finalizado' WHERE id=?", (laudo_id,))
            conn.commit()
            conn.close()
            print(f"  ✅ Laudo '{laudo['nome_laudo']}' marcado como finalizado.")

    def _exportar_docx_laudo_completo(
        self,
        laudo:   Dict[str, Any],
        imagens: List[Dict[str, Any]],
    ) -> str:
        """
        Exporta DOCX com todas as imagens do laudo.
        Cada imagem = 1 tabela no formato do modelo (6 linhas × 5 colunas).
        Entre tabelas: separador com nome da imagem.
        """
        try:
            from docx import Document as DocxDoc
            from docx.shared import Pt, RGBColor, Cm
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
        except ImportError:
            print("  ⚠️  python-docx não instalado: pip install python-docx")
            return ""

        import json as _j

        doc = DocxDoc()
        for sec in doc.sections:
            sec.top_margin = sec.bottom_margin = Cm(2.5)
            sec.left_margin = sec.right_margin = Cm(3.0)

        # ── Capa do laudo ─────────────────────────────────────────────────
        h1 = doc.add_heading("LAUDO PERICIAL — ANÁLISE DE IMAGENS DE PATOLOGIA", level=1)
        h1.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_nome = doc.add_paragraph()
        p_nome.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_nome = p_nome.add_run(laudo["nome_laudo"])
        r_nome.bold = True; r_nome.font.size = Pt(13)
        doc.add_paragraph()
        if laudo.get("descricao"):
            doc.add_paragraph(f"Objeto: {laudo['descricao']}")
        if laudo.get("perito"):
            doc.add_paragraph(f"Perito: {laudo['perito']}")
        doc.add_paragraph(f"Data: {laudo.get('data_criacao','')[:10]}")
        doc.add_paragraph(f"Total de anomalias registradas: {len(imagens)}")
        doc.add_paragraph()

        # ── Uma tabela por imagem ─────────────────────────────────────────
        for idx, img_reg in enumerate(imagens, 1):
            dados = {}
            try:
                dados = _j.loads(img_reg.get("dados_json","{}") or "{}")
            except Exception:
                pass

            # Separador entre imagens
            p_sep = doc.add_paragraph()
            p_sep.add_run(f"Item {idx:02d} — {img_reg['nome_imagem']}").bold = True

            # Chamar o método de tabela individual reutilizando exportar_docx_analise_imagem
            # mas retornando a tabela em vez de salvar um doc separado
            self._adicionar_tabela_imagem(
                doc=doc,
                dados_ibape   = dados.get("ibape", {}),
                dados_gut     = dados.get("gut", {}),
                dados_visual  = dados.get("visual", {}),
                textos_banco  = dados.get("textos_banco", []),
                consolidacao  = dados.get("consolidacao", {}),
                nome_imagem   = img_reg["nome_imagem"],
            )
            doc.add_paragraph()  # espaço entre itens

        # ── Rodapé ────────────────────────────────────────────────────────
        p_rod = doc.add_paragraph()
        p_rod.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r_rod = p_rod.add_run(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} — "
            f"Cérebro de Engenharia Diagnóstica v2.0"
        )
        r_rod.font.size = Pt(8)
        r_rod.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

        pasta_exp = getattr(self, "PASTA_EXPORTACAO", "exportacoes/")
        os.makedirs(pasta_exp, exist_ok=True)
        safe = laudo["nome_laudo"].replace(" ","-").replace("/","-")[:30]
        fname = os.path.join(pasta_exp, f"Laudo_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx")
        doc.save(fname)
        return fname

    def _adicionar_tabela_imagem(
        self, doc, dados_ibape, dados_gut, dados_visual,
        textos_banco, consolidacao, nome_imagem: str,
    ) -> None:
        """Adiciona a tabela de uma imagem (6×5) ao documento existente."""
        try:
            from docx.shared import Pt, RGBColor, Cm, Twips
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
        except ImportError:
            return

        # ── Dados ─────────────────────────────────────────────────────────
        _PLACEHOLDERS = ("Não identificado","A classificar","A identificar","indisponível")
        def _dv(v): s=str(v or ""); return "" if any(t in s for t in _PLACEHOLDERS) else s
        codigo  = dados_ibape.get("codigo_analise") or "—"
        grau    = dados_ibape.get("grau_risco") or dados_gut.get("risco") or ""
        titulo  = dados_ibape.get("titulo") or _dv(dados_visual.get("tipo_provavel")) or ""
        local   = (_dv(dados_visual.get("localizacao_aparente")) or
                   _dv(dados_visual.get("elemento_afetado")) or
                   dados_ibape.get("anomalia_elemento",""))
        origem  = dados_ibape.get("anomalia_origem") or ""
        falha_o = dados_ibape.get("falha_origem") or "-"
        G       = str(dados_gut.get("G") or "-")
        U       = str(dados_gut.get("U") or "-")
        T       = str(dados_gut.get("T") or "-")
        prio    = str(dados_gut.get("prioridade") or "-")

        COR_AZUL = RGBColor(0x1F, 0x49, 0x7D)
        COR_CABE = "D9E1F2"
        # Cores do grau de risco
        COR_GRAU = {"Crítico": "CC0000", "Médio": "FFC000", "Mínimo": "70AD47"}.get(grau, "BFBFBF")

        def _set_shading(cell, fill_hex):
            tc   = cell._tc
            tcPr = tc.find(qn("w:tcPr"))
            if tcPr is None: tcPr = OxmlElement("w:tcPr"); tc.insert(0, tcPr)
            shd  = tcPr.find(qn("w:shd"))
            if shd  is None: shd  = OxmlElement("w:shd");  tcPr.append(shd)
            shd.set(qn("w:val"),  "clear"); shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"), fill_hex.upper())

        def _bold_center(cell, text, size=10, color=None):
            p = cell.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(str(text)); r.bold = True; r.font.size = Pt(size)
            if color: r.font.color.rgb = color

        def _text_cell(cell, text, size=9, bold=False):
            p = cell.paragraphs[0]
            r = p.add_run(str(text)); r.font.size = Pt(size); r.bold = bold

        W = [723, 3358, 1311, 1276, 1826]
        W_TOTAL = sum(W)
        tbl = doc.add_table(rows=6, cols=5)
        tbl.style = "Table Grid"
        tbl.width = Twips(W_TOTAL)
        grid = tbl._tbl.find(qn("w:tblGrid"))
        if grid is None: grid = OxmlElement("w:tblGrid"); tbl._tbl.insert(0, grid)
        else:
            for gc in list(grid): grid.remove(gc)
        for w in W:
            gc = OxmlElement("w:gridCol"); gc.set(qn("w:w"), str(w)); grid.append(gc)
        for row in tbl.rows:
            for c_idx, cell in enumerate(row.cells):
                tcPr = cell._tc.find(qn("w:tcPr"))
                if tcPr is None: tcPr = OxmlElement("w:tcPr"); cell._tc.insert(0, tcPr)
                tcW = tcPr.find(qn("w:tcW"))
                if tcW is None: tcW = OxmlElement("w:tcW"); tcPr.append(tcW)
                tcW.set(qn("w:w"), str(W[c_idx])); tcW.set(qn("w:type"), "dxa")

        # Linha 0 — foto (merge corner-to-corner via API oficial)
        cell_foto = tbl.cell(0, 0).merge(tbl.cell(0, 4))
        caminhos = [
            os.path.join(PASTA_SAIDA,   nome_imagem) if nome_imagem else "",
            os.path.join(PASTA_ENTRADA, nome_imagem) if nome_imagem else "",
        ]
        foto_ok = False
        for cp in caminhos:
            if not cp or not os.path.isfile(cp): continue
            try:
                try:
                    from PIL import Image as _PIL
                    with _PIL.open(cp) as im: w_px, _ = im.size
                    w_cm = min(14.0, w_px / 96 * 2.54)
                except ImportError:
                    w_cm = 14.0
                p_img = cell_foto.paragraphs[0]; p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run_img = p_img.add_run(); run_img.add_picture(cp, width=Cm(w_cm))
                foto_ok = True; break
            except Exception as ef: logger.warning("foto %s: %s", cp, ef)
        if not foto_ok:
            _text_cell(cell_foto, f"Imagem: {nome_imagem} (não localizada)")

        # Linha 1 — cabeçalhos IBAPE
        for c_idx, (cell, hdr) in enumerate(zip(tbl.rows[1].cells,
                ["Item 12","Local","Anomalia","Falha","Grau de risco"])):
            _set_shading(cell, COR_CABE); _bold_center(cell, hdr, 10, COR_AZUL)

        # Linha 2 — dados
        grau_emoji = "🔴" if grau=="Crítico" else ("🟡" if grau=="Médio" else "🟢")
        local_t = f"{local}" + (f"\n{titulo}" if titulo and titulo!=local else "")
        for c_idx, (cell, val) in enumerate(zip(tbl.rows[2].cells,
                [codigo, local_t, origem, falha_o, f"{grau_emoji} {grau}"])):
            if c_idx == 4:
                _set_shading(cell, COR_GRAU)
                _bold_center(cell, val, 10,
                             RGBColor(0xFF,0xFF,0xFF) if grau in ("Crítico","Mínimo") else RGBColor(0x00,0x00,0x00))
            else:
                _text_cell(cell, val)

        # Linha 3 — cabeçalhos GUT
        for c_idx, (cell, hdr) in enumerate(zip(tbl.rows[3].cells,
                ["GUT","G","U","T","Total"])):
            _set_shading(cell, COR_CABE if c_idx<4 else COR_GRAU)
            _bold_center(cell, hdr, 10,
                         COR_AZUL if c_idx<4 else
                         (RGBColor(0xFF,0xFF,0xFF) if grau in ("Crítico","Mínimo") else RGBColor(0x00,0x00,0x00)))

        # Linha 4 — valores GUT
        for c_idx, (cell, val) in enumerate(zip(tbl.rows[4].cells,
                ["GUT", G, U, T, prio])):
            if c_idx == 4:
                _set_shading(cell, COR_GRAU)
                txt_cor = RGBColor(0xFF,0xFF,0xFF) if grau in ("Crítico","Mínimo") else RGBColor(0x00,0x00,0x00)
                _bold_center(cell, val, 12, txt_cor)
            else:
                _bold_center(cell, val, 11)

        # Linha 5 — observação: 5 seções descritivas NBR 13752
        cell_obs = tbl.cell(5, 0).merge(tbl.cell(5, 4))
        p_obs = cell_obs.paragraphs[0]
        _escrever_secoes_observacao(
            p_obs, consolidacao, dados_visual, dados_ibape, dados_gut, textos_banco
        )

    # ─────────────────────────────────────────────────────────────────────
    # PONTO DE ENTRADA — processar todas as imagens da pasta
    # ─────────────────────────────────────────────────────────────────────

    def processar_lote(self) -> int:
        """
        Ponto de entrada principal. Gerencia laudo (novo ou retomada),
        processa cada imagem e oferece exportação final do laudo completo.
        """
        os.makedirs(PASTA_ENTRADA, exist_ok=True)
        os.makedirs(PASTA_SAIDA,   exist_ok=True)
        os.makedirs(PASTA_ERROS,   exist_ok=True)

        # ── Selecionar / criar laudo ───────────────────────────────────────
        laudo = self._selecionar_laudo()
        if laudo is None:
            print("  Operação cancelada.")
            return 0

        self._laudo_ativo = laudo   # tornar disponível em processar_imagem
        self.PASTA_EXPORTACAO = "exportacoes/"

        imagens = _listar_imagens(PASTA_ENTRADA)
        if not imagens:
            print("\n  📂 Nenhuma imagem encontrada em img_patologias_entrada/")
            print("     Coloque as imagens na pasta e execute novamente.")
            self._encerrar_laudo(laudo)
            return 0

        print(f"\n  📸 {len(imagens)} imagem(ns) encontrada(s) em {PASTA_ENTRADA}/")
        print(f"  📋 Laudo ativo: {laudo['nome_laudo']}\n")
        processadas = 0

        for idx, nome in enumerate(imagens, 1):
            caminho = os.path.join(PASTA_ENTRADA, nome)
            print(f"\n{'═'*68}")
            print(f"  IMAGEM {idx}/{len(imagens)}: {nome}")
            print("═"*68)

            try:
                ok = self.processar_imagem(caminho, nome)
                if ok:
                    _mover_imagem(caminho, PASTA_SAIDA, nome)
                    processadas += 1
                    print(f"\n  ✅ Imagem '{nome}' processada e movida para {PASTA_SAIDA}/")
                else:
                    _mover_imagem(caminho, PASTA_ERROS, nome)
                    print(f"\n  ⚠️  Imagem '{nome}' movida para {PASTA_ERROS}/ (incompleta)")
            except KeyboardInterrupt:
                print(f"\n\n  Análise de '{nome}' cancelada.")
                resp = input("  Continuar com próxima imagem? [S/N]: ").strip().upper()
                if resp != "S":
                    break
            except Exception as e:
                logger.error("Erro ao processar '%s': %s", nome, e, exc_info=True)
                print(f"\n  ❌ Erro: {e}")
                _mover_imagem(caminho, PASTA_ERROS, nome)

        print(f"\n{'═'*68}")
        print(f"  RESULTADO: {processadas}/{len(imagens)} imagem(ns) processada(s)")
        print("═"*68)

        # ── Menu final do laudo ────────────────────────────────────────────
        self._encerrar_laudo(laudo)
        return processadas

    # ─────────────────────────────────────────────────────────────────────
    # PROCESSAMENTO DE UMA IMAGEM
    # ─────────────────────────────────────────────────────────────────────

    def processar_imagem(self, caminho: str, nome: str) -> bool:
        """
        Executa o fluxo completo para uma única imagem.
        Retorna True se a análise foi concluída (mesmo parcialmente).
        """
        imagem_id = f"{Path(nome).stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # ── ETAPA 1: Descrição visual inicial ────────────────────────────
        print("\n  ─── ETAPA 1/5 — Análise Visual Inicial ───────────────────")
        if getattr(self.ai, "ia_disponivel", False):
            print("  ⏳ Enviando imagem para análise visual via IA...")
            dados_visual = analisar_imagem_visual(caminho, self.ai)
            # Se IA retornou "Não identificado", trata como falha e pede preenchimento manual
            _falhou = (
                dados_visual.get("tipo_provavel","") in ("Não identificado","") and
                dados_visual.get("elemento_afetado","") in ("Não identificado","")
            )
            if _falhou:
                print("  ⚠️  IA não identificou elementos na imagem — preenchimento manual necessário.")
                dados_visual = self._descricao_manual(nome)
        else:
            print("  ⚠️  IA não configurada. Preencha manualmente.")
            dados_visual = self._descricao_manual(nome)

        print(f"\n  📋 Tipo provável: {dados_visual.get('tipo_provavel','?')}")
        print(f"  📋 Elemento:      {dados_visual.get('elemento_afetado','?')}")
        print(f"  📋 Descrição:     {dados_visual.get('descricao_visual','?')[:120]}")

        # ── ETAPA 2: GUT Adaptativo ───────────────────────────────────────
        print("\n  ─── ETAPA 2/5 — GUT Adaptativo ───────────────────────────")
        dados_gut = self._executar_gut(dados_visual, imagem_id)
        if not dados_gut:
            print("  ⚠️  GUT Adaptativo não concluído — análise marcada como incompleta.")
            dados_gut = {"G": None, "U": None, "T": None, "risco": "Não classificado"}
        else:
            dados_gut = _serializar_gut(dados_gut)

        # ── ETAPA 3: Análise IBAPE ────────────────────────────────────────
        print("\n  ─── ETAPA 3/5 — Análise IBAPE ────────────────────────────")
        dados_ibape = self._executar_ibape(dados_visual, dados_gut, imagem_id)
        if not dados_ibape:
            print("  ⚠️  Análise IBAPE não concluída — análise marcada como incompleta.")
            dados_ibape = {}

        # Anexar dados visuais ao ibape para uso na consolidação e no DOCX
        dados_ibape["_descricao_visual"]        = dados_visual.get("descricao_visual", "")
        dados_ibape["_tipo_provavel"]            = dados_visual.get("tipo_provavel", "")
        dados_ibape["_elemento_afetado"]         = dados_visual.get("elemento_afetado", "")
        dados_ibape["_observacoes_preliminares"] = dados_visual.get("observacoes_preliminares", "")
        # Guardar nome da imagem para localizar o arquivo no DOCX
        dados_ibape["_nome_imagem"]              = nome
        dados_visual["_nome_imagem"]             = nome

        # ── ETAPA 4: Busca no banco ────────────────────────────────────────
        print("\n  ─── ETAPA 4/5 — Busca de Textos Correlatos no Banco ──────")
        print("  ⏳ Consultando banco com base nos dados dos módulos...")
        textos_banco = buscar_textos_correlatos(
            self.db, dados_gut, dados_ibape,
            descricao_visual=dados_visual.get("descricao_visual", ""),
            n=8,
        )

        # Incluir trechos referenciados pelo perito no módulo IBAPE (topicos_banco)
        _ids_ibape = []
        _tb_raw = dados_ibape.get("topicos_banco") or []
        if isinstance(_tb_raw, str):
            try:
                import json as _j; _ids_ibape = _j.loads(_tb_raw)
            except Exception:
                pass
        elif isinstance(_tb_raw, list):
            _ids_ibape = _tb_raw
        if _ids_ibape:
            _ids_ja = {t.get("id") for t in textos_banco if t.get("id")}
            _extras = [t for t in _fetch_topicos_by_ids(self.db, _ids_ibape)
                       if t.get("id") not in _ids_ja]
            textos_banco = _extras + textos_banco  # referências do perito primeiro

        print(f"  📚 {len(textos_banco)} texto(s) correlato(s) recuperado(s).")
        for i, t in enumerate(textos_banco[:3], 1):
            print(f"     [{i}] {t.get('nome_arquivo','?')[:40]} | {t.get('titulo_topico','')[:40]}")

        # ── ETAPA 5: Consolidação ─────────────────────────────────────────
        # A consolidação ocorre sempre — com IA (enriquecida) ou sem (offline).
        # No modo offline, os dados dos módulos são suficientes para montar
        # uma consolidação técnica estruturada sem qualquer chamada de API.
        print("\n  ─── ETAPA 5/5 — Consolidação Técnica ─────────────────────")
        if getattr(self.ai, "ia_disponivel", False):
            print("  ⏳ Consolidando via API...")
            consolidacao = consolidar_via_api(
                imagem_id, dados_gut, dados_ibape, textos_banco, self.ai
            )
            print(f"  ✅ Consolidação concluída — confiança: {consolidacao.get('nivel_de_confianca','?')}")
        else:
            print("  ℹ️  Modo offline — consolidação gerada a partir dos módulos GUT + IBAPE.")
            consolidacao = _consolidar_offline(imagem_id, dados_gut, dados_ibape, textos_banco)
            print(f"  ✅ Consolidação offline concluída.")

        # ── GRAVAÇÃO ──────────────────────────────────────────────────────
        self._gravar_resultado(imagem_id, nome, dados_visual, dados_gut, dados_ibape,
                               textos_banco, consolidacao)

        # ── REGISTRAR NO LAUDO ATIVO ──────────────────────────────────────
        laudo_ativo = getattr(self, "_laudo_ativo", None)
        if laudo_ativo:
            import json as _j
            dados_reg = {
                "ibape":        {k:v for k,v in dados_ibape.items()
                                 if not k.startswith("_") and isinstance(v,(str,int,float,bool,list,dict,type(None)))},
                "gut":          _serializar_gut(dados_gut),
                "visual":        dados_visual,
                "textos_banco":  textos_banco[:8],
                "consolidacao":  {k:v for k,v in consolidacao.items()
                                  if isinstance(v, (str,int,float,bool,list,type(None)))},
                "codigo_ibape":  dados_ibape.get("codigo_analise",""),
                "grau_risco":    dados_ibape.get("grau_risco","") or dados_gut.get("risco",""),
            }
            self._registrar_imagem_laudo(laudo_ativo["id"], nome, imagem_id, dados_reg)

        # ── EXIBIÇÃO FINAL ────────────────────────────────────────────────
        self._exibir_resultado_final(consolidacao, dados_gut, dados_ibape)

        # ── MELHORIA 5: menu pós-análise ──────────────────────────────────
        # Passar todas as etapas para o menu para gerar o DOCX completo
        self._menu_pos_analise(
            dados_ibape=dados_ibape,
            nome_imagem=nome,
            caminho_imagem=caminho,
            dados_gut=dados_gut,
            dados_visual=dados_visual,
            textos_banco=textos_banco,
            consolidacao=consolidacao,
        )

        return True

    # ─────────────────────────────────────────────────────────────────────
    # MELHORIA 5 — MENU PÓS-ANÁLISE
    # ─────────────────────────────────────────────────────────────────────

    def exportar_docx_analise_imagem(
        self,
        dados_ibape:    dict,
        dados_gut:      dict,
        dados_visual:   dict,
        textos_banco:   list,
        consolidacao:   dict,
        caminho_imagem: str = "",
    ) -> str:
        """
        Gera DOCX com layout tabular baseado no Modelo_de_layout.docx:
          • Tabela 5 colunas: Item | Local | Anomalia | Falha | Grau de Risco
          • Linha 0 (foto): imagem da patologia centralizada
          • Linha 1 (cabeçalhos): Item 12 | Local | Anomalia | Falha | Grau de risco
          • Linha 2 (dados): nº | localização | origem | falha | grau GUT
          • Linha 3 (GUT header): GUT | G | U | T | Total (coluna Total = vermelho)
          • Linha 4 (GUT valores): GUT | G val | U val | T val | Prioridade (vermelho)
          • Linha 5 (observação): texto completo da análise IBAPE (mescla todas as colunas)

        Larguras das colunas (A4, margens 3cm): ~723 | 3358 | 1311 | 1276 | 1826 DXA
        """
        try:
            from docx import Document as DocxDoc
            from docx.shared import Pt, RGBColor, Cm, Inches
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
            from lxml import etree
        except ImportError:
            print("  ⚠️  python-docx não instalado: pip install python-docx")
            return ""

        # ── Dados ─────────────────────────────────────────────────────────
        _PLACEHOLDERS = ("Não identificado","A classificar","A identificar","indisponível")
        def _dv(v): s=str(v or ""); return "" if any(t in s for t in _PLACEHOLDERS) else s
        codigo  = dados_ibape.get("codigo_analise") or "IBAPE-IMG"
        grau    = dados_ibape.get("grau_risco") or dados_gut.get("risco") or ""
        titulo  = dados_ibape.get("titulo") or _dv(dados_visual.get("tipo_provavel")) or "Análise"
        local   = (_dv(dados_visual.get("localizacao_aparente")) or
                   _dv(dados_visual.get("elemento_afetado")) or
                   dados_ibape.get("anomalia_elemento",""))
        origem  = dados_ibape.get("anomalia_origem") or ""
        falha_o = dados_ibape.get("falha_origem") or "-"
        G       = str(dados_gut.get("G") or "-")
        U       = str(dados_gut.get("U") or "-")
        T       = str(dados_gut.get("T") or "-")
        prio    = str(dados_gut.get("prioridade") or "-")

        COR_AZUL  = RGBColor(0x1F, 0x49, 0x7D)
        COR_CINZA = RGBColor(0xBF, 0xBF, 0xBF)
        COR_VERM  = "EE0000"
        COR_CABE  = "D9E1F2"  # azul claro cabeçalho

        # ── Documento ─────────────────────────────────────────────────────
        doc = DocxDoc()
        for sec in doc.sections:
            sec.top_margin = sec.bottom_margin = Cm(2.5)
            sec.left_margin = sec.right_margin = Cm(3.0)

        def _set_shading(cell, fill_hex: str):
            tc   = cell._tc
            tcPr = tc.find(qn("w:tcPr"))
            if tcPr is None:
                tcPr = OxmlElement("w:tcPr"); tc.insert(0, tcPr)
            shd = tcPr.find(qn("w:shd"))
            if shd is None:
                shd = OxmlElement("w:shd"); tcPr.append(shd)
            shd.set(qn("w:val"),   "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"),  fill_hex.upper())

        def _bold_center(cell, text: str, size: int = 10, color: RGBColor = None):
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(str(text))
            run.bold = True
            run.font.size = Pt(size)
            if color: run.font.color.rgb = color

        def _text_cell(cell, text: str, size: int = 10, bold: bool = False):
            p = cell.paragraphs[0]
            run = p.add_run(str(text))
            run.font.size = Pt(size)
            run.bold = bold

        def _merge_row(table, row_idx: int, ncols: int):
            """Mescla células via API oficial python-docx (corner-to-corner)."""
            # table.cell(r,0).merge(table.cell(r,n-1)) é a forma correta e confiável.
            # Produz o XML exato que o Word espera: gridSpan + tcW correto em 1 célula.
            return table.cell(row_idx, 0).merge(table.cell(row_idx, ncols - 1))

        # ── Larguras (A4 - 2*3cm = 15cm = ~8494 DXA total) ────────────────
        # Modelo: 723 | 3358 | 1311 | 1276 | 1826
        W_TOTAL = 8494
        W = [723, 3358, 1311, 1276, 1826]

        # ── Tabela principal: 6 linhas × 5 colunas ────────────────────────
        tbl = doc.add_table(rows=6, cols=5)
        tbl.style = "Table Grid"
        from docx.shared import Twips
        tbl.width = Twips(W_TOTAL)
        # Definir larguras das colunas via tblGrid
        grid = tbl._tbl.find(qn("w:tblGrid"))
        if grid is None:
            grid = OxmlElement("w:tblGrid")
            tbl._tbl.insert(0, grid)
        else:
            for gc in list(grid): grid.remove(gc)
        for w in W:
            gc = OxmlElement("w:gridCol")
            gc.set(qn("w:w"), str(w))
            grid.append(gc)
        # Largura individual de cada célula
        for row in tbl.rows:
            for c_idx, cell in enumerate(row.cells):
                tcPr = cell._tc.find(qn("w:tcPr"))
                if tcPr is None:
                    tcPr = OxmlElement("w:tcPr"); cell._tc.insert(0, tcPr)
                tcW = tcPr.find(qn("w:tcW"))
                if tcW is None:
                    tcW = OxmlElement("w:tcW"); tcPr.append(tcW)
                tcW.set(qn("w:w"),    str(W[c_idx]))
                tcW.set(qn("w:type"), "dxa")

        # ─── LINHA 0 — FOTO ────────────────────────────────────────────────
        cell_foto = _merge_row(tbl, 0, 5)
        nome_img  = dados_visual.get("_nome_imagem") or dados_ibape.get("_nome_imagem") or ""
        caminhos  = [
            caminho_imagem,
            os.path.join(PASTA_SAIDA,   nome_img) if nome_img else "",
            os.path.join(PASTA_ENTRADA, nome_img) if nome_img else "",
        ]
        foto_inserida = False
        for cp in caminhos:
            if not cp or not os.path.isfile(cp): continue
            try:
                try:
                    from PIL import Image as _PIL
                    with _PIL.open(cp) as im: w_px, h_px = im.size
                    # Calcular: max 14cm largura, proporção mantida
                    w_cm = min(14.0, w_px / 96 * 2.54)
                    h_cm = h_px / w_px * w_cm
                except ImportError:
                    w_cm, h_cm = 14.0, 10.5
                p_img = cell_foto.paragraphs[0]
                p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run_img = p_img.add_run()
                from docx.shared import Cm as _Cm
                run_img.add_picture(cp, width=_Cm(w_cm))
                foto_inserida = True
                break
            except Exception as e_f:
                logger.warning("Foto: %s", e_f)
        if not foto_inserida:
            _text_cell(cell_foto, f"⚠️  Foto não localizada: {nome_img or caminho_imagem}")

        # ─── LINHA 1 — CABEÇALHOS ──────────────────────────────────────────
        hdrs = ["Item 12", "Local", "Anomalia", "Falha", "Grau de risco"]
        for c_idx, (cell, hdr) in enumerate(zip(tbl.rows[1].cells, hdrs)):
            _set_shading(cell, COR_CABE)
            _bold_center(cell, hdr, size=10, color=COR_AZUL)

        # ─── LINHA 2 — DADOS IBAPE ─────────────────────────────────────────
        grau_emoji = "🔴" if grau == "Crítico" else ("🟡" if grau == "Médio" else "🟢")
        local_titulo = f"{local}" + (f"\n{titulo}" if titulo and titulo != local else "")
        row2_vals = [codigo, local_titulo, origem, falha_o, f"{grau_emoji} {grau}"]
        # Cor da célula grau: vermelho=Crítico, amarelo=Médio, verde=Mínimo
        COR_GRAU = {"Crítico": "CC0000", "Médio": "FFC000", "Mínimo": "70AD47"}.get(grau, "BFBFBF")
        COR_TXT_GRAU = RGBColor(0xFF,0xFF,0xFF) if grau in ("Crítico","Mínimo") else RGBColor(0x00,0x00,0x00)
        for c_idx, (cell, val) in enumerate(zip(tbl.rows[2].cells, row2_vals)):
            if c_idx == 4:
                _set_shading(cell, COR_GRAU)
                _bold_center(cell, val, size=10, color=COR_TXT_GRAU)
            else:
                _text_cell(cell, val, size=9)

        # ─── LINHA 3 — CABEÇALHOS GUT ─────────────────────────────────────
        gut_hdrs = ["GUT", "G", "U", "T", "Total"]
        for c_idx, (cell, hdr) in enumerate(zip(tbl.rows[3].cells, gut_hdrs)):
            _set_shading(cell, COR_CABE if c_idx < 4 else COR_GRAU)
            _bold_center(cell, hdr, size=10,
                         color=COR_AZUL if c_idx < 4 else COR_TXT_GRAU)

        # ─── LINHA 4 — VALORES GUT ────────────────────────────────────────
        gut_vals = ["GUT", G, U, T, prio]
        for c_idx, (cell, val) in enumerate(zip(tbl.rows[4].cells, gut_vals)):
            if c_idx == 4:
                _set_shading(cell, COR_GRAU)
                _bold_center(cell, val, size=12, color=COR_TXT_GRAU)
            else:
                _bold_center(cell, val, size=11)

        # ─── LINHA 5 — OBSERVAÇÃO: 5 seções descritivas NBR 13752 ──────────
        cell_obs = _merge_row(tbl, 5, 5)
        p_obs = cell_obs.paragraphs[0]
        _escrever_secoes_observacao(
            p_obs, consolidacao, dados_visual, dados_ibape, dados_gut, textos_banco
        )

        # ── Rodapé ──────────────────────────────────────────────────────
        doc.add_paragraph()
        p_rod = doc.add_paragraph()
        p_rod.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r_rod = p_rod.add_run(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} — "
            f"Cérebro de Engenharia Diagnóstica v2.0 | {codigo}"
        )
        r_rod.font.size = Pt(8)
        r_rod.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

        # ── Salvar ────────────────────────────────────────────────────────
        pasta_exp = getattr(self, "PASTA_EXPORTACAO", "exportacoes/")
        os.makedirs(pasta_exp, exist_ok=True)
        data_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_cod = codigo.replace("/","-").replace(":","")
        fname = os.path.join(pasta_exp, f"AnaliseIMG_{safe_cod}_{data_str}.docx")
        doc.save(fname)
        return fname


    def _menu_pos_analise(
        self,
        dados_ibape:    Dict[str, Any],
        nome_imagem:    str,
        caminho_imagem: str = "",
        dados_gut:      Dict[str, Any] = None,
        dados_visual:   Dict[str, Any] = None,
        textos_banco:   list = None,
        consolidacao:   Dict[str, Any] = None,
    ) -> None:
        """
        Menu pós-análise: exportar relatório DOCX completo (foto + GUT + IBAPE
        + textos do banco + consolidação), editar no módulo IBAPE, ou continuar.
        """
        codigo = dados_ibape.get("codigo_analise", "")
        print(f"\n{'─'*68}")
        print(f"  ✅ Análise da imagem '{nome_imagem}' concluída.")
        if codigo:
            print(f"     Código IBAPE: {codigo}")
        print(f"{'─'*68}")
        print("  O que deseja fazer agora?")
        print("  [1] Exportar relatório completo em DOCX (foto + GUT + IBAPE + banco)")
        print("  [2] Editar análise IBAPE (abrir módulo)")
        print("  [0] Continuar (próxima imagem ou encerrar)")
        op = input("  > ").strip()

        if op == "1":
            print("  ⏳ Gerando DOCX completo...")
            caminho = self.exportar_docx_analise_imagem(
                dados_ibape    = dados_ibape,
                dados_gut      = dados_gut    or {},
                dados_visual   = dados_visual or {},
                textos_banco   = textos_banco or [],
                consolidacao   = consolidacao or {},
                caminho_imagem = caminho_imagem,
            )
            if caminho:
                print(f"\n  ✅ Relatório completo exportado: {caminho}")
            else:
                print("\n  ⚠️  Exportação não concluída. Verifique: pip install python-docx")
        elif op == "2":
            try:
                from analise_ibape import AnaliseIBAPE, inicializar_banco
                conn_ib = inicializar_banco(DB_IBAPE)
                modulo  = AnaliseIBAPE(conn_ib, self.db)
                print(f"\n  ℹ️  Abrindo módulo IBAPE. Use [5] Editar e informe o código {codigo}.")
                modulo.executar()
                conn_ib.close()
            except Exception as e:
                print(f"  ⚠️  Não foi possível abrir o módulo IBAPE: {e}")
        # op == "0" ou outro: continua normalmente


    # ─────────────────────────────────────────────────────────────────────
    # ETAPA 2 — GUT ADAPTATIVO
    # ─────────────────────────────────────────────────────────────────────

    def _executar_gut(
        self,
        dados_visual: Dict[str, Any],
        imagem_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Instancia o GUT Adaptativo com a descrição visual como ponto de partida.
        O perito responde as perguntas normalmente — fluxo idêntico ao [gut_adaptativo].
        """
        try:
            from gut_adaptativo import GUTAdaptativo

            descricao = (
                f"{dados_visual.get('tipo_provavel','Anomalia')} em "
                f"{dados_visual.get('elemento_afetado','elemento não identificado')} — "
                f"{dados_visual.get('descricao_visual','')[:150]}"
            ).strip(" —")

            # Sugestão para NC4 baseada na descrição visual
            _triviais = {"sim","não","nao","ok","s","n","","não sei","ns","sem indicios","sem indícios"}
            nexo_sugerido = ""
            for campo in ["subtipo", "descricao_visual", "indicios_progressao"]:
                v = (dados_visual.get(campo) or "").strip()
                if v.lower() not in _triviais and len(v) > 5:
                    nexo_sugerido = v[:150]
                    break

            if nexo_sugerido:
                print(
                    f"\n  ℹ️  NC4 (causa raiz) — sugestão baseada na descrição visual:\n"
                    f"     \"{nexo_sugerido}\"\n"
                    f"     Quando o GUT solicitar 'Descreva a causa raiz', pressione\n"
                    f"     ENTER para aceitar ou edite conforme necessário."
                )

            conn = self.conn_gut or self.db.get_connection()
            try:
                engine = GUTAdaptativo(
                    conn=conn,
                    ai_engine=self.ai,
                    db_manager=self.db,
                )
                # Forçar TREINAMENTO COMPLETO para análise de imagens:
                # cada imagem pode ter uma anomalia com G, U e T distintos.
                # SEMI_AUTONOMO usa histórico para preencher U e T
                # automaticamente, o que é incorreto — o perito deve avaliar
                # todas as 12 dimensões para garantir classificação correta.
                resultado = engine.avaliar(descricao, forcar_modo="TREINAMENTO")
                if not isinstance(resultado, dict):
                    return None
                # Recuperar ID do último registro salvo no gut_historico
                # (gut_adaptativo salva mas não coloca o ID no resultado_final)
                if not resultado.get("historico_id"):
                    try:
                        _cur = conn.cursor()
                        _row = _cur.execute(
                            "SELECT id FROM gut_historico ORDER BY id DESC LIMIT 1"
                        ).fetchone()
                        if _row:
                            resultado["historico_id"] = _row[0]
                    except Exception:
                        pass
                return resultado
            finally:
                if not self.conn_gut:
                    conn.close()

        except ImportError:
            print("  ⚠️  gut_adaptativo.py não encontrado.")
            return self._gut_manual()
        except Exception as e:
            logger.error("Erro no GUT Adaptativo: %s", e)
            print(f"  ❌ Erro no GUT Adaptativo: {e}")
            return self._gut_manual()

    def _gut_manual(self) -> Dict[str, Any]:
        """
        Coleta GUT manualmente quando o módulo não está disponível.
        Valores padrão aplicados se o perito pressionar ENTER.
        Nunca trava — em caso de erro retorna estrutura com valores neutros.
        """
        print("  Informe os valores GUT (ENTER em qualquer campo usa valor padrão):")
        try:
            def _int_input(prompt: str, default: int) -> int:
                try:
                    v = input(f"  {prompt}").strip()
                    return int(v) if v else default
                except (ValueError, EOFError, KeyboardInterrupt):
                    return default

            G = max(1, min(10, _int_input("G — Gravidade   (1-10, padrão 3): ", 3)))
            U = max(1, min(10, _int_input("U — Urgência    (1-10, padrão 3): ", 3)))
            T = max(1, min(10, _int_input("T — Tendência   (1-10, padrão 3): ", 3)))
            try:
                risco = input("  Risco (Crítico/Médio/Mínimo, ENTER=Médio): ").strip() or "Médio"
            except (EOFError, KeyboardInterrupt):
                risco = "Médio"
            return {"G": G, "U": U, "T": T, "prioridade": G*U*T, "risco": risco,
                    "fonte": "manual", "confianca": 0.5}
        except Exception as e:
            logger.warning("_gut_manual: fallback por erro: %s", e)
            return {"G": 3, "U": 3, "T": 3, "prioridade": 27, "risco": "Médio",
                    "fonte": "manual", "confianca": 0.3}

    # ─────────────────────────────────────────────────────────────────────
    # ETAPA 3 — ANÁLISE IBAPE
    # ─────────────────────────────────────────────────────────────────────

    def _executar_ibape(
        self,
        dados_visual: Dict[str, Any],
        dados_gut:    Dict[str, Any],
        imagem_id:    str,
    ) -> Optional[Dict[str, Any]]:
        """
        Instancia a Análise IBAPE com pré-preenchimento completo dos dados
        do GUT e da descrição visual. O perito revisa e complementa.
        """
        try:
            from analise_ibape import AnaliseIBAPE, inicializar_banco

            conn_ib = self.conn_ibape or inicializar_banco(DB_IBAPE)
            try:
                modulo = AnaliseIBAPE(conn_ib, self.db)

                # Extrair nexo causal do GUT
                nexo_gut   = dados_gut.get("nexo") or {}
                nexo_texto = ""
                if isinstance(nexo_gut, dict):
                    nexo_texto = str(nexo_gut.get("texto_livre","") or nexo_gut.get("descricao","") or "")
                if not nexo_texto:
                    nexo_texto = dados_visual.get("indicios_progressao","") or ""

                # Mapear origem GUT → IBAPE para pré-preencher anomalia_origem
                # Evita que o IBAPE pergunte novamente o que já foi respondido no GUT
                # Map GUT origin (Enum or dict) → IBAPE anomalia_origem
                def _map_origem(nexo_gut):
                    raw = ""
                    if isinstance(nexo_gut, dict):
                        raw = str(nexo_gut.get("origem","") or "")
                    elif nexo_gut is not None:
                        attr = getattr(nexo_gut,"origem",None)
                        raw = (attr.value if hasattr(attr,"value") else str(attr)) if attr else ""
                    r = raw.lower().replace("ê","e").replace("ó","o").replace("â","a")
                    if r.startswith("end"): return "Endógena"
                    if r.startswith("exo") or r.startswith("exó"): return "Exógena"
                    if r.startswith("nat"): return "Natural"
                    if r.startswith("fun"): return "Funcional"
                    return ""
                anomalia_origem = _map_origem(nexo_gut)

                # Filtrar placeholders de falha da IA antes de pré-preencher IBAPE
                def _vv(val):
                    """Retorna vazio se val for placeholder de falha da IA."""
                    s = str(val or "")
                    if any(t in s for t in ("Não identificado","A classificar","A identificar",
                                            "indisponível","API retornou","Não avaliado")):
                        return ""
                    return s

                pre_dados = {
                    "titulo":             (
                        f"{_vv(dados_visual.get('tipo_provavel',''))} — "
                        f"{_vv(dados_visual.get('elemento_afetado',''))} — "
                        f"{_vv(dados_visual.get('localizacao_aparente',''))}"
                    ).strip(" —")[:200] or "Nova análise",
                    "anomalia_origem":    anomalia_origem,   # vem do GUT — sem re-pergunta
                    "anomalia_descricao": _vv(dados_visual.get("descricao_visual","")),
                    "anomalia_sintomas":  _vv(
                        f"{dados_visual.get('subtipo','')}. "
                        f"{dados_visual.get('indicios_progressao','')}"
                    ).strip(". "),
                    "anomalia_elemento":  _vv(dados_visual.get("elemento_afetado","")),
                    "anomalia_sistema":   dados_gut.get("subsistema",""),
                    "nexo_causal":        nexo_texto,
                    "grau_risco":         {"Crítico": "Crítico", "Alto": "Médio",
                                          "Médio": "Mínimo", "Baixo": "Mínimo"}.get(
                                              dados_gut.get("risco", ""), ""),
                    "acao_recomendada":   dados_gut.get("acao_recomendada",""),
                    "grau_justificativa": " | ".join(filter(None, [
                        dados_gut.get("justificativa_G",""),
                        dados_gut.get("justificativa_U",""),
                        dados_gut.get("justificativa_T",""),
                    ])),
                    "G_gut":              dados_gut.get("G"),
                    "U_gut":              dados_gut.get("U"),
                    "T_gut":              dados_gut.get("T"),
                    "prioridade_gut":     dados_gut.get("prioridade"),
                    "gut_historico_id":   dados_gut.get("historico_id"),
                    "status":             "rascunho",
                }

                risco_gut = dados_gut.get("risco","?")
                print(
                    f"\n  ℹ️  Campos pré-preenchidos para o módulo IBAPE:\n"
                    f"     Título:     {pre_dados['titulo'][:60]}\n"
                    f"     Elemento:   {dados_visual.get('elemento_afetado','?')}\n"
                    f"     Subsistema: {dados_gut.get('subsistema','?')}\n"
                    f"     Risco GUT:  {risco_gut} "
                    f"(G={dados_gut.get('G','?')} U={dados_gut.get('U','?')} T={dados_gut.get('T','?')})\n"
                    f"     Nexo:       {nexo_texto[:80] or 'não preenchido'}\n"
                    f"\n  Pressione ENTER para confirmar cada campo ou edite conforme necessário."
                )
                input("  [ENTER] para iniciar o módulo IBAPE...")

                cursor = conn_ib.cursor()
                cursor.execute("SELECT COALESCE(MAX(id),0) FROM analises_ibape")
                id_antes = cursor.fetchone()[0]

                modulo.executar(pre_dados=pre_dados)

                cursor.execute("SELECT * FROM analises_ibape WHERE id > ?", (id_antes,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None

            finally:
                if not self.conn_ibape:
                    conn_ib.close()

        except ImportError:
            print("  ⚠️  analise_ibape.py não encontrado.")
            return self._ibape_manual(dados_visual, dados_gut)
        except Exception as e:
            logger.error("Erro na Análise IBAPE: %s", e)
            print(f"  ❌ Erro na Análise IBAPE: {e}")
            return self._ibape_manual(dados_visual, dados_gut)

    def _ibape_manual(
        self,
        dados_visual: Dict[str, Any],
        dados_gut:    Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Coleta dados IBAPE manualmente quando o módulo não está disponível.
        Todos os campos são opcionais — ENTER aceita o valor sugerido.
        Salva no banco IBAPE para gerar codigo_analise correto.
        """
        print("  Informe os dados IBAPE (ENTER em qualquer campo usa o valor sugerido):\n")

        def _ask(prompt: str, default: str = "") -> str:
            hint = f" [{default[:40]}]" if default else ""
            try:
                v = input(f"  {prompt}{hint}: ").strip()
                return v if v else default
            except (EOFError, KeyboardInterrupt):
                return default

        origem   = _ask("Origem (Endógena/Exógena/Natural/Funcional)", "Endógena")
        natureza = _ask("Natureza (Vício Construtivo/Avaria/Decrepitude)",
                        "Vício Construtivo" if origem == "Endógena" else "A Classificar")
        descr    = _ask("Descrição da anomalia",
                        dados_visual.get("descricao_visual","")[:80])
        nexo     = _ask("Nexo causal",
                        dados_visual.get("indicios_progressao","")[:80])

        analise_dict = {
            "anomalia_origem":    origem,
            "anomalia_natureza":  natureza,
            "anomalia_elemento":  dados_visual.get("elemento_afetado",""),
            "anomalia_sistema":   dados_gut.get("subsistema",""),
            "anomalia_descricao": descr or dados_visual.get("descricao_visual",""),
            "anomalia_sintomas":  dados_visual.get("subtipo",""),
            "nexo_causal":        nexo,
            "grau_risco":         dados_gut.get("risco","Médio"),
            "acao_recomendada":   dados_gut.get("acao_recomendada",""),
            "G_gut":              dados_gut.get("G"),
            "U_gut":              dados_gut.get("U"),
            "T_gut":              dados_gut.get("T"),
            "prioridade_gut":     dados_gut.get("prioridade"),
            "status":             "rascunho",
        }

        # Salvar no banco para gerar codigo_analise correto (IBAPE-2026-0001)
        try:
            from analise_ibape import inicializar_banco, salvar_analise
            conn_ib = inicializar_banco(DB_IBAPE)
            analise_id = salvar_analise(conn_ib, analise_dict)
            cursor = conn_ib.cursor()
            cursor.execute("SELECT * FROM analises_ibape WHERE id = ?", (analise_id,))
            row = cursor.fetchone()
            conn_ib.close()
            if row:
                return dict(row)
        except Exception as e:
            logger.warning("_ibape_manual: não foi possível salvar no banco: %s", e)

        return analise_dict

    
    # ─────────────────────────────────────────────────────────────────────
    # DESCRIÇÃO MANUAL (quando IA não disponível)
    # ─────────────────────────────────────────────────────────────────────

    def _descricao_manual(self, nome: str) -> Dict[str, Any]:
        """
        Coleta descrição visual manualmente quando IA está offline ou falhou.
        Exibe análises anteriores como referência para agilizar o preenchimento.
        """
        print(f"\n  Descreva visualmente a anomalia observada na imagem '{nome}':")

        # ── Sugestões de análises anteriores ──────────────────────────────
        anteriores = []
        try:
            from analise_ibape import inicializar_banco as _init_ib
            _conn_ib = self.conn_ibape or _init_ib(DB_IBAPE)
            _cur = _conn_ib.cursor()
            _cur.execute("""
                SELECT titulo, anomalia_sistema, anomalia_elemento,
                       anomalia_origem, anomalia_sintomas
                FROM analises_ibape
                ORDER BY id DESC LIMIT 5
            """)
            anteriores = _cur.fetchall()
        except Exception:
            pass

        base = {}
        if anteriores:
            print("\n  📋 Análises anteriores — use como referência ou como base:")
            for i, r in enumerate(anteriores, 1):
                print(f"  [{i}] {(r[0] or '')[:55]} | {r[1] or ''} | {r[2] or ''}")
            print("  [0] Preencher do zero")
            try:
                resp = input("  Usar análise como base [1-5] ou [0] manual: ").strip()
                if resp.isdigit() and 1 <= int(resp) <= len(anteriores):
                    r = anteriores[int(resp) - 1]
                    base = {
                        "tipo_provavel":    r[0] or "",
                        "elemento_afetado": r[2] or "",
                        "indicios_progressao": r[4] or "",
                    }
                    print(f"  ✓ Base carregada: {(r[0] or '')[:50]}")
            except (EOFError, KeyboardInterrupt):
                pass

        print("  (Pressione ENTER para usar sugestão entre colchetes ou pular)\n")

        def _ask(prompt: str, default: str = "") -> str:
            hint = f" [{default[:40]}]" if default else ""
            try:
                val = input(f"  {prompt}{hint}: ").strip()
                return val if val else default
            except (EOFError, KeyboardInterrupt):
                return default

        tipo        = _ask("Tipo provável (ex: fissura, infiltração)", base.get("tipo_provavel",""))
        subtipo     = _ask("Subtipo (ex: fissura diagonal)")
        elemento    = _ask("Elemento afetado (ex: laje, pilar)", base.get("elemento_afetado",""))
        localizacao = _ask("Localização (ex: canto superior direito)")
        descricao   = _ask("Descrição da anomalia", base.get("tipo_provavel",""))
        indicios    = _ask("Indícios de progressão", base.get("indicios_progressao",""))

        return {
            "descricao_visual":         descricao or f"Imagem: {nome}",
            "tipo_provavel":            tipo or "A classificar",
            "subtipo":                  subtipo,
            "elemento_afetado":         elemento or "A identificar",
            "localizacao_aparente":     localizacao,
            "indicios_progressao":      indicios,
            "observacoes_preliminares": "Descrição inserida manualmente (modo offline).",
        }

    # ─────────────────────────────────────────────────────────────────────
    # GRAVAÇÃO NO BANCO PRINCIPAL
    # ─────────────────────────────────────────────────────────────────────

    def _gravar_resultado(
        self,
        imagem_id:    str,
        nome_arquivo: str,
        dados_visual: Dict,
        dados_gut:    Dict,
        dados_ibape:  Dict,
        textos_banco: List[Dict],
        consolidacao: Dict,
    ) -> None:
        """
        Grava o tópico completo no banco principal com todos os dados integrados.
        Texto original = descrição visual.
        Texto reescrito = consolidação técnica da API.
        Palavras-chave = termos-âncora extraídos dos módulos.
        """
        try:
            laudo_id = (
                self.db.buscar_laudo_por_nome(nome_arquivo) or
                self.db.registrar_laudo(nome_arquivo, tipo_fonte="laudo_judicial")
            )

            texto_orig = (
                f"IMAGEM: {nome_arquivo}\n"
                f"ID: {imagem_id}\n\n"
                f"DESCRIÇÃO VISUAL:\n{dados_visual.get('descricao_visual','')}\n\n"
                f"TIPO PROVÁVEL: {dados_visual.get('tipo_provavel','')}\n"
                f"ELEMENTO: {dados_visual.get('elemento_afetado','')}\n"
                f"INDÍCIOS DE PROGRESSÃO: {dados_visual.get('indicios_progressao','')}"
            )

            texto_reesc = (
                f"{consolidacao.get('consolidacao_tecnica','')}\n\n"
                f"TIPO CONSOLIDADO: {consolidacao.get('tipo_anomalia_consolidado','')}\n"
                f"CONFIANÇA: {consolidacao.get('nivel_de_confianca','?')}\n"
                f"INSPEÇÃO COMPLEMENTAR: "
                f"{'Necessária' if consolidacao.get('necessita_inspecao_complementar') else 'Não necessária'}"
            )

            # Palavras-chave = termos técnicos dos dois módulos
            pks_set = set()
            pks_set.add(dados_visual.get("tipo_provavel", "").lower())
            pks_set.add(dados_visual.get("elemento_afetado", "").lower())
            pks_set.add(dados_ibape.get("anomalia_origem", "").lower())
            pks_set.add(dados_ibape.get("anomalia_natureza", "").lower())
            for norma in (dados_gut.get("normas_sugeridas") or []):
                pks_set.add(norma.lower())
            for norma in (dados_ibape.get("normas_referencias") or []):
                if isinstance(norma, str):
                    pks_set.add(norma.lower())
            pks = ", ".join(t for t in sorted(pks_set) if t and len(t) > 2)

            gut_str = (
                f"G:{dados_gut.get('G','?')} U:{dados_gut.get('U','?')} "
                f"T:{dados_gut.get('T','?')} P:{dados_gut.get('prioridade','?')}"
            )

            self.db.salvar_topico(
                laudo_id=laudo_id,
                num=imagem_id,
                titulo=f"Análise de Imagem — {dados_visual.get('tipo_provavel','Anomalia')}",
                orig=texto_orig,
                reescrito=texto_reesc,
                risco=dados_gut.get("risco", "-"),
                gut=gut_str,
                criterio=consolidacao.get("tipo_anomalia_consolidado", "-"),
                aval_risco=dados_ibape.get("grau_risco", "-"),
                aval_gut=gut_str,
                palavras_chave=pks,
                hierarquia=f"ANÁLISE DE IMAGEM > {dados_visual.get('tipo_provavel','?')}",
            )

            # Salvar consolidação JSON completa como parâmetro normativo
            try:
                self.db.salvar_parametro(
                    laudo_id=laudo_id,
                    topico_id=0,
                    parametro="consolidacao_imagem",
                    valor=json.dumps(consolidacao, ensure_ascii=False)[:4000],
                    contexto=f"Imagem: {nome_arquivo}",
                )
            except Exception:
                pass

        except Exception as e:
            logger.error("Erro ao gravar resultado no banco: %s", e)
            print(f"  ⚠️  Não foi possível gravar no banco: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # EXIBIÇÃO DO RESULTADO FINAL
    # ─────────────────────────────────────────────────────────────────────

    def _exibir_resultado_final(
        self,
        consolidacao: Dict,
        dados_gut:    Dict,
        dados_ibape:  Dict,
    ) -> None:
        """Exibe o resultado consolidado no terminal."""
        sep = "─" * 68
        print(f"\n╔{'═'*68}╗")
        print(f"║  CONSOLIDAÇÃO TÉCNICA DA ANOMALIA{' '*34}║")
        print(f"╠{'═'*68}╣")
        print(f"║  Tipo:      {consolidacao.get('tipo_anomalia_consolidado','?'):<56}║")
        print(f"║  Risco GUT: G={dados_gut.get('G','?')} U={dados_gut.get('U','?')} "
              f"T={dados_gut.get('T','?')} → {dados_gut.get('risco','?'):<44}║")
        print(f"║  Origem:    {dados_ibape.get('anomalia_origem','?'):<56}║")
        print(f"║  Natureza:  {dados_ibape.get('anomalia_natureza','?'):<56}║")
        print(f"║  Confiança: {consolidacao.get('nivel_de_confianca','?'):<56}║")
        print(f"╠{'═'*68}╣")
        desc = consolidacao.get("descricao_tecnica_breve", "") or ""
        # Quebrar descrição em linhas de 64 chars
        for i in range(0, min(len(desc), 192), 64):
            linha = desc[i:i+64]
            print(f"║  {linha:<66}║")
        print(f"╠{'═'*68}╣")
        inspecao = "SIM" if consolidacao.get("necessita_inspecao_complementar") else "NÃO"
        print(f"║  Inspeção complementar necessária: {inspecao:<32}║")
        div = consolidacao.get("divergencias_identificadas", "") or "Nenhuma"
        print(f"║  Divergências: {str(div)[:52]:<52}║")
        print(f"╚{'═'*68}╝")


# ══════════════════════════════════════════════════════════════════════════════
# PONTO DE ENTRADA — chamado pelo main.py
# ══════════════════════════════════════════════════════════════════════════════

def analise_imagem_cli(
    db_manager: Any,
    ai_engine:  Any,
    conn_ibape: Optional[sqlite3.Connection] = None,
    conn_gut:   Optional[sqlite3.Connection] = None,
) -> None:
    """
    Ponto de entrada para integração com main.py.

    Fluxo:
      img_patologias_entrada/ → GUT Adaptativo → Análise IBAPE
      → Busca banco → Consolidação API → img_patologias_processadas/

    Args:
        db_manager: Instância de DatabaseManager.
        ai_engine:  Instância de AIEngine.
        conn_ibape: Conexão ao analise_ibape.db (opcional — cria se None).
        conn_gut:   Conexão ao banco principal para GUT (opcional).
    """
    print("\n" + "═"*68)
    print("  📸 ANÁLISE INTEGRADA DE IMAGENS DE PATOLOGIA")
    print("  GUT Adaptativo + Análise IBAPE + Banco + IA")
    print("═"*68)
    print(f"""
  Fluxo de análise:
    1. Descrição visual automática (IA) ou manual
    2. GUT Adaptativo — você responde as perguntas de cada imagem
    3. Análise IBAPE — você preenche os campos técnicos
    4. Busca automática de textos normativos no banco
    5. Consolidação técnica via API (homogeneização, não decisão)

  Pasta de entrada:  {PASTA_ENTRADA}/
  Pasta de saída:    {PASTA_SAIDA}/

  ℹ️  Cada imagem tem análise independente.
  ℹ️  A API não classifica — apenas consolida o que você preencheu.
""")
    input("  [ENTER] para iniciar ou Ctrl+C para cancelar...")

    try:
        analisador = AnalisadorImagem(
            db_manager=db_manager,
            ai_engine=ai_engine,
            conn_ibape=conn_ibape,
            conn_principal_gut=conn_gut,
        )
        analisador.processar_lote()
    except KeyboardInterrupt:
        print("\n\n  Análise de imagens encerrada pelo usuário.")
    except Exception as e:
        logger.exception("analise_imagem_cli: %s", e)
        print(f"\n  ❌ Erro no módulo de análise de imagens: {e}")
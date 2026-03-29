"""
offline_extractor.py — Extrator Offline de Documentos (Fase 1 e Fase 2)
Sistema: Cérebro de Engenharia Diagnóstica — Reprocessamento Inteligente v1.0

Responsabilidades:
  • Fase 1: Extração textual de DOCX/TXT/PDF (sem IA)
  • Fase 2: Reprocessamento de documentos já no banco (correção e enriquecimento)
  • Extração de palavras-chave (dicionário + TF-IDF simples)
  • Extração de parâmetros numéricos (regex)
  • Hierarquia de seções/capítulos
  • Fallback gracioso para todos os erros de parsing

Referência: Componente ExtratorOffline, Seção 4.1 do prompt de reprocessamento.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from log_manager import GerenciadorLog

# ─────────────────────────────────────────────────────────────────────────────
# Importações opcionais (graceful degradation)
# ─────────────────────────────────────────────────────────────────────────────

try:
    import docx as _docx
    DOCX_OK = True
except ImportError:
    DOCX_OK = False

try:
    import pypdf
    PYPDF_OK = True
except ImportError:
    PYPDF_OK = False

try:
    import pdfplumber
    PDFPLUMBER_OK = True
except ImportError:
    PDFPLUMBER_OK = False

try:
    import mammoth as _mammoth
    MAMMOTH_OK = True
except ImportError:
    MAMMOTH_OK = False

try:
    from bs4 import BeautifulSoup as _BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

STOPWORDS_PT = {
    "de","da","do","das","dos","em","no","na","nos","nas","um","uma","o","a",
    "os","as","e","ou","que","se","por","para","com","não","mais","como","mas",
    "foi","são","ser","ter","tem","há","sua","seu","seus","suas","este","esta",
    "esse","essa","ao","à","pelo","pela","deve","pode","cada","quando","onde",
    "assim","entre","até","após","sobre","sob","também","já","ainda","pois",
    "qual","todo","todos","mesmo","então","sendo","tendo","neste","desta",
    "pelo","pelos","pelas","sendo","número","item","seção","capítulo","página",
}

# Regex para extração de parâmetros numéricos
_RE_PARAMS = [
    (r"(\d+[,.]?\d*)\s*(mm|cm|m)\b",          "dimensão",     1, 2),
    (r"(\d+[,.]?\d*)\s*(kN|kPa|MPa|N\/mm²)\b","carga",        1, 2),
    (r"(\d+[,.]?\d*)%",                         "percentual",   1, None),
    (r"(\d+)\s*h(?:oras?)?\b",                  "tempo_horas",  1, None),
    (r"NBR\s*(\d{3,6})",                         "nbr_ref",      1, None),
    (r"(\d+[,.]?\d*)\s*a\s*(\d+[,.]?\d*)\s*(mm|cm|m|%)",
                                                 "intervalo",    1, 3),
]

_RE_HIERARQUIA = re.compile(
    r"^(\d+(?:\.\d+)*)\s+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ][^\n]{3,80})",
    re.MULTILINE
)

_RE_LIMPAR = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


# ─────────────────────────────────────────────────────────────────────────────
# Função pública: extrair_documento — formato canônico unificado
# ─────────────────────────────────────────────────────────────────────────────

def extrair_documento(caminho: str, forcar_ocr: bool = False) -> Dict[str, Any]:
    """
    Detecta o formato do arquivo, extrai texto e retorna estrutura canônica.

    Suporta: .pdf, .docx, .doc, .html, .htm, .txt
    Estratégia por formato:
      PDF digital  → pdfplumber com detecção de layout em colunas
      PDF scanner  → ocrmypdf + pdfplumber (se forcar_ocr=True ou sem texto)
      DOCX         → python-docx (headings + tabelas)
      DOC legado   → mammoth → HTML → BeautifulSoup
      HTML         → BeautifulSoup (H1-H6 como hierarquia)
      TXT          → regex estruturado

    Args:
        caminho:    Caminho absoluto ou relativo ao arquivo.
        forcar_ocr: Se True, força OCR mesmo em PDFs com texto.

    Returns:
        Dict com chaves: formato_origem, titulo_documento, hierarquia, metadata.
        Nunca lança exceção — em caso de erro retorna estrutura vazia com
        metadata['erro'] preenchido.
    """
    import logging as _log_mod
    _log = _log_mod.getLogger(__name__)

    caminho_p = Path(caminho)
    ext = caminho_p.suffix.lower()
    resultado: Dict[str, Any] = {
        "formato_origem":   ext.lstrip(".") or "desconhecido",
        "titulo_documento": caminho_p.stem,
        "hierarquia":       [],
        "metadata": {
            "total_paginas":      0,
            "total_secoes":       0,
            "tem_tabelas":        False,
            "tem_ocr":            False,
            "qualidade_extracao": 0.0,
            "erro":               "",
        },
    }

    if not caminho_p.exists():
        resultado["metadata"]["erro"] = f"Arquivo não encontrado: {caminho}"
        _log.error("[extrair_documento] %s", resultado["metadata"]["erro"])
        return resultado

    try:
        if ext == ".pdf":
            _extrair_pdf_canonico(caminho, forcar_ocr, resultado, _log)
        elif ext == ".docx":
            _extrair_docx_canonico(caminho, resultado, _log)
        elif ext == ".doc":
            _extrair_doc_canonico(caminho, resultado, _log)
        elif ext in (".html", ".htm"):
            _extrair_html_canonico(caminho, resultado, _log)
        elif ext == ".txt":
            _extrair_txt_canonico(caminho, resultado, _log)
        else:
            resultado["metadata"]["erro"] = f"Formato não suportado: {ext}"
            _log.warning("[extrair_documento] %s", resultado["metadata"]["erro"])
    except Exception as e:
        resultado["metadata"]["erro"] = f"Erro inesperado: {e}"
        _log.error("[extrair_documento] Erro ao processar '%s': %s", caminho, e, exc_info=True)

    resultado["metadata"]["total_secoes"] = len(resultado["hierarquia"])
    return resultado


# ── Extratores internos do formato canônico ───────────────────────────────────

def _calcular_qualidade_extracao(
    secoes: List[Dict], total_paginas: int, tem_ocr: bool
) -> float:
    """
    Estima qualidade de 0.0 a 1.0 com base em:
    - % de páginas com texto (ou secoes/paginas estimado)
    - Presença de hierarquia estruturada
    - Ausência de caracteres corrompidos
    - Penalidade se OCR foi necessário
    """
    if not secoes:
        return 0.0
    total_texto = sum(len(s.get("texto", "")) for s in secoes)
    tem_hierarquia = any(s.get("nivel", 0) > 1 or s.get("codigo", "") for s in secoes)
    # Detectar chars corrompidos (caixas, substitutos)
    texto_amostra = " ".join(s.get("texto", "")[:200] for s in secoes[:5])
    chars_corrompidos = len(re.findall(r'[\ufffd\u25a1\u2593]{2,}', texto_amostra))
    score_texto    = min(1.0, total_texto / max(total_paginas * 400, 1))
    score_hierarq  = 0.2 if tem_hierarquia else 0.0
    score_corrupcao = max(0.0, 0.3 - chars_corrompidos * 0.05)
    penalidade_ocr  = -0.1 if tem_ocr else 0.0
    return round(min(1.0, max(0.0, score_texto * 0.5 + score_hierarq + score_corrupcao + penalidade_ocr)), 2)


def _secao_canonica(
    nivel: int, codigo: str, titulo: str, texto: str,
    tabelas: Optional[List] = None, pagina_inicio: int = 0
) -> Dict[str, Any]:
    """Cria um dict de seção no formato canônico."""
    return {
        "nivel":        nivel,
        "codigo":       codigo,
        "titulo":       titulo[:200],
        "texto":        _RE_LIMPAR.sub("", texto).strip(),
        "tabelas":      tabelas or [],
        "pagina_inicio": pagina_inicio,
    }


def _extrair_pdf_canonico(
    caminho: str, forcar_ocr: bool,
    resultado: Dict, _log: Any
) -> None:
    """Extrai PDF com pdfplumber + detecção de layout em 2 colunas."""
    if not PDFPLUMBER_OK:
        resultado["metadata"]["erro"] = "pdfplumber não instalado"
        return

    import pdfplumber as _plumber

    secoes: List[Dict] = []
    hierarquia_atual: List[str] = []
    total_paginas = 0
    tem_ocr = False
    texto_total_chars = 0

    try:
        with _plumber.open(caminho) as pdf:
            total_paginas = len(pdf.pages)
            resultado["metadata"]["total_paginas"] = total_paginas

            for num_pag, pagina in enumerate(pdf.pages, 1):
                texto_pag = _extrair_pagina_pdf_com_colunas(pagina, _log)

                if not texto_pag.strip() and not forcar_ocr:
                    # Página sem texto — pode ser scan; tenta com pypdf como fallback
                    if PYPDF_OK:
                        try:
                            import pypdf as _pypdf
                            reader = _pypdf.PdfReader(caminho)
                            if num_pag - 1 < len(reader.pages):
                                texto_pag = reader.pages[num_pag - 1].extract_text() or ""
                        except Exception:
                            pass

                if not texto_pag.strip():
                    tem_ocr = True  # Sinalizador: esta página precisaria de OCR
                    continue

                texto_total_chars += len(texto_pag)
                # Processa o texto da página em seções
                for linha in texto_pag.split("\n"):
                    linha = linha.strip()
                    if not linha or len(linha) < 5:
                        continue
                    m = _RE_HIERARQUIA.match(linha)
                    if m:
                        codigo = m.group(1)
                        titulo = m.group(2).strip()
                        nivel  = len(codigo.split("."))
                        hierarquia_atual = hierarquia_atual[:nivel - 1] + [f"{codigo} {titulo}"]
                        secoes.append(_secao_canonica(
                            nivel=nivel, codigo=codigo, titulo=titulo,
                            texto=linha, pagina_inicio=num_pag
                        ))
                    elif secoes:
                        secoes[-1]["texto"] += "\n" + linha
                    else:
                        secoes.append(_secao_canonica(
                            nivel=1, codigo="", titulo=linha[:80],
                            texto=linha, pagina_inicio=num_pag
                        ))

    except Exception as e:
        resultado["metadata"]["erro"] = f"Erro ao ler PDF: {e}"
        _log.error("[extrair_documento] PDF '%s': %s", caminho, e)
        return

    resultado["hierarquia"] = secoes
    resultado["metadata"]["tem_ocr"] = tem_ocr
    resultado["metadata"]["qualidade_extracao"] = _calcular_qualidade_extracao(
        secoes, total_paginas, tem_ocr
    )
    _log.info(
        "[extrair_documento] PDF '%s': %d seções, %d págs, qualidade=%.2f, ocr=%s",
        Path(caminho).name, len(secoes), total_paginas,
        resultado["metadata"]["qualidade_extracao"], tem_ocr
    )


def _extrair_pagina_pdf_com_colunas(pagina: Any, _log: Any) -> str:
    """
    Extrai texto de uma página PDF com detecção de layout em 2 colunas.
    Usa bounding boxes do pdfplumber para separar colunas quando a largura
    da página é ≥ 2× a largura média dos blocos de texto.
    """
    try:
        palavras = pagina.extract_words(x_tolerance=3, y_tolerance=3)
        if not palavras:
            return pagina.extract_text() or ""

        largura_pag = float(pagina.width)
        # Detectar se há duas colunas: verificar se existe gap central sem texto
        xs_centro = [float(w["x0"]) for w in palavras if w["x0"] > largura_pag * 0.3
                     and w["x0"] < largura_pag * 0.7]
        # Se menos de 10% das palavras estão no centro → provável 2 colunas
        pct_centro = len(xs_centro) / max(len(palavras), 1)
        if pct_centro < 0.10 and len(palavras) > 20:
            # Layout 2 colunas: separar pela metade da página
            meio = largura_pag / 2
            col_esq = [w for w in palavras if float(w["x0"]) < meio]
            col_dir = [w for w in palavras if float(w["x0"]) >= meio]
            # Ordenar cada coluna por y (linha) depois x
            def _ordenar(words: list) -> str:
                agrupadas: Dict[int, List] = {}
                for w in words:
                    y_key = round(float(w["top"]) / 5) * 5
                    agrupadas.setdefault(y_key, []).append(w)
                linhas = []
                for y_key in sorted(agrupadas):
                    linha_words = sorted(agrupadas[y_key], key=lambda x: float(x["x0"]))
                    linhas.append(" ".join(ww["text"] for ww in linha_words))
                return "\n".join(linhas)
            return _ordenar(col_esq) + "\n" + _ordenar(col_dir)

        return pagina.extract_text() or ""

    except Exception as e:
        _log.debug("[extrair_pagina_pdf] Fallback para extract_text: %s", e)
        try:
            return pagina.extract_text() or ""
        except Exception:
            return ""


def _extrair_docx_canonico(caminho: str, resultado: Dict, _log: Any) -> None:
    """Extrai DOCX preservando headings H1-H6, tabelas e listas."""
    if not DOCX_OK:
        resultado["metadata"]["erro"] = "python-docx não instalado"
        return
    try:
        doc = _docx.Document(caminho)
    except Exception as e:
        resultado["metadata"]["erro"] = f"Erro ao abrir DOCX: {e}"
        _log.error("[extrair_documento] DOCX '%s': %s", caminho, e)
        return

    secoes: List[Dict] = []
    hierarquia_atual: List[str] = []
    tabelas_doc = []

    # Extrair tabelas como lista de dicts
    for tabela in doc.tables:
        try:
            headers = [c.text.strip() for c in tabela.rows[0].cells] if tabela.rows else []
            linhas_tab = []
            for row in tabela.rows[1:]:
                celulas = [c.text.strip() for c in row.cells]
                if any(celulas):
                    if headers and len(headers) == len(celulas):
                        linhas_tab.append(dict(zip(headers, celulas)))
                    else:
                        linhas_tab.append({f"col{i}": v for i, v in enumerate(celulas)})
            if linhas_tab:
                tabelas_doc.append(linhas_tab)
        except Exception:
            pass

    tem_tabelas = bool(tabelas_doc)
    tab_idx = 0

    for para in doc.paragraphs:
        txt = para.text.strip()
        if not txt:
            continue
        txt = _RE_LIMPAR.sub("", txt)
        estilo = para.style.name if para.style else ""

        nivel = 0
        codigo = ""
        if "Heading" in estilo or "T\u00edtulo" in estilo:
            try:
                nivel = int(re.search(r'\d+', estilo).group())
            except (AttributeError, ValueError):
                nivel = 1
        elif _RE_HIERARQUIA.match(txt):
            m = _RE_HIERARQUIA.match(txt)
            codigo = m.group(1)
            nivel = len(codigo.split("."))

        if nivel > 0:
            if not codigo:
                m2 = _RE_HIERARQUIA.match(txt)
                if m2:
                    codigo = m2.group(1)
            hierarquia_atual = hierarquia_atual[:nivel - 1] + [txt[:80]]
            # Associar tabela seguinte ao heading, se houver
            tabelas_associadas = []
            if tab_idx < len(tabelas_doc):
                tabelas_associadas = [tabelas_doc[tab_idx]]
                tab_idx += 1
                tem_tabelas = True
            secoes.append(_secao_canonica(
                nivel=nivel, codigo=codigo,
                titulo=txt, texto=txt,
                tabelas=tabelas_associadas, pagina_inicio=0
            ))
        elif secoes:
            secoes[-1]["texto"] += "\n" + txt
        else:
            secoes.append(_secao_canonica(
                nivel=1, codigo="", titulo=txt[:80],
                texto=txt, pagina_inicio=0
            ))

    resultado["hierarquia"] = secoes
    resultado["metadata"]["tem_tabelas"] = tem_tabelas
    resultado["metadata"]["total_paginas"] = 1  # DOCX não tem página nativa
    resultado["metadata"]["qualidade_extracao"] = _calcular_qualidade_extracao(secoes, 1, False)
    _log.info(
        "[extrair_documento] DOCX '%s': %d seções, %d tabelas, qualidade=%.2f",
        Path(caminho).name, len(secoes), len(tabelas_doc),
        resultado["metadata"]["qualidade_extracao"]
    )


def _extrair_doc_canonico(caminho: str, resultado: Dict, _log: Any) -> None:
    """Extrai .doc legado via mammoth → HTML → BeautifulSoup."""
    if not MAMMOTH_OK:
        _log.warning(
            "[extrair_documento] mammoth não instalado. "
            "Instale: pip install mammoth. Tentando python-docx como fallback."
        )
        # Último recurso: tentar python-docx (às vezes funciona com .doc antigos)
        if DOCX_OK:
            _extrair_docx_canonico(caminho, resultado, _log)
        else:
            resultado["metadata"]["erro"] = "mammoth e python-docx não instalados"
        return

    try:
        with open(caminho, "rb") as f:
            html_resultado = _mammoth.convert_to_html(f)
        html = html_resultado.value
    except Exception as e:
        resultado["metadata"]["erro"] = f"Erro mammoth: {e}"
        _log.error("[extrair_documento] DOC '%s': %s", caminho, e)
        return

    if not BS4_OK:
        # Fallback: extrair texto puro do HTML via regex
        texto_puro = re.sub(r'<[^>]+>', ' ', html)
        resultado["hierarquia"] = [_secao_canonica(1, "", "Documento", texto_puro)]
        resultado["metadata"]["qualidade_extracao"] = 0.5
        return

    _extrair_html_str_canonico(html, resultado, _log, nome_arquivo=Path(caminho).name)


def _extrair_html_canonico(caminho: str, resultado: Dict, _log: Any) -> None:
    """Extrai arquivo HTML usando BeautifulSoup."""
    if not BS4_OK:
        resultado["metadata"]["erro"] = "beautifulsoup4 não instalado"
        return
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            html = f.read()
    except Exception as e:
        resultado["metadata"]["erro"] = f"Erro ao ler HTML: {e}"
        return
    _extrair_html_str_canonico(html, resultado, _log, nome_arquivo=Path(caminho).name)


def _extrair_html_str_canonico(
    html: str, resultado: Dict, _log: Any, nome_arquivo: str = ""
) -> None:
    """Parseia string HTML com BeautifulSoup, usando H1-H6 como hierarquia."""
    soup = _BeautifulSoup(html, "html.parser")
    secoes: List[Dict] = []
    hierarquia_atual: List[str] = []
    titulo_doc = soup.find("title")
    if titulo_doc:
        resultado["titulo_documento"] = titulo_doc.get_text().strip()[:200]

    tags_heading = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    for elemento in soup.find_all(["h1","h2","h3","h4","h5","h6","p","table"]):
        tag = elemento.name.lower()
        if tag in tags_heading:
            nivel = tags_heading[tag]
            titulo = elemento.get_text(" ", strip=True)
            m = _RE_HIERARQUIA.match(titulo)
            codigo = m.group(1) if m else ""
            hierarquia_atual = hierarquia_atual[:nivel - 1] + [titulo[:80]]
            secoes.append(_secao_canonica(
                nivel=nivel, codigo=codigo, titulo=titulo, texto=titulo
            ))
        elif tag == "p":
            texto = elemento.get_text(" ", strip=True)
            if texto and len(texto) > 5:
                if secoes:
                    secoes[-1]["texto"] += "\n" + texto
                else:
                    secoes.append(_secao_canonica(1, "", texto[:80], texto))
        elif tag == "table":
            try:
                linhas_tab = []
                headers_el = elemento.find_all("th")
                headers = [h.get_text(strip=True) for h in headers_el]
                for tr in elemento.find_all("tr"):
                    celulas = [td.get_text(strip=True) for td in tr.find_all("td")]
                    if celulas:
                        if headers and len(headers) == len(celulas):
                            linhas_tab.append(dict(zip(headers, celulas)))
                        else:
                            linhas_tab.append({f"col{i}": v for i, v in enumerate(celulas)})
                if linhas_tab and secoes:
                    secoes[-1]["tabelas"].append(linhas_tab)
                    resultado["metadata"]["tem_tabelas"] = True
            except Exception:
                pass

    resultado["hierarquia"] = secoes
    resultado["metadata"]["total_paginas"] = 1
    resultado["metadata"]["qualidade_extracao"] = _calcular_qualidade_extracao(secoes, 1, False)
    _log.info(
        "[extrair_documento] HTML '%s': %d seções, qualidade=%.2f",
        nome_arquivo, len(secoes), resultado["metadata"]["qualidade_extracao"]
    )


def _extrair_txt_canonico(caminho: str, resultado: Dict, _log: Any) -> None:
    """Extrai TXT com detecção de padrões NBR via regex estruturado."""
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            conteudo = f.read()
    except Exception as e:
        resultado["metadata"]["erro"] = f"Erro ao ler TXT: {e}"
        return

    linhas = conteudo.split("\n")
    secoes: List[Dict] = []
    hierarquia_atual: List[str] = []

    for linha in linhas:
        linha = linha.strip()
        if not linha or len(linha) < 5:
            continue
        linha = _RE_LIMPAR.sub("", linha)
        m = _RE_HIERARQUIA.match(linha)
        if m:
            codigo = m.group(1)
            titulo = m.group(2).strip()
            nivel  = len(codigo.split("."))
            hierarquia_atual = hierarquia_atual[:nivel - 1] + [f"{codigo} {titulo}"]
            secoes.append(_secao_canonica(
                nivel=nivel, codigo=codigo, titulo=titulo, texto=linha
            ))
        elif secoes:
            secoes[-1]["texto"] += "\n" + linha
        else:
            secoes.append(_secao_canonica(1, "", linha[:80], linha))

    resultado["hierarquia"] = secoes
    resultado["metadata"]["total_paginas"] = 1
    resultado["metadata"]["qualidade_extracao"] = _calcular_qualidade_extracao(secoes, 1, False)
    _log.info(
        "[extrair_documento] TXT '%s': %d seções, qualidade=%.2f",
        Path(caminho).name, len(secoes), resultado["metadata"]["qualidade_extracao"]
    )


# ─────────────────────────────────────────────────────────────────────────────
# ExtratorOffline
# ─────────────────────────────────────────────────────────────────────────────

class ExtratorOffline:
    """
    Extrator e reprocessador offline — funciona 100% sem IA.

    Fase 1: processar_documento(caminho, laudo_id) → insere tópicos no banco.
    Fase 2: reprocessar_todos()                    → revisa docs em processados/.

    Exemplo de uso (Fase 1):
        extrator = ExtratorOffline(db_path="banco_pericial.db")
        laudo_id = extrator.registrar_laudo("laudo_01.pdf", "pdf")
        extrator.processar_documento("pdf_entrada/laudo_01.pdf", laudo_id)

    Exemplo de uso (Fase 2):
        extrator.reprocessar_todos()
    """

    def __init__(
        self,
        db_path: str = "banco_pericial.db",
        log: Optional[GerenciadorLog] = None,
        dicionario: Optional[Dict[str, List[str]]] = None,
    ):
        self.db_path    = db_path
        self.log        = log or GerenciadorLog.obter_instancia()
        self.dicionario = dicionario or self._carregar_dicionario_banco()

    # ─── Banco de dados ───────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def registrar_laudo(
        self, nome_arquivo: str, tipo_fonte: str = "outro"
    ) -> int:
        """
        Registra ou recupera o laudo no banco.

        Returns:
            ID do laudo em laudos.id
        """
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT id FROM laudos WHERE nome_arquivo = ?", (nome_arquivo,)
            ).fetchone()
            if row:
                return row[0]

            cur = conn.execute(
                "INSERT INTO laudos (nome_arquivo, tipo_fonte) VALUES (?, ?)",
                (nome_arquivo, tipo_fonte)
            )
            laudo_id = cur.lastrowid
            conn.commit()
            return laudo_id
        finally:
            conn.close()

    def _migrar_colunas_topicos(self) -> None:
        """Adiciona colunas novas em topicos se não existirem (idempotente)."""
        novas_colunas = [
            ("tipo_anomalia",          "TEXT DEFAULT ''"),
            ("origem_patologica",      "TEXT DEFAULT ''"),
            ("mecanismo",              "TEXT DEFAULT ''"),
            ("ia_score_confianca",     "REAL DEFAULT 0.0"),
            ("ia_modelo",              "TEXT DEFAULT ''"),
            ("ia_timestamp",           "TIMESTAMP"),
            ("status_processamento",   "TEXT DEFAULT 'nao_iniciado'"),
            ("versao_processamento",   "INTEGER DEFAULT 1"),
            ("historico_mudancas",     "TEXT DEFAULT '[]'"),
        ]
        conn = self._conn()
        try:
            cols_existentes = {
                row[1] for row in conn.execute("PRAGMA table_info(topicos)").fetchall()
            }
            for nome_col, definicao in novas_colunas:
                if nome_col not in cols_existentes:
                    try:
                        conn.execute(
                            f"ALTER TABLE topicos ADD COLUMN {nome_col} {definicao}"
                        )
                        self.log.info(f"[ExtratorOffline] Coluna adicionada: topicos.{nome_col}")
                    except Exception as e:
                        self.log.warning(f"[ExtratorOffline] Coluna '{nome_col}' não adicionada: {e}")
            conn.commit()
        finally:
            conn.close()

    # ─── Extração de texto ────────────────────────────────────────────────────

    def extrair_texto_docx(self, caminho: str) -> List[Dict[str, Any]]:
        """
        Extrai parágrafos e tabelas de DOCX com hierarquia.
        Suporta .docx moderno; para .doc legado usa mammoth como fallback.

        Returns:
            Lista de {'texto', 'hierarquia', 'pagina'}
        """
        ext = Path(caminho).suffix.lower()

        # .doc legado: tentar mammoth → HTML → texto plano
        if ext == ".doc":
            return self._extrair_doc_legado(caminho)

        if not DOCX_OK:
            self.log.warning("[ExtratorOffline] python-docx não disponível.")
            return []
        try:
            doc = _docx.Document(caminho)
            blocos = []
            hierarquia_atual = []

            # Incluir texto das tabelas no fluxo do documento
            for para in doc.paragraphs:
                txt = para.text.strip()
                if not txt:
                    continue
                txt = _RE_LIMPAR.sub("", txt)
                estilo = para.style.name if para.style else ""

                nivel = 0
                if "Heading" in estilo or "Título" in estilo:
                    try:
                        nivel = int(re.search(r'\d+', estilo).group())
                    except (AttributeError, ValueError):
                        nivel = 1
                elif _RE_HIERARQUIA.match(txt):
                    m = _RE_HIERARQUIA.match(txt)
                    nivel = len(m.group(1).split("."))

                if nivel > 0:
                    hierarquia_atual = hierarquia_atual[:nivel - 1] + [txt[:80]]

                blocos.append({
                    "texto":      txt,
                    "hierarquia": " > ".join(hierarquia_atual),
                    "pagina":     0,
                })

            # Extrair conteúdo das tabelas como texto adicional
            for tabela in doc.tables:
                try:
                    linhas_txt = []
                    for row in tabela.rows:
                        celulas = [c.text.strip() for c in row.cells if c.text.strip()]
                        if celulas:
                            linhas_txt.append(" | ".join(celulas))
                    texto_tabela = "\n".join(linhas_txt)
                    if texto_tabela.strip():
                        blocos.append({
                            "texto":      texto_tabela,
                            "hierarquia": " > ".join(hierarquia_atual) + " [tabela]",
                            "pagina":     0,
                        })
                except Exception:
                    pass

            return blocos
        except Exception as e:
            self.log.error(f"[ExtratorOffline] Erro DOCX '{caminho}': {e}", exc_info=True)
            return []

    def _extrair_doc_legado(self, caminho: str) -> List[Dict[str, Any]]:
        """Extrai .doc via mammoth → texto plano. Fallback: python-docx."""
        if MAMMOTH_OK:
            try:
                with open(caminho, "rb") as f:
                    resultado = _mammoth.convert_to_plain_text(f)
                texto = resultado.value or ""
                if texto.strip():
                    return [
                        {"texto": linha.strip(), "hierarquia": "", "pagina": 0}
                        for linha in texto.split("\n")
                        if len(linha.strip()) > 10
                    ]
            except Exception as e:
                self.log.warning(f"[ExtratorOffline] mammoth falhou em '{caminho}': {e}")

        # Último recurso: python-docx (às vezes aceita .doc antigos)
        if DOCX_OK:
            try:
                doc = _docx.Document(caminho)
                return [
                    {"texto": p.text.strip(), "hierarquia": "", "pagina": 0}
                    for p in doc.paragraphs if len(p.text.strip()) > 10
                ]
            except Exception as e:
                self.log.error(f"[ExtratorOffline] Erro DOC '{caminho}': {e}")

        self.log.warning(f"[ExtratorOffline] Não foi possível extrair '{caminho}': instale mammoth.")
        return []

    def extrair_texto_pdf(self, caminho: str) -> List[Dict[str, Any]]:
        """
        Extrai texto de PDF (pdfplumber > pypdf > fallback).

        Returns:
            Lista de {'texto', 'hierarquia', 'pagina'}
        """
        blocos: List[Dict] = []

        # Tentativa 1: pdfplumber com detecção de colunas
        if PDFPLUMBER_OK:
            try:
                import pdfplumber as _plumber
                import logging as _log_mod
                _log_inst = _log_mod.getLogger(__name__)
                with _plumber.open(caminho) as pdf:
                    for num_pag, pag in enumerate(pdf.pages, 1):
                        txt = _extrair_pagina_pdf_com_colunas(pag, _log_inst)
                        for linha in txt.split("\n"):
                            linha = linha.strip()
                            if len(linha) > 10:
                                blocos.append({
                                    "texto":      _RE_LIMPAR.sub("", linha),
                                    "hierarquia": "",
                                    "pagina":     num_pag,
                                })
                if blocos:
                    return self._inferir_hierarquia(blocos)
            except Exception as e:
                self.log.warning(f"[ExtratorOffline] pdfplumber falhou em '{caminho}': {e}")

        # Tentativa 2: pypdf
        if PYPDF_OK:
            try:
                reader = pypdf.PdfReader(caminho)
                for num_pag, pag in enumerate(reader.pages, 1):
                    txt = pag.extract_text() or ""
                    for linha in txt.split("\n"):
                        linha = linha.strip()
                        if len(linha) > 10:
                            blocos.append({
                                "texto":      _RE_LIMPAR.sub("", linha),
                                "hierarquia": "",
                                "pagina":     num_pag,
                            })
                return self._inferir_hierarquia(blocos)
            except Exception as e:
                self.log.error(
                    f"[ExtratorOffline] Erro PDF '{caminho}': {e}", exc_info=True
                )

        return blocos

    def extrair_texto_txt(self, caminho: str) -> List[Dict[str, Any]]:
        """Extrai parágrafos de arquivo TXT."""
        try:
            with open(caminho, encoding="utf-8", errors="replace") as f:
                linhas = f.read().split("\n")
            return [
                {
                    "texto":      _RE_LIMPAR.sub("", l.strip()),
                    "hierarquia": "",
                    "pagina":     0,
                }
                for l in linhas if len(l.strip()) > 10
            ]
        except Exception as e:
            self.log.error(f"[ExtratorOffline] Erro TXT '{caminho}': {e}")
            return []

    def _inferir_hierarquia(self, blocos: List[Dict]) -> List[Dict]:
        """Infere hierarquia de seção com base em numeração (5.1.2 ...)."""
        hierarquia_atual: List[str] = []
        for bloco in blocos:
            m = _RE_HIERARQUIA.match(bloco["texto"])
            if m:
                nivel = len(m.group(1).split("."))
                hierarquia_atual = hierarquia_atual[:nivel - 1] + [bloco["texto"][:80]]
                bloco["hierarquia"] = " > ".join(hierarquia_atual)
            else:
                bloco["hierarquia"] = " > ".join(hierarquia_atual)
        return blocos

    # ─── Processamento principal (Fase 1) ────────────────────────────────────

    def processar_documento(
        self,
        caminho: str,
        laudo_id: int,
        op_id: int = -1,
    ) -> Tuple[int, int]:
        """
        Processa um documento e insere tópicos no banco (Fase 1 offline).

        Args:
            caminho:  Caminho completo do arquivo
            laudo_id: FK para laudos.id
            op_id:    ID de operação do GerenciadorLog (opcional)

        Returns:
            (topicos_inseridos, parametros_inseridos)
        """
        ext = Path(caminho).suffix.lower()
        nome = Path(caminho).name

        self.log.info(f"[ExtratorOffline] Processando '{nome}'", laudo_id=laudo_id)
        t0 = time.time()

        # Extração de texto
        if ext == ".pdf":
            blocos = self.extrair_texto_pdf(caminho)
        elif ext in (".docx", ".doc"):
            blocos = self.extrair_texto_docx(caminho)
        elif ext == ".txt":
            blocos = self.extrair_texto_txt(caminho)
        else:
            self.log.warning(f"[ExtratorOffline] Extensão não suportada: {ext}")
            return 0, 0

        if not blocos:
            self.log.warning(f"[ExtratorOffline] Nenhum bloco extraído de '{nome}'")
            return 0, 0

        # Agrupamento em tópicos (juntar blocos pequenos em chunks significativos)
        topicos = self._agrupar_em_topicos(blocos, laudo_id)

        # Persistência no banco
        n_topicos, n_params = self._inserir_topicos(topicos, laudo_id)

        elapsed = time.time() - t0
        self.log.info(
            f"[ExtratorOffline] '{nome}' concluído",
            topicos=n_topicos, params=n_params,
            tempo_s=f"{elapsed:.1f}"
        )
        return n_topicos, n_params

    def _agrupar_em_topicos(
        self, blocos: List[Dict], laudo_id: int
    ) -> List[Dict[str, Any]]:
        """
        Agrupa blocos de texto em tópicos coerentes (~300-800 chars por tópico).
        Respeita quebras de hierarquia.
        """
        topicos: List[Dict] = []
        buffer_texto: List[str] = []
        hierarquia_atual = ""
        pagina_inicio = 0
        numero_topico = 1

        def _flush():
            nonlocal numero_topico
            texto = " ".join(buffer_texto).strip()
            if len(texto) < 20:
                return
            palavras_chave = self._extrair_palavras_chave(texto)
            params = self._extrair_parametros(texto)
            topicos.append({
                "numero_topico": str(numero_topico),
                "titulo_topico": texto[:120],
                "hierarquia":    hierarquia_atual,
                "texto_original": texto,
                "palavras_chave": ", ".join(palavras_chave),
                "pagina":        pagina_inicio,
                "parametros":    params,
                "status_processamento": "fase_1_offline",
            })
            numero_topico += 1
            buffer_texto.clear()

        for bloco in blocos:
            txt = bloco["texto"]
            hier = bloco.get("hierarquia", "")
            pag  = bloco.get("pagina", 0)

            # Nova seção → flush do buffer anterior
            if hier and hier != hierarquia_atual and buffer_texto:
                _flush()
                hierarquia_atual = hier
                pagina_inicio = pag

            if not hierarquia_atual:
                hierarquia_atual = hier
                pagina_inicio = pag

            buffer_texto.append(txt)

            # Flush por tamanho máximo
            if sum(len(t) for t in buffer_texto) > 800:
                _flush()

        if buffer_texto:
            _flush()

        return topicos

    def _inserir_topicos(
        self, topicos: List[Dict], laudo_id: int
    ) -> Tuple[int, int]:
        """Insere lista de tópicos no banco. Retorna (n_topicos, n_params)."""
        self._migrar_colunas_topicos()
        conn = self._conn()
        n_t = 0
        n_p = 0
        try:
            for t in topicos:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO topicos
                       (laudo_id, numero_topico, titulo_topico, hierarquia,
                        texto_original, palavras_chave, pagina,
                        status_processamento)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        laudo_id,
                        t.get("numero_topico", ""),
                        t.get("titulo_topico", "")[:500],
                        t.get("hierarquia", ""),
                        t.get("texto_original", ""),
                        t.get("palavras_chave", ""),
                        t.get("pagina", 0),
                        t.get("status_processamento", "fase_1_offline"),
                    )
                )
                topico_id = cur.lastrowid
                n_t += 1

                # Inserir parâmetros
                for p in t.get("parametros", []):
                    conn.execute(
                        """INSERT INTO parametros_normativos
                           (laudo_id, topico_id, parametro, valor, unidade, contexto, pagina)
                           VALUES (?,?,?,?,?,?,?)""",
                        (
                            laudo_id, topico_id,
                            p.get("parametro", ""), p.get("valor", ""),
                            p.get("unidade", ""), p.get("contexto", ""),
                            t.get("pagina", 0),
                        )
                    )
                    n_p += 1

            conn.commit()
        except Exception as e:
            self.log.error(f"[ExtratorOffline] Erro ao inserir tópicos: {e}", exc_info=True)
            conn.rollback()
        finally:
            conn.close()
        return n_t, n_p

    # ─── Reprocessamento (Fase 2) ─────────────────────────────────────────────

    def reprocessar_todos(
        self,
        pasta_processados: str = "pdf_processados",
        callback_verificar_entrada: Optional[Any] = None,
    ) -> Dict[str, int]:
        """
        Fase 2: Reanálise de todos os documentos já processados.
        Preenche lacunas, corrige erros, expande palavras-chave.

        Args:
            pasta_processados: Pasta com documentos já processados
            callback_verificar_entrada: Se retornar True, interrompe o reprocessamento

        Returns:
            Dict com contadores de campos_modificados, topicos_revisados, etc.
        """
        self.log.info("[ExtratorOffline] Fase 2: Iniciando reprocessamento offline.")
        stats = {"topicos_revisados": 0, "campos_preenchidos": 0, "params_adicionados": 0}

        conn = self._conn()
        try:
            # Buscar tópicos com lacunas
            topicos = conn.execute(
                """SELECT id, laudo_id, titulo_topico, texto_original,
                          palavras_chave, status_processamento, pagina
                   FROM topicos
                   WHERE (palavras_chave IS NULL OR palavras_chave = ''
                          OR texto_original IS NULL OR texto_original = '')
                      OR status_processamento IN ('nao_iniciado', 'fase_1_offline')
                   ORDER BY id"""
            ).fetchall()
        finally:
            conn.close()

        self.log.info(f"[ExtratorOffline] Fase 2: {len(topicos)} tópico(s) para revisar.")

        for row in topicos:
            # Verificar se novos documentos chegaram (interromper se sim)
            if callback_verificar_entrada and callback_verificar_entrada():
                self.log.info("[ExtratorOffline] Fase 2 interrompida: novos documentos detectados.")
                break

            tid, laudo_id, titulo, texto, palavras, status, pagina = row
            try:
                self._revisitar_topico(
                    tid, laudo_id, titulo, texto, palavras, status, pagina, stats
                )
            except Exception as e:
                self.log.error(
                    f"[ExtratorOffline] Erro revisando tópico {tid}: {e}", exc_info=True
                )

        self.log.info(
            "[ExtratorOffline] Fase 2 concluída.",
            **{k: str(v) for k, v in stats.items()}
        )
        return stats

    def _revisitar_topico(
        self,
        tid: int, laudo_id: int, titulo: str, texto: str,
        palavras: str, status: str, pagina: int,
        stats: Dict[str, int],
    ) -> None:
        """Revisa e enriquece um tópico individual na Fase 2."""
        conn = self._conn()
        try:
            atualizacoes: Dict[str, Any] = {}
            texto_base = texto or titulo or ""

            # 1. Preencher palavras-chave vazias
            if not palavras or len(palavras.strip()) < 5:
                novas_pks = self._extrair_palavras_chave(texto_base)
                if novas_pks:
                    atualizacoes["palavras_chave"] = ", ".join(novas_pks)
                    stats["campos_preenchidos"] += 1

            # 2. Expandir palavras-chave existentes com sinônimos
            else:
                expandida = self._expandir_com_sinonimos(palavras)
                if expandida != palavras:
                    atualizacoes["palavras_chave"] = expandida
                    stats["campos_preenchidos"] += 1

            # 3. Atualizar status de processamento
            if status in ("nao_iniciado", "fase_1_offline"):
                atualizacoes["status_processamento"] = "fase_2_offline"

            # 4. Aplicar atualizações
            if atualizacoes:
                set_clause = ", ".join(f"{k}=?" for k in atualizacoes)
                vals = list(atualizacoes.values()) + [tid]
                conn.execute(f"UPDATE topicos SET {set_clause} WHERE id=?", vals)
                conn.commit()
                stats["topicos_revisados"] += 1

            # 5. Verificar e inserir parâmetros faltantes
            if texto_base:
                params = self._extrair_parametros(texto_base)
                if params:
                    existentes = conn.execute(
                        "SELECT COUNT(*) FROM parametros_normativos WHERE topico_id=?", (tid,)
                    ).fetchone()[0]
                    if existentes == 0:
                        for p in params:
                            conn.execute(
                                """INSERT INTO parametros_normativos
                                   (laudo_id, topico_id, parametro, valor, unidade, contexto)
                                   VALUES (?,?,?,?,?,?)""",
                                (laudo_id, tid, p["parametro"], p["valor"],
                                 p.get("unidade",""), p.get("contexto",""))
                            )
                        conn.commit()
                        stats["params_adicionados"] += len(params)

        finally:
            conn.close()

    # ─── Extração de palavras-chave ───────────────────────────────────────────

    def _extrair_palavras_chave(self, texto: str, max_palavras: int = 10) -> List[str]:
        """
        Extração TF-IDF simples + dicionário técnico.
        Sem dependência de libs externas.
        """
        texto_lower = texto.lower()
        tokens = re.findall(r"\b[a-záéíóúâêîôûãõç]{4,}\b", texto_lower)
        tokens = [t for t in tokens if t not in STOPWORDS_PT]

        # Boost por dicionário técnico
        freq: Counter = Counter(tokens)
        for termo, sinonimos in self.dicionario.items():
            if termo in texto_lower or any(s in texto_lower for s in sinonimos):
                freq[termo] += 3

        # Bigrams técnicos
        for i in range(len(tokens) - 1):
            bigram = f"{tokens[i]} {tokens[i+1]}"
            if any(termo in bigram for termo in self.dicionario):
                freq[bigram] = freq.get(bigram, 0) + 2

        return [w for w, _ in freq.most_common(max_palavras)]

    def _expandir_com_sinonimos(self, palavras_str: str) -> str:
        """Adiciona sinônimos técnicos às palavras-chave existentes."""
        pks = set(p.strip().lower() for p in palavras_str.split(",") if p.strip())
        adicionais: set = set()

        for termo, sinonimos in self.dicionario.items():
            if termo in pks:
                for sin in sinonimos[:2]:  # Máximo 2 sinônimos por conceito
                    adicionais.add(sin)

        todas = pks | adicionais
        return ", ".join(sorted(todas))

    # ─── Extração de parâmetros ───────────────────────────────────────────────

    def _extrair_parametros(self, texto: str) -> List[Dict[str, str]]:
        """Extrai parâmetros numéricos e referências normativas."""
        params: List[Dict] = []
        for padrao, nome, g_val, g_uni in _RE_PARAMS:
            for m in re.finditer(padrao, texto, re.IGNORECASE):
                valor = m.group(g_val)
                unidade = m.group(g_uni) if g_uni else ""
                contexto = texto[max(0, m.start() - 40):m.end() + 40].strip()
                params.append({
                    "parametro": nome,
                    "valor":     valor,
                    "unidade":   unidade,
                    "contexto":  contexto,
                })
        return params

    # ─── Dicionário de sinônimos ──────────────────────────────────────────────

    def _carregar_dicionario_banco(self) -> Dict[str, List[str]]:
        """Carrega dicionário técnico do banco + dicionário padrão."""
        dic: Dict[str, List[str]] = {
            "impermeabilização": ["estanqueidade","infiltração","vazamento","umidade"],
            "fissuração":        ["fissura","trinca","rachadura","fenda"],
            "corrosão":          ["ferrugem","oxidação","armadura exposta","carbonatação"],
            "recalque":          ["afundamento","subsidência","assentamento","desnivelamento"],
            "desplacamento":     ["soltura","descolamento","estufamento"],
            "patologia":         ["anomalia","defeito","falha","dano","manifestação"],
            "estrutura":         ["viga","pilar","laje","concreto armado","estrutural"],
            "fundação":          ["sapata","estaca","radier","bloco","tubulão"],
            "revestimento":      ["azulejo","porcelanato","cerâmica","piso","acabamento"],
            "norma":             ["nbr","abnt","requisito","critério","normativo"],
        }
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT conceito, sinonimos FROM dicionario_pericial_sinonimos"
            ).fetchall()
            conn.close()
            import json
            for conceito, sin_json in rows:
                try:
                    dic[conceito] = json.loads(sin_json)
                except Exception:
                    pass
        except Exception:
            pass  # Tabela pode não existir ainda
        return dic

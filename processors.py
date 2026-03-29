"""
processors.py — Pipeline de Ingestão e Processamento de Documentos
Versão 3.0 — PericialChunker integrado, extração de parâmetros normativos,
             alertas de erro de leitura, suporte a hierarquia de seções.
"""
import os
import re
import time
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple

try:
    import docx
except ImportError:
    print("⚠️  python-docx não encontrado. Instale: pip install python-docx")

try:
    import pypdf
except ImportError:
    print("⚠️  pypdf não encontrado. Instale: pip install pypdf")

try:
    import pdfplumber
    PDFPLUMBER_DISPONIVEL = True
except ImportError:
    pdfplumber = None
    PDFPLUMBER_DISPONIVEL = False

try:
    import yake
    extrator_yake = yake.KeywordExtractor(lan="pt", n=2, dedupLim=0.9, top=5, features=None)
    YAKE_DISPONIVEL = True
except ImportError:
    print("⚠️  YAKE não encontrado. Usando apenas dicionário de sinônimos.")
    YAKE_DISPONIVEL = False

EXTENSOES_IMAGEM = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}
QUALIDADE_MINIMA = 0.45


# ══════════════════════════════════════════════════════════════════════════════
#  DICIONÁRIO DE SINÔNIMOS EXPANDIDO
# ══════════════════════════════════════════════════════════════════════════════

DICIONARIO_SINONIMOS = {
    "impermeabilização": ["estanqueidade", "estanque", "impermeável",
                          "infiltração", "vazamento", "umidade", "percolação"],
    "fissuração":        ["fissura", "trinca", "rachadura", "fenda",
                          "abertura", "rompimento", "fissurado"],
    "corrosão":          ["ferrugem", "oxidação", "armadura exposta",
                          "carbonatação", "desagregação", "corroído"],
    "recalque":          ["afundamento", "cedência", "subsidência",
                          "assentamento", "desnivelamento"],
    "desplacamento":     ["soltura", "descolamento", "estufamento",
                          "queda de revestimento", "destaque"],
    "argamassa":         ["reboco", "emboço", "chapisco", "massa",
                          "argamassado", "argamassamento"],
    "guarda-corpo":      ["guarda corpo", "parapeito", "corrimão",
                          "proteção lateral", "barreira de proteção", "gradil",
                          "guarda corpos", "proteção de borda"],
    "ventilação":        ["aeração", "circulação de ar", "exaustão",
                          "renovação de ar", "ventilado", "ventilação natural"],
    "fundação":          ["sapata", "estaca", "radier", "bloco",
                          "tubulão", "fundações", "infraestrutura"],
    "revestimento":      ["azulejo", "porcelanato", "cerâmica", "piso",
                          "acabamento", "revestir", "revestimentos"],
    "estrutura":         ["viga", "pilar", "laje", "concreto armado",
                          "estrutural", "estruturas", "elemento estrutural"],
    "patologia":         ["anomalia", "defeito", "falha", "dano",
                          "manifestação patológica", "vício construtivo"],
    "norma":             ["nbr", "abnt", "requisito", "especificação",
                          "critério", "regulamento", "normativo"],
    "laudo":             ["parecer", "vistoria", "inspeção", "relatório técnico",
                          "perícia", "laudo pericial"],
    "estanqueidade":     ["impermeabilidade", "vedação", "selagem",
                          "lâmina d'água", "teste de estanqueidade"],
    "desempenho":        ["desempenho térmico", "desempenho acústico",
                          "vida útil", "durabilidade", "manutenção"],
}

# ══════════════════════════════════════════════════════════════════════════════
#  STOPWORDS EM PORTUGUÊS
# ══════════════════════════════════════════════════════════════════════════════

STOPWORDS_PT = {
    "de","da","do","das","dos","em","no","na","nos","nas","um","uma","uns",
    "umas","o","a","os","as","e","ou","que","se","por","para","com","não",
    "mais","como","mas","foi","são","ser","ter","tem","há","sua","seu","seus",
    "suas","este","esta","esse","essa","ao","à","pelo","pela","deve","pode",
    "cada","quando","onde","assim","entre","até","após","sobre","sob","também",
    "já","ainda","pois","qual","quais","todo","toda","todos","todas","mesmo",
    "outra","outro","então","sendo","tendo","sendo","neste","nesta","nesse",
    "nessa","deste","desta","desse","dessa","pelo","pela","pelos","pelas",
}

# ══════════════════════════════════════════════════════════════════════════════
#  PADRÕES PARA EXTRAÇÃO DE PARÂMETROS NORMATIVOS
# ══════════════════════════════════════════════════════════════════════════════
# Cada entrada: (nome_parametro, regex, grupo_valor, grupo_unidade)
PADROES_PARAMETROS = [
    # Alturas, comprimentos, espessuras
    ("altura_minima",
     r'altura\s+m[íi]nima\s+(?:de\s+)?(\d+[,.]?\d*)\s*(m\b|cm\b|mm\b)',
     1, 2),
    ("altura_maxima",
     r'altura\s+m[áa]xima\s+(?:de\s+)?(\d+[,.]?\d*)\s*(m\b|cm\b|mm\b)',
     1, 2),
    ("espessura_minima",
     r'espessura\s+m[íi]nima\s+(?:de\s+)?(\d+[,.]?\d*)\s*(m\b|cm\b|mm\b)',
     1, 2),
    ("espessura_maxima",
     r'espessura\s+m[áa]xima\s+(?:de\s+)?(\d+[,.]?\d*)\s*(m\b|cm\b|mm\b)',
     1, 2),
    ("comprimento",
     r'comprimento\s+(?:m[íi]nimo\s+)?(?:de\s+)?(\d+[,.]?\d*)\s*(m\b|cm\b|mm\b)',
     1, 2),

    # Cargas e resistências
    ("carga_minima",
     r'carga\s+(?:m[íi]nima\s+)?(?:de\s+)?(\d+[,.]?\d*)\s*(kN\b|kPa\b|MPa\b|N/mm[²2]\b|kgf\b)',
     1, 2),
    ("resistencia",
     r'resist[êe]ncia\s+(?:m[íi]nima\s+)?(?:de\s+)?(\d+[,.]?\d*)\s*(MPa\b|kPa\b|N/mm[²2]\b)',
     1, 2),
    ("tensao",
     r'tens[ãa]o\s+(?:de\s+)?(\d+[,.]?\d*)\s*(MPa\b|kPa\b|N/mm[²2]\b)',
     1, 2),

    # Duração de ensaios
    ("duracao_ensaio",
     r'(?:dura[çc][ãa]o|per[íi]odo)\s+(?:de\s+)?(\d+)\s*(horas?\b|dias?\b|meses?\b|minutos?\b)',
     1, 2),
    ("lamina_dagua",
     r'l[âa]mina\s+d[`\'\"]?[aá]gua\s+(?:de\s+)?(\d+)\s*(cm\b|mm\b|m\b|horas?\b)',
     1, 2),

    # Inclinações e ângulos
    ("inclinacao",
     r'inclina[çc][ãa]o\s+(?:m[íi]nima\s+)?(?:de\s+)?(\d+[,.]?\d*)\s*(%\b|°\b|graus?\b)',
     1, 2),

    # Temperaturas
    ("temperatura",
     r'temperatura\s+(?:m[íi]nima|m[áa]xima)?\s*(?:de\s+)?(\d+[,.]?\d*)\s*°?C\b',
     1, None),

    # Percentuais — captura intervalo bilateral quando presente
    # Ex: "20% a 30%" → val=20, contexto inclui "a 30%"
    ("percentual",
     r'((?:\d+[,\.]?)?\d+)\s*%(?:\s*(?:a|até|-)\s*((?:\d+[,\.]?)?\d+)\s*%)?',
     1, None),

    # Caimento de piso (NBR 13753, NBR 10844)
    # Ex: "caimento mínimo de 1,0%" ou "caimento de 1,5% a 2,5%"
    ("caimento",
     r'caimento\s+(?:m[íi]nimo\s+)?(?:de\s+)?((?:\d+[,\.]?)?\d+)\s*%'
     r'(?:\s*(?:a|até|-)\s*((?:\d+[,\.]?)?\d+)\s*%)?',
     1, None),

    # Espessura de contrapiso com intervalo (NBR 13753 item 5.5.3)
    # Ex: "espessura do contrapiso entre 15 mm e 25 mm"
    ("espessura_contrapiso",
     r'espessura\s+do?\s+contrapiso\s+(?:entre\s+)?'
     r'((?:\d+[,\.]?)?\d+)\s*(mm|cm)'
     r'(?:\s*(?:e|a|até|-)\s*((?:\d+[,\.]?)?\d+)\s*(?:mm|cm))?',
     1, 2),

    # Aberturas de fissura (específico NBR 6118)
    ("abertura_fissura",
     r'abertura\s+(?:de\s+)?fissura\s+(?:m[áa]xima\s+)?(?:de\s+)?(\d+[,.]?\d*)\s*(mm\b|cm\b)',
     1, 2),
]


# ══════════════════════════════════════════════════════════════════════════════
#  EXTRAÇÃO DE INTERVALOS NUMÉRICOS — standalone
#  Usada por _extrair_parametros() e diretamente pelo search_improvements
# ══════════════════════════════════════════════════════════════════════════════

def extrair_intervalo(texto: str):
    """
    Extrai intervalo numérico mínimo/máximo de texto técnico.

    Suporta formatos reais encontrados nas NBRs:
      "20% a 30%"                 → (20.0, 30.0, '%')
      "15 mm a 25 mm"             → (15.0, 25.0, 'mm')
      "1,5% a 2,5%"               → (1.5, 2.5, '%')
      "entre 15 mm e 25 mm"       → (15.0, 25.0, 'mm')
      "resistência ≥ 0,3 MPa"     → (0.3, None, 'mpa')
      "no mínimo 70 mm"           → (70.0, None, 'mm')
      "texto sem número"          → None

    Args:
        texto: Texto técnico a analisar (pode conter vírgula decimal).

    Returns:
        Tupla (val_min, val_max, unidade) ou None se não encontrar.
        val_max é None para limites unilaterais (≥ / mínimo).
        Unidade em minúsculo, sem espaços.
    """
    import re as _re

    if not texto:
        return None

    # Normalizar: vírgula decimal → ponto, colapsar espaços
    t = texto.replace(',', '.').lower()
    t = _re.sub(r'\s+', ' ', t).strip()

    UNIDADES = (r'(?:mpa|kpa|kn|n/mm[²2]|kgf|'
                r'mm\b|cm\b|m\b|%|°c|'
                r'horas?|dias?|meses?|minutos?|anos?)')

    # ── Padrão 1: intervalo bilateral "X [unid] a Y [unid]" ─────────────────
    p_bilateral = _re.compile(
        r'(?:entre\s+)?'
        r'(\d+\.?\d*)\s*(' + UNIDADES + r')?\s*'
        r'(?:a\b|até|e\b|-)\s*'
        r'(\d+\.?\d*)\s*(' + UNIDADES + r')?',
        _re.IGNORECASE
    )
    m = p_bilateral.search(t)
    if m:
        try:
            val_min = float(m.group(1))
            val_max = float(m.group(3))
            # Preferir unidade do segundo número; fallback para o primeiro
            unidade = (m.group(4) or m.group(2) or '').strip()
            # Detectar '%' que aparece logo após os números mas fora do grupo
            trecho = t[m.start():m.end() + 5]
            if not unidade and '%' in trecho:
                unidade = '%'
            return (val_min, val_max, unidade)
        except (ValueError, TypeError):
            pass

    # ── Padrão 2: limite inferior unilateral "≥ X" / "mínimo X" ────────────
    p_min = _re.compile(
        r'(?:\u2265|>=|m[íi]nimo\s+(?:de\s+)?|no\s+m[íi]nimo\s+|pelo\s+menos\s+)'
        r'\s*(\d+\.?\d*)\s*(' + UNIDADES + r')?',
        _re.IGNORECASE
    )
    m2 = p_min.search(t)
    if m2:
        try:
            val_min = float(m2.group(1))
            unidade = (m2.group(2) or '').strip()
            return (val_min, None, unidade)
        except (ValueError, TypeError):
            pass

    # ── Padrão 3: limite superior unilateral "≤ X" / "máximo X" ────────────
    p_max = _re.compile(
        r'(?:\u2264|<=|m[áa]ximo\s+(?:de\s+)?|no\s+m[áa]ximo\s+)'
        r'\s*(\d+\.?\d*)\s*(' + UNIDADES + r')?',
        _re.IGNORECASE
    )
    m3 = p_max.search(t)
    if m3:
        try:
            val_max = float(m3.group(1))
            unidade = (m3.group(2) or '').strip()
            return (None, val_max, unidade)
        except (ValueError, TypeError):
            pass

    return None


_TOKENIZER_REAL = None
try:
    from transformers import AutoTokenizer as _AutoTokenizer
    _TOKENIZER_REAL = _AutoTokenizer.from_pretrained(
        "mistralai/Mistral-7B-v0.1", use_fast=True
    )
except Exception:
    pass  # Fallback: 1 token ≈ 4 chars (sem dependência externa)


class PericialChunker:
    """
    Chunker hierárquico integrado ao pipeline principal.
    Preserva numeração normativa (pai → filho) para rastreabilidade total.
    Suporta hierarquia de até 4 níveis (padrão NBR: 4.5.2.1).
    """

    # Divide em seções de nível 1 a 4 conforme padrão NBR.
    # "4 Título", "4.4 Título", "4.4.1 Título", "4.4.1.2 Título" — todos detectados.
    # Aceita ponto opcional após o número e maiúsculas acentuadas (PT-BR).
    # IMPORTANTE: usar (?:...) não-capturante — re.split() com grupos capturantes
    # inclui None no resultado quando o grupo não casa, causando erros downstream.
    _RE_SECAO = re.compile(
        r'\n(?=(?:\d+\.){0,3}\d+\.?\s+[A-ZÁÉÍÓÚÀÂÊÔÃÕÜÇ])'
        # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        # (?:\d+\.){0,3}  →  0 a 3 grupos "N." NÃO-CAPTURANTES antes do número final
        # Cobre: "4" (nível 1), "4.4" (2), "4.4.1" (3), "4.4.1.2" (4)
    )
    # Captura número e título da primeira linha de uma seção (qualquer profundidade)
    ITEM_REGEX = re.compile(r'^(\d+(?:\.\d+)*)\.?\s+(.+)$')
    MIN_CONFIDENCE = 0.85

    # M2 — limites de tamanho de chunk em tokens
    MAX_TOKENS   = 1200   # chunks acima disso são subdivididos
    MIN_TOKENS   = 300    # chunks abaixo disso são mesclados
    OVERLAP_TOKENS = 150  # sobreposição entre sub-chunks

    def __init__(self):
        self._hierarquia_atual: List[str] = []

    @staticmethod
    def _contar_tokens_aprox(texto: str) -> int:
        """
        Conta tokens usando tokenizer real (Mistral-7B-v0.1) se disponível.
        Fallback: 1 token ≈ 4 caracteres (sem dependência externa).
        """
        if _TOKENIZER_REAL is not None:
            try:
                return max(1, len(_TOKENIZER_REAL.encode(texto, add_special_tokens=False)))
            except Exception:
                pass
        return max(1, len(texto) // 4)

    def _subdividir_chunk(self, chunk: Dict[str, Any],
                          max_chars: int, overlap_chars: int) -> List[Dict[str, Any]]:
        """
        Subdivide um chunk grande em sub-chunks com sobreposição.
        Cada sub-chunk herda hierarquia/pagina do pai; número recebe sufixo _s1, _s2…
        """
        texto = chunk['texto']
        passo = max_chars - overlap_chars
        sub_chunks: List[Dict[str, Any]] = []
        inicio = 0
        idx = 0
        while inicio < len(texto):
            trecho = texto[inicio: inicio + max_chars]
            if len(trecho.strip()) < 80:
                break
            idx += 1
            sub_chunks.append({
                'numero':    f"{chunk['numero']}_s{idx}",
                'titulo':    chunk['titulo'],
                'texto':     trecho,
                'hierarquia': chunk['hierarquia'],
                'pagina':    chunk['pagina'],
            })
            if inicio + max_chars >= len(texto):
                break
            inicio += passo
        return sub_chunks if sub_chunks else [chunk]

    def _aplicar_token_chunking(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        M2 — Pós-processamento em dois passos:
        1. Mescla chunks pequenos (< MIN_TOKENS) com o seguinte.
        2. Subdivide chunks grandes (> MAX_TOKENS) com sobreposição.
        Preserva metadados (hierarquia, pagina) em todos os fragmentos.
        """
        max_chars     = self.MAX_TOKENS   * 4   # 4800
        min_chars     = self.MIN_TOKENS   * 4   # 1200
        overlap_chars = self.OVERLAP_TOKENS * 4  # 600

        # Fase 1 — mesclar chunks pequenos consecutivos
        mesclados: List[Dict[str, Any]] = []
        buffer: Optional[Dict[str, Any]] = None
        for chunk in chunks:
            if buffer is None:
                buffer = dict(chunk)
            elif len(buffer['texto']) < min_chars:
                buffer['texto'] = buffer['texto'] + '\n\n' + chunk['texto']
            else:
                mesclados.append(buffer)
                buffer = dict(chunk)
        if buffer:
            mesclados.append(buffer)

        # Fase 2 — subdividir chunks grandes
        resultado: List[Dict[str, Any]] = []
        for chunk in mesclados:
            if len(chunk['texto']) > max_chars:
                resultado.extend(self._subdividir_chunk(chunk, max_chars, overlap_chars))
            else:
                resultado.append(chunk)

        return resultado

    def _nivel(self, numero: str) -> int:
        return len(numero.split('.'))

    def _atualizar_hierarquia(self, numero: str, titulo: str):
        nivel = self._nivel(numero)
        self._hierarquia_atual = (
            self._hierarquia_atual[:nivel - 1] + [f"{numero} {titulo}"]
        )

    def hierarquia_como_string(self) -> str:
        return " > ".join(self._hierarquia_atual)

    def processar_texto_normativo(self, texto: str, pagina: int = 0,
                                  confianca: float = 1.0) -> List[Dict[str, Any]]:
        """
        Divide texto normativo em chunks preservando hierarquia.
        Detecta cabeçalhos de seção no formato NBR ("4.1 Título" / "4.1. Título").
        Retorna lista de dicts com texto, numero, titulo, hierarquia, pagina.
        """
        if confianca < self.MIN_CONFIDENCE:
            return []

        chunks = []
        partes = self._RE_SECAO.split(texto)

        for parte in partes:
            parte = parte.strip()
            if len(parte) < 20:
                continue
            linhas = parte.splitlines()
            primeira = linhas[0].strip()
            m = self.ITEM_REGEX.match(primeira)

            if m:
                numero = m.group(1)
                titulo = m.group(2)[:120]
                self._atualizar_hierarquia(numero, titulo)
            else:
                numero = f"p.{pagina}"
                titulo = primeira[:80] if primeira else "Trecho"

            chunks.append({
                'numero':    numero,
                'titulo':    titulo,
                'texto':     parte,
                'hierarquia': self.hierarquia_como_string(),
                'pagina':    pagina,
            })

        # M2: pós-processa — mescla chunks pequenos e subdivide os grandes
        return self._aplicar_token_chunking(chunks)


class FileProcessor:
    def __init__(self, db_manager, ai_engine, pastas: dict):
        self.db      = db_manager
        self.ai      = ai_engine
        self.pastas  = pastas
        self.chunker = PericialChunker()

    # ─────────────────────────────────────────────────────────────────────────
    #  VALIDAÇÃO E LIMPEZA
    # ─────────────────────────────────────────────────────────────────────────

    def _is_imagem_valida(self, nome: str) -> bool:
        _, ext = os.path.splitext(nome)
        return ext.lower() in EXTENSOES_IMAGEM

    def _calcular_qualidade(self, texto: str) -> float:
        if not texto or len(texto.strip()) < 10:
            return 0.0
        linhas = [l.strip() for l in texto.splitlines() if l.strip()]
        if not linhas:
            return 0.0
        total              = len(linhas)
        linhas_curtas      = sum(1 for l in linhas if len(l) <= 4)
        linhas_corrompidas = sum(1 for l in linhas if re.search(r'[-<>~:]{2,}|:::|\-\-\-|o\s*o\s*::', l))
        linhas_sem_vogal   = sum(1 for l in linhas if not re.search(r'[aeiouáéíóúâêîôûãõàAEIOUÁÉÍÓÚ]', l))
        palavras_reais     = re.findall(r'[a-zA-ZÀ-ú]{3,}', texto)
        total_chars        = max(len(texto.replace('\n', '')), 1)
        ratio_palavras     = len(palavras_reais) / (total_chars / 5)
        return round(
            (1 - linhas_curtas      / total) * 0.35 +
            (1 - linhas_corrompidas / total) * 0.30 +
            (1 - linhas_sem_vogal   / total) * 0.20 +
            min(ratio_palavras, 1)            * 0.15, 2
        )

    def _texto_utilizavel(self, texto: str, origem: str = '') -> bool:
        score = self._calcular_qualidade(texto)
        if score < QUALIDADE_MINIMA:
            print(f"   ⚠️  Qualidade baixa ({score:.2f}) em '{origem}' — descartado.")
            return False
        return True

    def _limpar_texto(self, texto: str) -> str:
        LIXO = [
            r'^\s*\d+\s*$', r'^\s*[\.\-\_\=\*]{3,}\s*$', r'^\s*[A-Z]{1,3}\s*$',
            r'^\s*P[aá]gina\s*\d+\s*(de\s*\d+)?\s*$', r'^\s*fls?\.\s*\d+\s*$',
            r'^[\s\W]+$',
        ]
        linhas = []
        for linha in texto.splitlines():
            s = linha.strip()
            if not s: continue
            if any(re.match(p, s, re.IGNORECASE) for p in LIXO): continue
            if len(s.split()) < 4 and len(s) < 20: continue
            linhas.append(re.sub(r'[ \t]{2,}', ' ', s))
        return re.sub(r'\n{3,}', '\n\n', '\n'.join(linhas)).strip()

    def _limpar_pdf(self, texto_bruto: str) -> str:
        if not texto_bruto: return ""
        # Remove soft hyphens (U+00AD) que aparecem em PDFs como separadores invisíveis
        texto = texto_bruto.replace('\u00ad', '')
        # Reconstrói palavras quebradas com hífen no fim de linha:
        #   "caimento má-\nximo" → "caimento máximo"
        # Cobre hífen normal (-) e hífen suave residual (\u00ad)
        texto = re.sub(r'(\w)[\-\u00ad]\n(\w)', r'\1\2', texto)
        # Remove linhas repetidas (cabeçalho/rodapé de página duplicado ≥3×)
        linhas     = texto.splitlines()
        contagem   = Counter(l.strip() for l in linhas if len(l.strip()) > 5)
        repeticoes = {l for l, c in contagem.items() if c >= 3}
        linhas     = [l for l in linhas if l.strip() not in repeticoes]
        return self._limpar_texto('\n'.join(linhas))

    # ─────────────────────────────────────────────────────────────────────────
    #  ALERTAS DE ERRO DE LEITURA
    # ─────────────────────────────────────────────────────────────────────────

    def _alertar_erro_leitura(self, arquivo: str, tipo_erro: str, detalhe: str = ''):
        sep = '─' * 62
        print(f"\n{sep}")
        print(f"  🚨 ALERTA DE LEITURA — {arquivo}")
        print(sep)
        msgs = {
            "pdf_protegido": (
                "❌  PDF protegido por senha ou criptografado.",
                "   ➡  Remova a proteção antes de ingerir o arquivo.\n"
                "   ➡  PDFs de scanner precisam de OCR externo (ex: Adobe Acrobat).\n"
                "   ➡  Prefira DOCX para documentos editáveis — melhor resultado."
            ),
            "pdf_qualidade_baixa": (
                "⚠️  Texto extraído com qualidade baixa (possível OCR sujo ou scanner).",
                "   ➡  Use um limpador de PDF antes de ingerir.\n"
                "   ➡  PDFs gerados diretamente de Word/LaTeX têm melhor qualidade.\n"
                "   ➡  DOCX é sempre preferível para textos editáveis."
            ),
            "pdf_sem_texto": (
                "❌  PDF sem texto extraível — provavelmente é uma imagem escaneada.",
                "   ➡  Aplique OCR (Adobe, ABBYY FineReader, Tesseract) antes.\n"
                "   ➡  DOCX gerado pelo Word contém o texto nativo e não tem este problema."
            ),
            "docx_corrompido": (
                "❌  Arquivo DOCX corrompido ou com formato incompatível.",
                "   ➡  Abra no Word e salve novamente como .docx.\n"
                "   ➡  Verifique se não está em formato .doc (Word 97-2003 antigo)."
            ),
            "docx_sem_topicos": (
                "⚠️  Nenhuma seção numerada encontrada (ex: 1.1, 2.3.1).",
                "   ➡  Adicione numeração de títulos no Word para melhor extração.\n"
                "   ➡  Estilos de Título (Título 1, Título 2) também são detectados."
            ),
            "generico": (
                "❌  Erro inesperado ao processar o arquivo.",
                f"   ➡  Detalhe técnico: {detalhe}"
            ),
        }
        titulo, instrucoes = msgs.get(tipo_erro, msgs["generico"])
        print(f"  {titulo}")
        if detalhe and tipo_erro != "generico":
            print(f"  📋 Detalhe: {detalhe}")
        print(instrucoes)
        print(f"{sep}\n")

    def _dica_formato(self):
        print(
            "  💡 DICA DE FORMATO:\n"
            "  ┌──────────────────────────────────────────────────────────┐\n"
            "  │  DOCX → laudos, pareceres, textos editáveis              │\n"
            "  │         Preserva numeração, parágrafos e estrutura.      │\n"
            "  │  PDF  → normas técnicas (NBR/ABNT), livros               │\n"
            "  │         Funciona bem quando o PDF tem texto embutido.    │\n"
            "  │  ⚠️  PDFs de scanner (imagem) precisam de OCR externo.   │\n"
            "  └──────────────────────────────────────────────────────────┘\n"
        )

    # ─────────────────────────────────────────────────────────────────────────
    #  PALAVRAS-CHAVE E SINÔNIMOS
    # ─────────────────────────────────────────────────────────────────────────

    def _top5_palavras(self, texto: str) -> List[str]:
        palavras = re.findall(r'[a-zA-ZÀ-ú]{4,}', texto.lower())
        filtradas = [p for p in palavras if p not in STOPWORDS_PT]
        if not filtradas: return []
        return [w for w, _ in Counter(filtradas).most_common(5)]

    def _expandir_sinonimos(self, palavras: List[str]) -> Dict[str, List[str]]:
        expansao = {}
        for palavra in palavras:
            if palavra in DICIONARIO_SINONIMOS:
                expansao[palavra] = DICIONARIO_SINONIMOS[palavra]
                continue
            for conceito, sins in DICIONARIO_SINONIMOS.items():
                if palavra in sins:
                    expansao[palavra] = [conceito] + [s for s in sins if s != palavra]
                    break
        return expansao

    def _extrair_palavras_chave(self, texto: str) -> str:
        if not texto or len(texto.strip()) < 20: return ""
        texto_lower = texto.lower()
        chaves = set()
        for conceito, sins in DICIONARIO_SINONIMOS.items():
            if conceito in texto_lower or any(s in texto_lower for s in sins):
                chaves.add(conceito)
        if YAKE_DISPONIVEL:
            try:
                for kw in extrator_yake.extract_keywords(texto):
                    chaves.add(kw[0].lower())
            except Exception: pass
        # Inclui top5 palavras e seus sinônimos
        top5 = self._top5_palavras(texto)
        chaves.update(top5)
        for sins in self._expandir_sinonimos(top5).values():
            chaves.update(sins[:2])
        chaves.discard('')
        return ", ".join(list(chaves)[:15])

    # ─────────────────────────────────────────────────────────────────────────
    #  EXTRAÇÃO DE PARÂMETROS NORMATIVOS (regex)
    # ─────────────────────────────────────────────────────────────────────────

    def _extrair_parametros(self, texto: str, laudo_id: int, topico_id: int,
                            item_ref: str = '', pagina: int = 0,
                            tipo_fonte: str = 'outro'):
        """
        Extrai parâmetros técnicos (alturas, cargas, durações, etc.) do texto
        via regex. Salva automaticamente no banco. Funciona SEM IA.

        Além de salvar o valor pontual em parametros_normativos, detecta
        intervalos numéricos (ex: "15 mm a 25 mm") via extrair_intervalo()
        e os persiste em parametros_extraidos quando disponível.
        """
        texto_lower = texto.lower()
        encontrados = 0
        tem_intervalo_db = hasattr(self.db, 'salvar_parametro_intervalo')

        for nome, padrao, grp_val, grp_uni in PADROES_PARAMETROS:
            for m in re.finditer(padrao, texto_lower, re.IGNORECASE):
                try:
                    valor   = m.group(grp_val)
                    unidade = m.group(grp_uni) if grp_uni and grp_uni <= len(m.groups()) else ''
                    # Contexto: trecho de 80 chars ao redor do match
                    inicio   = max(0, m.start() - 40)
                    fim      = min(len(texto_lower), m.end() + 40)
                    contexto = texto_lower[inicio:fim].replace('\n', ' ').strip()

                    # ── Salvar valor pontual (tabela original) ──────────────
                    self.db.salvar_parametro(
                        laudo_id=laudo_id, topico_id=topico_id,
                        parametro=nome, valor=valor, unidade=unidade,
                        contexto=contexto, item_ref=item_ref, pagina=pagina
                    )
                    encontrados += 1

                    # ── Detectar e salvar intervalo (tabela nova) ───────────
                    if tem_intervalo_db:
                        intervalo = extrair_intervalo(contexto)
                        if intervalo:
                            val_min, val_max, uni_iv = intervalo
                            # Usar unidade do intervalo se mais específica
                            uni_final = uni_iv if uni_iv else unidade
                            try:
                                self.db.salvar_parametro_intervalo(
                                    topico_id=topico_id,
                                    laudo_id=laudo_id,
                                    nome=nome,
                                    val_min=val_min,
                                    val_max=val_max,
                                    unidade=uni_final,
                                    contexto=contexto,
                                    item_ref=item_ref,
                                    pagina=pagina,
                                )
                            except Exception:
                                pass  # Não interromper ingestão por falha no intervalo

                except Exception:
                    pass

        if encontrados:
            print(f"      📐 {encontrados} parâmetro(s) normativo(s) extraído(s).")

    # ─────────────────────────────────────────────────────────────────────────
    #  EXTRAÇÃO DE QUESITOS — sem IA
    # ─────────────────────────────────────────────────────────────────────────

    def _extrair_quesitos_texto(self, texto: str, laudo_id: int, titulo_secao: str) -> int:
        """Extrai pares pergunta/resposta de seção de Quesitos via regex. Sem IA."""
        texto_norm = re.sub(r'\s+', ' ', texto).strip()
        blocos     = re.split(r'(?i)\bRESPOSTA\s*:', texto_norm)
        pares: list = []
        perg_pend   = ''
        for i, bloco in enumerate(blocos):
            if i == 0:
                perg_pend = bloco.strip(); continue
            partes   = re.split(r'(?=\b[A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕ][^.!?]{10,}\?)', bloco, maxsplit=1)
            resposta = partes[0].strip()
            prox     = partes[1].strip() if len(partes) > 1 else ''
            segs     = re.split(r'(?<=\?)\s+', perg_pend)
            perg     = segs[-1].strip() if segs else perg_pend
            if perg and len(perg) > 15 and resposta and len(resposta) > 5:
                pares.append({'pergunta': perg[:800], 'resposta': resposta[:3000]})
            perg_pend = prox
        for par in pares:
            self.db.salvar_quesito(laudo_id, titulo_secao, par['pergunta'], par['resposta'])
        if pares:
            print(f"      ⚖️  {len(pares)} quesito(s) de '{titulo_secao}'.")
        return len(pares)

    # ─────────────────────────────────────────────────────────────────────────
    #  GRAU DE RISCO E MATRIZ GUT — sem IA
    # ─────────────────────────────────────────────────────────────────────────

    _RE_GRAU_RISCO    = re.compile(
        r'grau\s+de\s+risco[:\s]+([Cc]r[íi]tico|[Gg]rave|[Mm][íi]nimo|[Mm][óo]derad[oa]|[Mm][éeê]dio)',
        re.IGNORECASE)
    _RE_GRAU_ISOLADO  = re.compile(
        r'(?:^|\n)\s*([Cc]r[íi]tico|[Gg]rave|[Mm][éeê]dio|[Mm][íi]nimo)\s*(?:\n|$)')
    _RE_ANOMALIA_TIPO = re.compile(
        r'\b(End[ôo]gena|Ex[oó]gena|Natural|Funcional)\b', re.IGNORECASE)
    _GUT_PADRAO = {
        'Crítico': 'G:5, U:5, T:5', 'Grave': 'G:4, U:4, T:4',
        'Médio':   'G:3, U:3, T:3', 'Mínimo':'G:2, U:2, T:2',
    }

    def _extrair_grau_risco(self, texto: str) -> str:
        m = self._RE_GRAU_RISCO.search(texto)
        if m: return m.group(1).capitalize()
        m2 = self._RE_GRAU_ISOLADO.search(texto)
        return m2.group(1).strip().capitalize() if m2 else '-'

    def _extrair_tipo_anomalia(self, texto: str) -> str:
        m = self._RE_ANOMALIA_TIPO.search(texto)
        return m.group(1).capitalize() if m else '-'

    # ─────────────────────────────────────────────────────────────────────────
    #  PROCESSAMENTO SEM IA (offline)
    # ─────────────────────────────────────────────────────────────────────────

    def _processar_sem_ia(self, texto: str, titulo: str) -> str:
        TERMOS = [
            'fissura','trinca','rachadura','infiltração','umidade','eflorescência',
            'corrosão','recalque','desplacamento','carbonatação','armadura',
            'ferrugem','mancha','mofo','bolor','impermeabilização','fundação',
            'estrutura','concreto','alvenaria','revestimento','argamassa',
            'aterro','solo','compactação','subsidência','drenagem','erosão',
            'nbr','abnt','norma','requisito','especificação','procedimento',
            'patologia','diagnóstico','reparo','manutenção','vistoria','inspeção',
            'guarda-corpo','parapeito','carga','resistência','desempenho',
        ]
        achados = [t for t in TERMOS if t in texto.lower()]
        if not achados:
            return "CONTEÚDO_IRRELEVANTE"
        return (
            f"[PROCESSADO SEM IA — MODO OFFLINE]\n"
            f"Tópico: {titulo}\n"
            f"Termos técnicos: {', '.join(sorted(set(achados)))}\n\n"
            f"--- TEXTO ORIGINAL ---\n{texto[:2000]}{'...' if len(texto) > 2000 else ''}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    #  EXTRAÇÃO DE TÓPICOS (DOCX)
    # ─────────────────────────────────────────────────────────────────────────

    # Padrões para filtrar dados pessoais/jurídicos do cabeçalho do laudo
    _FILTRO_DADOS_PESSOAIS = re.compile(
        r'polo\s+(ativo|passivo)|cpf[:\s]|cnpj[:\s]|exmo\.|exma\.|'
        r'juízo\s+d[ao]|vara\s+c[íi]vel|comarca\s+de|processo\s*n[°º]?[\s:]\d|'
        r'processo:\s*\d|perito:\s+\w|advogad[oa]:|assistente\s+técnic[oa]',
        re.IGNORECASE
    )
    # Seções que devem ser EXCLUÍDAS da indexação técnica
    _SECOES_IGNORAR = re.compile(
        r'^(SUMÁRIO|INTRODUÇÃO|IDENTIFICAÇÃO\s+DAS\s+PARTES|COMUNICAÇÃO\s+DA\s+PERÍCIA|'
        r'LINHA\s+DO\s+TEMPO|ANEXOS?|ART\.?$|ORÇAMENTO|GLOSSÁRIO)',
        re.IGNORECASE
    )

    def extrair_topicos_word(self, caminho: str) -> List[Dict]:
        try:
            doc = docx.Document(caminho)
        except Exception as e:
            self._alertar_erro_leitura(os.path.basename(caminho), "docx_corrompido", str(e))
            return []

        topicos       = []
        topico_atual  = None  # Não inicia com "Geral/Introdução" — evita capturar cabeçalho
        self.chunker  = PericialChunker()
        contador_sec  = [0]  # Contador para numeração de seções sem número explícito

        # Regex 1: título com número explícito no texto  (ex: "14.3.1 Requisito...")
        re_num_texto = re.compile(r'^(\d+(?:\.\d+)*)\.?\s+([A-ZÀ-Úa-zà-ú].{2,})$')
        # Regex 2: título MAIÚSCULO simples sem número (ex: "GUARDA CORPO" em Heading style)
        re_maiusc    = re.compile(r'^([A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕ][A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕ\s\-\/]{3,})$')

        def _e_heading(p) -> bool:
            """Detecta se parágrafo é um título/heading do Word."""
            nome = (p.style.name or '').lower()
            return (nome.startswith('heading') or
                    nome.startswith('título') or
                    nome.startswith('title') or
                    nome in ('heading 1','heading 2','heading 3',
                              'título 1','título 2','título 3'))

        def _salvar_atual():
            if topico_atual and topico_atual.get('texto', '').strip():
                topicos.append(dict(topico_atual))

        for p in doc.paragraphs:
            texto = p.text.strip()
            if not texto: continue
            # Ignora linhas de sumário (pontinhos ....... 99)
            if re.search(r'\.{3,}\s*\d+\s*$', texto): continue

            # ── Detecção de seção nova ────────────────────────────────────────
            novo_titulo = None
            novo_num    = None

            m = re_num_texto.match(texto)
            if m and len(texto.split()) <= 20:
                novo_num   = m.group(1)
                novo_titulo = m.group(2).strip()

            elif _e_heading(p) and len(texto.split()) <= 15:
                # Heading style — o número pode estar no texto ou ser automático
                m2 = re_num_texto.match(texto)
                if m2:
                    novo_num   = m2.group(1)
                    novo_titulo = m2.group(2).strip()
                else:
                    # Número automático do Word — gera um contador sequencial
                    contador_sec[0] += 1
                    novo_num   = f"H{contador_sec[0]}"
                    novo_titulo = texto

            if novo_titulo:
                # Filtra seções não-técnicas (sumário, introdução, identificação das partes…)
                if self._SECOES_IGNORAR.match(novo_titulo):
                    topico_atual = None  # Descarta o que vier depois também
                    continue

                _salvar_atual()
                self.chunker._atualizar_hierarquia(novo_num, novo_titulo)
                topico_atual = {
                    'numero':    novo_num,
                    'titulo':    novo_titulo,
                    'texto':     '',
                    'hierarquia': self.chunker.hierarquia_como_string(),
                    '_ignorar':  False,
                }
                continue

            # ── Corpo de texto ────────────────────────────────────────────────
            if topico_atual is None:
                # Ainda no cabeçalho — verifica se contém dados pessoais
                if self._FILTRO_DADOS_PESSOAIS.search(texto):
                    continue  # Descarta silenciosamente
                # Se parece conteúdo técnico, inicia um tópico "Preâmbulo"
                if len(texto.split()) > 12 and not self._FILTRO_DADOS_PESSOAIS.search(texto):
                    topico_atual = {
                        'numero': 'PRE', 'titulo': 'Preâmbulo Técnico',
                        'texto': '', 'hierarquia': '', '_ignorar': False,
                    }

            if topico_atual:
                # Bloqueia dados pessoais mesmo dentro de seções
                if self._FILTRO_DADOS_PESSOAIS.search(texto) and topico_atual['numero'] in ('-', 'PRE', 'H1'):
                    continue
                topico_atual['texto'] += texto + '\n'

        _salvar_atual()

        if not topicos:
            self._alertar_erro_leitura(os.path.basename(caminho), "docx_sem_topicos")

        validos = []
        for t in topicos:
            limpo = self._limpar_texto(t['texto'])
            if self._texto_utilizavel(limpo, t['titulo']):
                t['texto'] = limpo
                validos.append(t)

        print(f"   📑 {len(validos)} seção(ões) válida(s) extraída(s) do DOCX.")
        return validos

    # ─────────────────────────────────────────────────────────────────────────
    #  EXTRAÇÃO DE TEXTO (PDF) — com PericialChunker
    # ─────────────────────────────────────────────────────────────────────────

    # Helpers pdfplumber
    _RE_TITULO_TABELA = re.compile(
        r'(Tabela|Quadro)\s+[\d\.]+[\s\-\u2014\u2013].*', re.IGNORECASE
    )

    def _serializar_tabela_csv(self, tabela: list) -> str:
        """CSV inline com separador ;. Retorna vazio se tabela sem conteudo."""
        linhas = []
        for row in (tabela or []):
            if row is None: continue
            celulas = [str(c).strip() if c is not None else "" for c in row]
            if any(celulas): linhas.append(";".join(celulas))
        return "\n".join(linhas)

    def _detectar_titulo_tabela(self, texto_pagina: str, n_tabela: int) -> str:
        """Procura Tabela X / Quadro X no texto da pagina."""
        m = self._RE_TITULO_TABELA.search(texto_pagina)
        return m.group(0).strip() if m else f"Tabela {n_tabela}"

    def _extrair_pagina_pdfplumber(self, page, contador_tabela: list) -> str:
        """Extrai texto + tabelas de uma pagina pdfplumber.
        contador_tabela: lista [N] mutavel por referencia (unico por documento).
        """
        import logging as _log; logger = _log.getLogger(__name__)
        texto_pagina = page.extract_text() or ""
        blocos: list = []
        try:
            tabelas = page.extract_tables() or []
        except Exception as e:
            logger.warning(f"pdfplumber: falha ao extrair tabelas desta pagina: {e}")
            tabelas = []
        for tabela in tabelas:
            if not tabela: continue
            csv_texto = self._serializar_tabela_csv(tabela)
            if not csv_texto.strip(): continue
            contador_tabela[0] += 1
            n = contador_tabela[0]
            titulo = self._detectar_titulo_tabela(texto_pagina, n)
            blocos.append(
                f"\n[[TABELA_{n}]] {titulo}\n"
                f"{csv_texto}\n"
                f"[[/TABELA_{n}]]\n"
            )
        return texto_pagina + "".join(blocos)

    # EXTRACAO DE TEXTO (PDF) com pdfplumber + fallback pypdf

    def extrair_texto_pdf(self, caminho: str) -> str:
        """
        Extrai texto do PDF com suporte a tabelas estruturadas.
        Nivel 1: pdfplumber disponivel - extrai texto + tabelas marcadas [[TABELA_N]].
        Nivel 2: pdfplumber falha em pagina especifica - pypdf para aquela pagina.
        Nivel 3: pdfplumber nao instalado ou falha global - pypdf para o documento todo.
        """
        import logging as _log; logger = _log.getLogger(__name__)
        nome = os.path.basename(caminho)

        # Verificacao antecipada de criptografia
        try:
            leitor_check = pypdf.PdfReader(caminho)
            if leitor_check.is_encrypted:
                self._alertar_erro_leitura(nome, "pdf_protegido", "Arquivo criptografado")
                self._dica_formato(); return ""
            total_paginas = len(leitor_check.pages)
        except Exception as e:
            self._alertar_erro_leitura(nome, "generico", str(e)); return ""

        paginas_texto: list = []; total_tabelas = 0; usou_pdfplumber = False

        # Nivel 1 / 2: pdfplumber
        if PDFPLUMBER_DISPONIVEL:
            try:
                contador_tabela = [0]
                with pdfplumber.open(caminho) as pdf:
                    pypdf_leitor = pypdf.PdfReader(caminho)
                    for n_pag, page in enumerate(pdf.pages):
                        try:
                            texto_pag = self._extrair_pagina_pdfplumber(page, contador_tabela)
                        except Exception as e_pag:
                            logger.warning(f"pdfplumber falhou pagina {n_pag+1} de {nome!r}: {e_pag}")
                            try:
                                texto_pag = pypdf_leitor.pages[n_pag].extract_text() or ""
                            except Exception: texto_pag = ""
                        if texto_pag.strip(): paginas_texto.append(texto_pag)
                total_tabelas = contador_tabela[0]; usou_pdfplumber = True
            except Exception as e_global:
                logger.info(f"pdfplumber falhou em {nome!r}: {e_global}. Usando pypdf.")
                paginas_texto = []

        # Nivel 3: pypdf puro
        if not paginas_texto:
            if not PDFPLUMBER_DISPONIVEL:
                logger.info(f"Usando pypdf (sem extracao de tabelas) para {nome!r}.")
            try:
                leitor = pypdf.PdfReader(caminho)
                paginas_texto = [p.extract_text() for p in leitor.pages if p.extract_text()]
            except Exception as e:
                self._alertar_erro_leitura(nome, "generico", str(e)); return ""

        if not paginas_texto:
            self._alertar_erro_leitura(nome, "pdf_sem_texto")
            self._dica_formato(); return ""

        texto_bruto = "\n".join(paginas_texto)
        score = self._calcular_qualidade(texto_bruto)
        if score < QUALIDADE_MINIMA:
            self._alertar_erro_leitura(
                nome, "pdf_qualidade_baixa",
                f"Score calculado: {score:.2f} (minimo: {QUALIDADE_MINIMA})"
            )
            self._dica_formato(); return ""

        modo = "(pdfplumber)" if usou_pdfplumber else "(pypdf, sem tabelas)"
        logger.info(f"[{nome}] Extracao: {total_paginas} pag., {total_tabelas} tab. {modo}")
        return self._limpar_pdf(texto_bruto)


    def extrair_paginas_pdf(self, caminho: str) -> List[Tuple[int, str]]:
        """
        Extrai texto do PDF página a página.
        Retorna lista de (num_pagina, texto_limpo), ignorando páginas vazias.
        Mantém o mesmo mecanismo de fallback pdfplumber → pypdf.
        """
        import logging as _log; logger = _log.getLogger(__name__)
        nome = os.path.basename(caminho)
        paginas: List[Tuple[int, str]] = []

        if PDFPLUMBER_DISPONIVEL:
            try:
                contador_tabela = [0]
                pypdf_leitor = pypdf.PdfReader(caminho)
                with pdfplumber.open(caminho) as pdf:
                    for n_pag, page in enumerate(pdf.pages, 1):
                        try:
                            texto = self._extrair_pagina_pdfplumber(page, contador_tabela)
                        except Exception:
                            try:
                                texto = pypdf_leitor.pages[n_pag - 1].extract_text() or ""
                            except Exception:
                                texto = ""
                        limpo = self._limpar_texto(texto)
                        if limpo.strip():
                            paginas.append((n_pag, limpo))
                return paginas
            except Exception as e:
                logger.info(f"extrair_paginas_pdf: pdfplumber falhou em {nome!r}: {e}. Usando pypdf.")

        # Fallback pypdf
        try:
            leitor = pypdf.PdfReader(caminho)
            for n_pag, page in enumerate(leitor.pages, 1):
                texto = page.extract_text() or ""
                limpo = self._limpar_texto(texto)
                if limpo.strip():
                    paginas.append((n_pag, limpo))
        except Exception as e:
            logger.warning(f"extrair_paginas_pdf: pypdf falhou em {nome!r}: {e}")
        return paginas

    @staticmethod
    def _titulo_do_trecho(texto: str, nome_arquivo: str, pagina: int) -> str:
        """Extrai título representativo: primeiro cabeçalho de seção ou primeira linha útil."""
        for linha in texto.split('\n')[:8]:
            l = linha.strip()
            # Cabeçalho de seção NBR: "4.1 Preparação" ou "4 Objetivo"
            if re.match(r'^\d+(?:\.\d+)*\.?\s+[A-ZÁÉÍÓÚÀÂÊÔÃÕÜ]', l) and len(l) < 100:
                return l
        for linha in texto.split('\n'):
            l = linha.strip()
            if len(l) > 15:
                return l[:90]
        return f"Pág.{pagina} — {os.path.splitext(nome_arquivo)[0][:40]}"

    def _processar_trechos_normativos(self, laudo_id: int, nome_arquivo: str,
                                      texto_completo: str,
                                      tipo_fonte: str = 'norma_abnt'):
        """
        Divide o PDF em chunks semânticos usando PericialChunker (nível 1-2).
        Cada seção "4.4 Caimento" inclui seus sub-itens "4.4.1", "4.4.2", etc.

        Fallback 1: se não detectar seções nível 1-2, tenta qualquer profundidade.
        Fallback 2: se ainda sem resultado, divide por parágrafos agrupados.
        """
        chunker = PericialChunker()
        chunks  = chunker.processar_texto_normativo(texto_completo, pagina=0)

        # Fallback 1 — tenta qualquer profundidade de seção
        if not chunks:
            _re_qualquer_nivel = re.compile(
                r'\n(?=\d+(?:\.\d+)*\.?\s+[A-ZÁÉÍÓÚÀÂÊÔÃÕÜÇ])'
            )
            partes = _re_qualquer_nivel.split(texto_completo)
            if len(partes) > 1:
                for parte in partes:
                    parte = parte.strip()
                    if len(parte) < 20:
                        continue
                    linhas  = parte.splitlines()
                    primeira = linhas[0].strip()
                    m = chunker.ITEM_REGEX.match(primeira)
                    if m:
                        numero = m.group(1)
                        titulo = m.group(2)[:120]
                        chunker._atualizar_hierarquia(numero, titulo)
                    else:
                        numero = 'p.0'
                        titulo = primeira[:80] or 'Trecho'
                    chunks.append({
                        'numero': numero, 'titulo': titulo,
                        'texto': parte,
                        'hierarquia': chunker.hierarquia_como_string(),
                        'pagina': 0,
                    })

        # Fallback 2 — agrupa parágrafos em blocos de ~1800 chars
        if not chunks:
            paragrafos = [p.strip() for p in texto_completo.split('\n') if p.strip()]
            grupo, chars, bloco_n = [], 0, 0
            for par in paragrafos:
                grupo.append(par)
                chars += len(par)
                if chars >= 1800 and par.endswith(('.', ':', ';', '!', '?')):
                    bloco_n += 1
                    bloco = '\n'.join(grupo)
                    chunks.append({
                        'numero': f"bloco_{bloco_n}",
                        'titulo': self._titulo_do_trecho(bloco, nome_arquivo, 0),
                        'texto': bloco, 'hierarquia': '', 'pagina': 0,
                    })
                    grupo, chars = [], 0
            if grupo:
                bloco_n += 1
                bloco = '\n'.join(grupo)
                chunks.append({
                    'numero': f"bloco_{bloco_n}",
                    'titulo': self._titulo_do_trecho(bloco, nome_arquivo, 0),
                    'texto': bloco, 'hierarquia': '', 'pagina': 0,
                })

        salvos = 0
        for chunk in chunks:
            if len(chunk['texto'].strip()) < 30:
                continue
            palavras_chave = extrair_palavras_chave_v2(
                texto=chunk['texto'],
                hierarquia=chunk.get('hierarquia', ''),
                tipo_documento=tipo_fonte,
                conn=None,
                max_palavras=10,
                usar_ia=False,
                ai_engine=self.ai,
            )
            topico_pai_id = self.db.resolver_pai(laudo_id, chunk['numero'])
            topico_id = self.db.salvar_topico(
                laudo_id=laudo_id,
                num=chunk['numero'], titulo=chunk['titulo'],
                orig=chunk['texto'], reescrito=chunk['texto'],
                palavras_chave=palavras_chave,
                hierarquia=chunk['hierarquia'],
                pagina=chunk['pagina'],
                token_count=PericialChunker._contar_tokens_aprox(chunk['texto']),  # M6
                topico_pai_id=topico_pai_id,
            )
            self._extrair_parametros(
                chunk['texto'], laudo_id, topico_id,
                item_ref=chunk['numero'], pagina=chunk['pagina']
            )
            salvos += 1

        print(f"   ✅ {salvos} trecho(s) indexado(s) com hierarquia.")

    # ─────────────────────────────────────────────────────────────────────────
    #  PROCESSAMENTO EM LOTE
    # ─────────────────────────────────────────────────────────────────────────

    def processar_lote(self, callback_interacao=None):
        processou_algo = False

        for ext, pasta_chave in [('.docx', 'doc'), ('.pdf', 'pdf')]:
            p_in  = self.pastas[pasta_chave]['in']
            p_out = self.pastas[pasta_chave]['out']

            p_err = self.pastas.get(pasta_chave, {}).get('err', pasta_chave + '_erros')
            os.makedirs(p_err, exist_ok=True)

            for arquivo in [f for f in os.listdir(p_in) if f.lower().endswith(ext)]:
                processou_algo = True
                print(f"\n{'═'*62}")
                print(f"  📄 PROCESSANDO: {arquivo}")
                print(f"{'═'*62}")

                laudo_id = (self.db.buscar_laudo_por_nome(arquivo) or
                            self.db.registrar_laudo(arquivo,
                                tipo_fonte='norma_abnt' if ext == '.pdf' else 'laudo_judicial'))
                caminho = os.path.join(p_in, arquivo)

                try:
                    if ext == '.docx':
                        topicos = self.extrair_topicos_word(caminho)
                        salvos = 0
                        for t in topicos:
                            if len(t['texto'].strip()) < 80: continue
                            ti = t['titulo'].upper()

                            # ── Seção QUESITOS → extrai Q&A sem IA ─────────────
                            if 'QUESITO' in ti:
                                print(f"   [⚖️] Quesitos: '{t['titulo']}'")
                                n_q = self._extrair_quesitos_texto(
                                    t['texto'], laudo_id, t['titulo'])
                                if n_q == 0:
                                    pares = self.ai.extrair_quesitos(t['texto'][:15000])
                                    for qa in pares:
                                        self.db.salvar_quesito(laudo_id, t['titulo'],
                                                               qa['pergunta'], qa['resposta'])
                                    if pares:
                                        print(f"      ✅ {len(pares)} via IA.")
                                    else:
                                        self.db.salvar_topico(
                                            laudo_id, t['numero'], t['titulo'],
                                            t['texto'], t['texto'],
                                            palavras_chave=extrair_palavras_chave_v2(
                                                texto=t['texto'],
                                                hierarquia=t.get('hierarquia', ''),
                                                tipo_documento='laudo_judicial',
                                                conn=None, max_palavras=10,
                                            ),
                                            hierarquia=t.get('hierarquia', ''),
                                            token_count=PericialChunker._contar_tokens_aprox(t['texto']),  # M6
                                            topico_pai_id=self.db.resolver_pai(laudo_id, t['numero']),
                                        )
                                continue

                            # ── Seções técnicas ──────────────────────────────────
                            analise = self.ai.processar_texto(t['texto'], t['titulo'])
                            if analise == "MODO_OFFLINE":
                                analise = self._processar_sem_ia(t['texto'], t['titulo'])

                            if "CONTEÚDO_IRRELEVANTE" not in analise.upper():
                                palavras_chave = extrair_palavras_chave_v2(
                                    texto=t['texto'],
                                    hierarquia=t.get('hierarquia', ''),
                                    tipo_documento='laudo_judicial',
                                    conn=None, max_palavras=10,
                                    usar_ia=False, ai_engine=self.ai,
                                )
                                grau = self._extrair_grau_risco(t['texto'])
                                anom = self._extrair_tipo_anomalia(t['texto'])
                                gut  = self._GUT_PADRAO.get(grau, '-')
                                topico_id = self.db.salvar_topico(
                                    laudo_id, t['numero'], t['titulo'],
                                    t['texto'], analise,
                                    risco=grau, gut=gut, criterio=anom,
                                    palavras_chave=palavras_chave,
                                    hierarquia=t.get('hierarquia', ''),
                                    token_count=PericialChunker._contar_tokens_aprox(t['texto']),  # M6
                                    topico_pai_id=self.db.resolver_pai(laudo_id, t['numero']),
                                )
                                # M7: análise IA separada do texto original
                                if analise and analise != t['texto']:
                                    self.db.salvar_analise_ia(topico_id, analise)
                                self._extrair_parametros(
                                    t['texto'], laudo_id, topico_id,
                                    item_ref=t['numero'], tipo_fonte='laudo_judicial')
                                salvos += 1
                            else:
                                print(f"   [!] Irrelevante: '{t['titulo']}'")
                        print(f"   ✅ {salvos} tópico(s) salvos.")

                    else:  # PDF
                        texto_pdf = self.extrair_texto_pdf(caminho)
                        if not texto_pdf.strip():
                            print(f"   ⛔ PDF não processável — ignorado.")
                        else:
                            tipo = 'norma_abnt' if any(
                                k in arquivo.lower() for k in ['nbr', 'abnt', 'norma']
                            ) else 'outro'
                            self._processar_trechos_normativos(laudo_id, arquivo, texto_pdf, tipo)

                    os.replace(caminho, os.path.join(p_out, arquivo))

                except Exception as _exc:
                    import traceback as _tb
                    print(f"   ❌ Erro ao processar '{arquivo}': {_exc}")
                    _tb.print_exc()
                    try:
                        os.replace(caminho, os.path.join(p_err, arquivo))
                        print(f"   ↳ Movido para '{p_err}'.")
                    except Exception:
                        pass

        # Imagens
        for pasta_img in ['img_normas', 'img_patologias']:
            p_in  = self.pastas[pasta_img]['in']
            p_out = self.pastas[pasta_img]['out']
            for arquivo in os.listdir(p_in):
                if not self._is_imagem_valida(arquivo): continue
                processou_algo = True
                laudo_id = (self.db.buscar_laudo_por_nome(arquivo) or
                            self.db.registrar_laudo(arquivo))
                if pasta_img == 'img_normas':
                    analise = self.ai.processar_imagem_norma(os.path.join(p_in, arquivo))
                    self.db.salvar_topico(laudo_id, "OCR", "Extração de Imagem",
                                         "[IMAGEM ORIGINAL]", analise)
                else:
                    dados = self.ai.processar_imagem_patologia(os.path.join(p_in, arquivo))
                    ar, ag = dados.get('risco', ''), dados.get('gut', '')
                    if callback_interacao:
                        ar, ag = callback_interacao(dados, arquivo)
                    self.db.salvar_topico(laudo_id, "IMG", "Análise Patológica Visual",
                                         dados.get('texto', ''), dados.get('texto', ''),
                                         dados.get('risco', ''), dados.get('gut', ''),
                                         dados.get('criterio', ''), ar, ag)
                os.replace(os.path.join(p_in, arquivo), os.path.join(p_out, arquivo))

        if not processou_algo:
            print("\n  📂 Nenhum arquivo encontrado nas pastas de entrada.")
        return processou_algo


# =============================================================================
# EXTRAÇÃO DE PALAVRAS-CHAVE v2.0 — 4 Camadas Técnico-Normativas
# Referência: IBAPE (2025) items 12.1-12.3 | NBR 13752:2024
# =============================================================================

import math
import sqlite3
import logging as _log_v2

_logger_v2 = _log_v2.getLogger("extrair_kw_v2")

# ── Regex de Camada 1 — Entidades Normativas ──────────────────────────────────
_RE_NBR = re.compile(
    r'(?:ABNT\s+)?NBR\s+\d{3,6}(?:[-:]\d+(?:[:\-]\d+)?)?',
    re.IGNORECASE,
)
_RE_PARAMETRO_QUANT = re.compile(
    r'\d+[,.]?\d*\s*'
    r'(?:mm\b|cm\b|m²\b|m³\b|MPa\b|kPa\b|kN/m²\b|kg/m²\b|%\b|anos?\b|dias?\b|horas?\b)',
    re.IGNORECASE,
)
_RE_ITEM_NORMATIVO = re.compile(r'[Ii]tem\s+\d+(?:\.\d+){1,4}')
_RE_TABELA_NORMATIVA = re.compile(r'[Tt]abela\s+\d+(?:\.\d+)?')

# IDF estático pré-calculado para modo sem banco
# (termos mais raros recebem score maior)
_IDF_ESTATICO: Dict[str, float] = {
    "fissura": 2.1, "eflorescência": 3.5, "recalque": 3.2,
    "desplacamento": 3.0, "carbonatação": 3.8, "corrosão de armadura": 3.6,
    "infiltração": 2.4, "impermeabilização": 2.8, "cobrimento": 2.9,
    "armadura": 2.3, "laje": 2.0, "fundação": 2.2, "fissuração": 2.5,
    "estanqueidade": 3.1, "guarda-corpo": 3.0, "vup": 3.7, "spt": 3.5,
    "pull-off": 4.0, "pacometria": 4.1, "esclerometria": 4.0,
    "termografia": 4.2, "nexo causal": 3.4, "vício construtivo": 3.3,
    "anomalia endógena": 3.5, "anomalia exógena": 3.5,
    "grau de risco crítico": 3.6, "vida útil de projeto": 3.8,
}


def extrair_entidades_normativas(texto: str) -> List[str]:
    """
    Camada 1: extrai entidades normativas via regex.
    Retorna lista deduplicada normalizada em lowercase.

    Args:
        texto: Texto do chunk a analisar.
    Returns:
        list[str] com NBRs, parâmetros quantitativos, itens e tabelas.

    Exemplo:
        extrair_entidades_normativas("NBR 6118:2023 — cobrimento 25 mm")
        # → ["nbr 6118:2023", "25 mm"]
    """
    encontrados: List[str] = []
    for padrao in [_RE_NBR, _RE_PARAMETRO_QUANT, _RE_ITEM_NORMATIVO, _RE_TABELA_NORMATIVA]:
        for m in padrao.finditer(texto):
            val = m.group(0).strip().lower()
            # Rejeita número isolado sem unidade (ex: "2024", "36")
            if padrao is _RE_PARAMETRO_QUANT and re.fullmatch(r'\d+', val):
                continue
            encontrados.append(val)
    # Deduplicação preservando ordem
    vistos: set = set()
    resultado = []
    for e in encontrados:
        if e not in vistos:
            vistos.add(e)
            resultado.append(e)
    return resultado


def tokenizar_tecnico(texto: str) -> List[str]:
    """
    Tokeniza texto preservando termos compostos com hífen e removendo ruído.

    Args:
        texto: Texto normalizado canonicamente.
    Returns:
        list[str] com tokens limpos (len >= 4, sem stopwords PT).

    Exemplo:
        tokenizar_tecnico("Fissura em guarda-corpo de concreto")
        # → ["fissura", "guarda-corpo", "concreto"]
    """
    # Lowercase e remoção de pontuação exceto hífen composto
    texto_lower = texto.lower()
    # Remove pontuação mantendo hifens entre palavras
    texto_clean = re.sub(r'(?<!\w)-|-(?!\w)', ' ', texto_lower)
    texto_clean = re.sub(r'[^\w\s\-]', ' ', texto_clean)
    tokens_raw = texto_clean.split()
    resultado = []
    for t in tokens_raw:
        if len(t) < 4:
            continue
        if t in STOPWORDS_PT:
            continue
        resultado.append(t)
    return resultado


def calcular_idf_tecnico_offline(
    tokens: List[str],
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, float]:
    """
    Calcula IDF técnico adaptativo.
    Se conn disponível: consulta banco real (SELECT COUNT FROM topicos).
    Se conn = None: usa IDF_ESTATICO pré-calculado.

    Args:
        tokens: Lista de tokens do texto.
        conn:   Conexão SQLite (opcional).
    Returns:
        dict {termo: score_tfidf} com score = TF × IDF × 0.60

    Exemplo:
        calcular_idf_tecnico_offline(["fissura", "laje"], conn=None)
        # → {"fissura": 0.84, "laje": 0.72}
    """
    if not tokens:
        return {}

    # TF local
    contagem: Dict[str, int] = {}
    for t in tokens:
        contagem[t] = contagem.get(t, 0) + 1
    total = max(len(tokens), 1)

    scores: Dict[str, float] = {}
    for termo, freq in contagem.items():
        tf = freq / total
        # IDF adaptativo ou estático
        if conn is not None:
            try:
                total_topicos = conn.execute("SELECT COUNT(*) FROM topicos").fetchone()[0]
                freq_banco = conn.execute(
                    "SELECT COUNT(*) FROM topicos WHERE palavras_chave LIKE ?",
                    (f"%{termo}%",),
                ).fetchone()[0]
                idf = math.log(total_topicos / (freq_banco + 1))
            except Exception as e:
                _logger_v2.warning(f"IDF banco falhou para '{termo}': {e}")
                idf = _IDF_ESTATICO.get(termo, 1.5)
        else:
            idf = _IDF_ESTATICO.get(termo, 1.5)

        score = tf * idf * 0.60
        if score > 0.05:
            scores[termo] = score

    return scores


def extrair_palavras_chave_v2(
    texto: str,
    hierarquia: str,
    tipo_documento: str,
    conn: Optional[sqlite3.Connection] = None,
    max_palavras: int = 10,
    usar_ia: bool = False,
    ai_engine: Optional[Any] = None,
    taxonomy_manager: Optional[Any] = None,
) -> str:
    """
    Extrai palavras-chave técnico-normativas contextuais em 4 camadas.

    Arquitetura:
      Camada 1: Entidades normativas (NBR, parâmetros quantitativos) — score 1.0
      Camada 2: Vocabulário pericial controlado (IBAPE + NBRs)       — score 0.85 × boost
      Camada 3: TF-IDF técnico adaptativo (banco ou estático)        — score 0.60
      Camada 4: Boost por seção e tipo de documento                  — multiplicador

    Referência: IBAPE (2025) items 12.1-12.3 | NBR 13752:2024

    Args:
        texto:           Texto do chunk/tópico a indexar.
        hierarquia:      Hierarquia da seção (ex: "H15 ANOMALIA").
        tipo_documento:  "norma_abnt"|"laudo_judicial"|"livro"|...
        conn:            Conexão SQLite para IDF adaptativo.
        max_palavras:    Máximo de termos no resultado (default: 10).
        usar_ia:         Se True e ai_engine disponível → usar Gemini.
        ai_engine:       Instância do AIEngine (opcional).
        taxonomy_manager: Instância do TaxonomyManager (opcional, cria se None).

    Returns:
        String de palavras-chave separadas por vírgula, ordenadas por score.
        Retorna "" para seções não-técnicas (preâmbulo, sumário).

    Raises:
        Nunca — todos os erros são capturados e logados com warning.

    Exemplo:
        extrair_palavras_chave_v2(
            "NBR 6118:2023 — cobrimento mínimo 25 mm. Fissura em pilar.",
            "H20 CRITÉRIO NORMATIVO", "norma_abnt"
        )
        # → "nbr 6118:2023, 25 mm, cobrimento de armadura, fissura, pilar"
    """
    try:
        # Carrega TaxonomyManager se não fornecido
        if taxonomy_manager is None:
            try:
                from taxonomy_manager import TaxonomyManager
                taxonomy_manager = TaxonomyManager()
            except Exception as e:
                _logger_v2.warning(f"TaxonomyManager não disponível: {e}")
                return _extrair_palavras_chave_fallback(texto, hierarquia)

        tm = taxonomy_manager

        # ── PASSO 0 — Verificar tipo de seção ────────────────────────────────
        info_secao = tm.inferir_tipo_secao(hierarquia)
        if info_secao["multiplicador"] == 0.0:
            _logger_v2.debug(f"Seção não técnica ignorada: {hierarquia[:50]}")
            return ""

        scores: Dict[str, float] = {}

        # ── PASSO 1 — Normalização canônica de sinônimos ─────────────────────
        texto_normalizado = tm.aplicar_normalizacao_canonica(texto)

        # ── PASSO 2 — Camada 1: Entidades normativas ─────────────────────────
        entidades = extrair_entidades_normativas(texto_normalizado)
        for entidade in entidades:
            scores[entidade] = 1.0

        # ── PASSO 3 — Camada 2: Vocabulário pericial controlado ──────────────
        tokens = tokenizar_tecnico(texto_normalizado)
        # Verificar tokens individuais e bigrams
        candidatos_vocab = set(tokens)
        # Bigrams para termos compostos (ex: "nexo causal", "grau de risco")
        for i in range(len(tokens) - 1):
            bigram = f"{tokens[i]} {tokens[i+1]}"
            candidatos_vocab.add(bigram)
        if len(tokens) > 2:
            for i in range(len(tokens) - 2):
                trigram = f"{tokens[i]} {tokens[i+1]} {tokens[i+2]}"
                candidatos_vocab.add(trigram)

        for candidato in candidatos_vocab:
            resultado_vocab = tm.buscar_vocabulario_pericial(candidato)
            if resultado_vocab and candidato not in scores:
                scores[candidato] = 0.85 * resultado_vocab["boost"]

        # ── PASSO 4 — Camada 3: TF-IDF técnico adaptativo ───────────────────
        if len(scores) < max_palavras:
            candidatos_tfidf = calcular_idf_tecnico_offline(tokens, conn)
            for termo, score in candidatos_tfidf.items():
                if termo not in scores:
                    scores[termo] = score

        # ── PASSO 5 — Camada 4: Boost por seção e tipo de documento ─────────
        multiplicador_secao = info_secao["multiplicador"]
        boost_tipo = tm.get_boost_tipo_doc(tipo_documento)
        categorias_boost = info_secao["categorias_boost"]

        for termo in list(scores.keys()):
            boost_cat = tm.calcular_boost_categoria(termo, categorias_boost)
            scores[termo] *= multiplicador_secao * boost_tipo * boost_cat

        # ── PASSO 6 — Filtros finais e ordenação ─────────────────────────────
        stopwords = tm.stopwords_tecnicas
        resultado = []
        for termo, _ in sorted(scores.items(), key=lambda x: -x[1]):
            if termo in stopwords:
                continue
            if len(termo) < 4 and termo.lower() not in {
                s.lower() for s in ["spt", "gut", "vup", "nbr", "idf", "cdc", "spda", "npa", "shs"]
            }:
                continue
            if tm.eh_fragmento_verbal(termo):
                continue
            if tm.eh_nome_proprio_ou_endereco(termo):
                continue
            resultado.append(termo)
            if len(resultado) >= max_palavras:
                break

        # ── PASSO 7 — Enriquecimento via IA (apenas se < 5 termos offline) ──
        if usar_ia and ai_engine is not None and len(resultado) < 5:
            try:
                resultado_ia = ai_engine.extrair_palavras_chave_ia(
                    texto=texto,
                    hierarquia=hierarquia,
                    tipo_documento=tipo_documento,
                    existentes=resultado,
                    max_palavras=max_palavras,
                )
                if resultado_ia:
                    resultado = resultado_ia
            except Exception as e:
                _logger_v2.warning(f"IA indisponível para enriquecimento: {e}")

        return ", ".join(resultado)

    except Exception as e:
        _logger_v2.warning(
            f"extrair_palavras_chave_v2 falhou: {e} | hierarquia={hierarquia[:50]}"
        )
        return ""


def _extrair_palavras_chave_fallback(texto: str, hierarquia: str) -> str:
    """
    Fallback mínimo quando TaxonomyManager não disponível.
    Usa apenas Camada 1 (entidades normativas).

    Args:
        texto: Texto a processar.
        hierarquia: Hierarquia da seção.
    Returns:
        String de entidades normativas encontradas.
    """
    entidades = extrair_entidades_normativas(texto)
    return ", ".join(entidades[:10])

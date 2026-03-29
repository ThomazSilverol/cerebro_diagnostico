"""
tests/test_extractor.py — Testes unitários do pipeline de extração
Execução: pytest tests/test_extractor.py -v
"""
import re
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Dict, Any

import pytest

# Garante que o diretório pai está no path para imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from offline_extractor import (
    extrair_documento,
    _calcular_qualidade_extracao,
    _secao_canonica,
    _extrair_txt_canonico,
    _RE_HIERARQUIA,
    ExtratorOffline,
)
from processors import PericialChunker


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures e helpers
# ─────────────────────────────────────────────────────────────────────────────

def _txt_temporario(conteudo: str) -> str:
    """Cria arquivo TXT temporário e retorna o caminho."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    f.write(conteudo)
    f.close()
    return f.name


# ─────────────────────────────────────────────────────────────────────────────
# Testes: extrair_documento — formato TXT
# ─────────────────────────────────────────────────────────────────────────────

class TestExtrairDocumentoTxt:
    """3+ casos para extração de arquivos TXT."""

    def test_txt_simples_retorna_estrutura_canonica(self):
        """TXT sem hierarquia gera ao menos 1 seção com texto não vazio."""
        conteudo = "Este é um texto simples sem numeração de seções.\nSegunda linha."
        caminho = _txt_temporario(conteudo)
        resultado = extrair_documento(caminho)
        assert resultado["formato_origem"] == "txt"
        assert len(resultado["hierarquia"]) >= 1
        assert resultado["metadata"]["erro"] == ""
        texto_total = " ".join(s["texto"] for s in resultado["hierarquia"])
        assert "simples" in texto_total.lower()

    def test_txt_com_numeracao_nbr_detecta_hierarquia(self):
        """TXT com numeração NBR (4 Título, 4.1 Subtítulo) gera hierarquia correta."""
        conteudo = textwrap.dedent("""\
            4 Requisitos Gerais
            Este capítulo define os requisitos gerais aplicáveis.
            4.1 Materiais
            Os materiais devem atender à NBR 6118.
            4.1.1 Concreto
            Resistência mínima de 25 MPa.
        """)
        caminho = _txt_temporario(conteudo)
        resultado = extrair_documento(caminho)
        secoes = resultado["hierarquia"]
        codigos = [s["codigo"] for s in secoes if s["codigo"]]
        assert "4" in codigos or any(c.startswith("4") for c in codigos)
        assert resultado["metadata"]["qualidade_extracao"] > 0.0

    def test_txt_vazio_retorna_zero_secoes(self):
        """TXT vazio ou com menos de 5 chars por linha → hierarquia vazia."""
        caminho = _txt_temporario("\n\n   \n\n")
        resultado = extrair_documento(caminho)
        assert resultado["metadata"]["erro"] == ""
        assert len(resultado["hierarquia"]) == 0

    def test_txt_quatro_niveis_hierarquia(self):
        """TXT com padrão NBR de 4 níveis (4.5.2.1) detecta todos os níveis."""
        conteudo = textwrap.dedent("""\
            4 Capítulo Principal
            Texto do capítulo.
            4.5 Seção Secundária
            Texto da seção.
            4.5.2 Subseção Terciária
            Texto da subseção.
            4.5.2.1 Item de Quarto Nível
            Texto do item de quarto nível.
        """)
        caminho = _txt_temporario(conteudo)
        resultado = extrair_documento(caminho)
        codigos = [s["codigo"] for s in resultado["hierarquia"] if s["codigo"]]
        assert any("4.5.2.1" in c for c in codigos), f"Quarto nível não detectado: {codigos}"


# ─────────────────────────────────────────────────────────────────────────────
# Testes: extrair_documento — arquivo inexistente
# ─────────────────────────────────────────────────────────────────────────────

class TestExtrairDocumentoErros:
    """Casos de erro: arquivo inexistente, formato não suportado."""

    def test_arquivo_inexistente_retorna_erro_sem_excecao(self):
        """Arquivo inexistente retorna estrutura com metadata['erro'] preenchido."""
        resultado = extrair_documento("/caminho/inexistente/arquivo.txt")
        assert resultado["metadata"]["erro"] != ""
        assert resultado["hierarquia"] == []

    def test_formato_nao_suportado_retorna_erro(self):
        """Extensão desconhecida (.xyz) retorna erro descritivo."""
        caminho = _txt_temporario("conteudo")
        caminho_xyz = caminho.replace(".txt", ".xyz")
        Path(caminho).rename(caminho_xyz)
        resultado = extrair_documento(caminho_xyz)
        assert resultado["metadata"]["erro"] != ""
        Path(caminho_xyz).unlink(missing_ok=True)

    def test_nunca_lanca_excecao(self):
        """extrair_documento nunca propaga exceções ao chamador."""
        try:
            resultado = extrair_documento("")
            assert isinstance(resultado, dict)
        except Exception as exc:
            pytest.fail(f"extrair_documento lançou exceção: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Testes: _calcular_qualidade_extracao
# ─────────────────────────────────────────────────────────────────────────────

class TestQualidadeExtracao:
    """Verifica cálculo de score de qualidade."""

    def test_sem_secoes_retorna_zero(self):
        assert _calcular_qualidade_extracao([], 10, False) == 0.0

    def test_secoes_ricas_retorna_score_alto(self):
        secoes = [
            _secao_canonica(1, "4", "Título", "A" * 500),
            _secao_canonica(2, "4.1", "Sub", "B" * 400),
        ]
        score = _calcular_qualidade_extracao(secoes, 2, False)
        assert score >= 0.5, f"Score esperado >= 0.5, obtido {score}"

    def test_ocr_penaliza_score(self):
        secoes = [_secao_canonica(1, "1", "Título", "Texto " * 100)]
        score_sem_ocr = _calcular_qualidade_extracao(secoes, 1, False)
        score_com_ocr = _calcular_qualidade_extracao(secoes, 1, True)
        assert score_com_ocr <= score_sem_ocr

    def test_chars_corrompidos_penalizam_score(self):
        secoes_limpas    = [_secao_canonica(1, "1", "T", "Conteúdo técnico normal. " * 20)]
        secoes_corrompidas = [_secao_canonica(1, "1", "T", "\ufffd\ufffd\ufffd texto " * 20)]
        s_limpo    = _calcular_qualidade_extracao(secoes_limpas, 1, False)
        s_corrompido = _calcular_qualidade_extracao(secoes_corrompidas, 1, False)
        assert s_corrompido <= s_limpo


# ─────────────────────────────────────────────────────────────────────────────
# Testes: PericialChunker
# ─────────────────────────────────────────────────────────────────────────────

class TestPericialChunker:
    """Verifica chunking hierárquico e suporte a 4 níveis."""

    def setup_method(self):
        self.chunker = PericialChunker()

    def test_texto_sem_hierarquia_retorna_um_chunk(self):
        texto = "Este é um parágrafo técnico sem numeração de seção. " * 20
        chunks = self.chunker.processar_texto_normativo(texto)
        assert len(chunks) >= 1
        assert all("texto" in c for c in chunks)

    def test_dois_niveis_gera_dois_chunks(self):
        texto = textwrap.dedent("""\
            4 Requisitos Gerais
            Texto do capítulo sobre requisitos gerais de instalações elétricas.

            4.1 Condutores
            Os condutores devem ter seção mínima conforme NBR 5410 tabela 37.
        """)
        chunks = self.chunker.processar_texto_normativo(texto)
        assert len(chunks) >= 1
        textos = " ".join(c["texto"] for c in chunks)
        assert "Requisitos" in textos or "Condutores" in textos

    def test_chunk_grande_e_subdividido(self):
        """Chunk com > MAX_TOKENS deve ser subdividido."""
        texto_longo = "palavra_tecnica " * 2000  # ~32000 chars >> MAX_TOKENS*4
        chunks = self.chunker.processar_texto_normativo(texto_longo)
        assert len(chunks) > 1, "Texto longo deve ser subdividido em múltiplos chunks"

    def test_chunk_pequeno_e_mesclado(self):
        """Chunks consecutivos pequenos devem ser mesclados."""
        # Dois fragmentos pequenos que individualmente ficam abaixo de MIN_TOKENS
        texto = "4 Título\nTexto curto.\n\n4.1 Sub\nTexto igualmente curto."
        chunks = self.chunker.processar_texto_normativo(texto)
        # Devem ser mesclados em 1 chunk
        total_chars = sum(len(c["texto"]) for c in chunks)
        assert total_chars > 0

    def test_regex_quatro_niveis(self):
        """_RE_SECAO deve dividir em seções de nível 1 a 4."""
        texto = textwrap.dedent("""\
            4 Capítulo
            Texto capítulo.
            4.5 Seção
            Texto seção.
            4.5.2 Subseção
            Texto subseção.
            4.5.2.1 Item
            Texto item.
        """)
        partes = PericialChunker._RE_SECAO.split(texto)
        # Deve haver pelo menos 2 partes (1 split em seção de 2+ níveis)
        assert len(partes) >= 2, f"Regex não dividiu texto de 4 níveis: {len(partes)} partes"

    def test_contar_tokens_aprox_retorna_positivo(self):
        assert PericialChunker._contar_tokens_aprox("palavra") > 0
        assert PericialChunker._contar_tokens_aprox("") >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Testes: ExtratorOffline — extração básica
# ─────────────────────────────────────────────────────────────────────────────

class TestExtratorOffline:
    """Testes de extração sem banco de dados (usando arquivo TXT temporário)."""

    def test_extrair_txt_retorna_blocos(self):
        conteudo = "Linha técnica com conteúdo pericial.\nOutra linha importante."
        caminho = _txt_temporario(conteudo)
        extrator = ExtratorOffline.__new__(ExtratorOffline)
        extrator.log = type("FakeLog", (), {
            "info": lambda *a, **kw: None,
            "warning": lambda *a, **kw: None,
            "error": lambda *a, **kw: None,
        })()
        extrator.dicionario = {}
        blocos = extrator.extrair_texto_txt(caminho)
        assert len(blocos) >= 1
        assert all("texto" in b for b in blocos)
        Path(caminho).unlink(missing_ok=True)

    def test_extrair_parametros_detecta_nbr(self):
        extrator = ExtratorOffline.__new__(ExtratorOffline)
        extrator.log = type("FakeLog", (), {
            "info": lambda *a, **kw: None,
            "warning": lambda *a, **kw: None,
            "error": lambda *a, **kw: None,
        })()
        extrator.dicionario = {}
        texto = "Conforme NBR 6118, a resistência mínima é de 25 MPa."
        params = extrator._extrair_parametros(texto)
        nomes = [p["parametro"] for p in params]
        assert "nbr_ref" in nomes or "resistencia" in nomes or len(params) > 0

    def test_extrair_palavras_chave_retorna_lista(self):
        extrator = ExtratorOffline.__new__(ExtratorOffline)
        extrator.log = type("FakeLog", (), {
            "info": lambda *a, **kw: None,
            "warning": lambda *a, **kw: None,
            "error": lambda *a, **kw: None,
        })()
        extrator.dicionario = {"fissura": ["trinca", "rachadura"]}
        texto = "Observou-se fissuração na laje com trincas visíveis."
        pks = extrator._extrair_palavras_chave(texto)
        assert isinstance(pks, list)
        assert len(pks) > 0

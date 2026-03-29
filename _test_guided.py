"""
Script de teste guiado — simula analise_img com inputs pré-definidos.
Todas as perguntas são exibidas junto com a resposta injetada.
"""
import sys, os, io
from unittest.mock import patch
from collections import deque

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── SEQUÊNCIA DE INPUTS ─────────────────────────────────────────────────────
# Cada item: (resposta, comentário para log)
RESPOSTAS = deque([
    # ── Seleção de laudo ────────────────────────────────────────────────────
    ("n",                  "→ Novo laudo"),
    ("Laudo Guiado",       "→ Nome do laudo"),
    ("",                   "→ Descrição [pular]"),
    ("",                   "→ Perito [pular]"),

    # ── Visual manual (Ollama não analisa imagem) ───────────────────────────
    ("0",                  "→ Sem base de análise anterior — preencher do zero"),
    ("fissura horizontal", "→ Tipo provável"),
    ("fissura de interface alvenaria/viga", "→ Subtipo"),
    ("muro externo",       "→ Elemento"),
    ("encontro muro/casa", "→ Localização"),
    ("Trinca horizontal em muro externo na interface entre alvenaria e viga. Ausência de junta de dilatação.", "→ Descrição"),
    ("progressiva",        "→ Indícios de progressão"),

    # ── GUT Adaptativo ──────────────────────────────────────────────────────
    ("01",                 "→ Item/referência"),
    ("Muro externo",       "→ Localização GUT"),
    ("2",                  "→ Subsistema: Acabamento"),
    ("2",                  "→ NC1: Endógena — falha de execução"),
    ("1",                  "→ NC2: Mecânico"),
    ("2",                  "→ NC3: Ativa com progressão estável"),
    ("Ausência de tela galvanizada e junta de dilatação no encontro muro/casa", "→ NC4 causa raiz"),
    ("1",                  "→ G1: revestimento de fachada"),
    ("3",                  "→ G2: localizado 5-25%"),
    ("2",                  "→ G3: risco de lesão"),
    ("3",                  "→ G4: dificulta uso"),
    ("3",                  "→ U1: moderada 1-3 meses"),
    ("2",                  "→ U2: uso frequente"),
    ("2",                  "→ U3: reversível intervenção complexa"),
    ("3",                  "→ U4: prazo >90 dias"),
    ("2",                  "→ T1: ativa progressão lenta"),
    ("1",                  "→ T2: múltiplos agentes contínuos"),
    ("2",                  "→ T3: relatada por usuários"),
    ("2",                  "→ T4: exposição moderada 60-180 dias"),
    ("n",                  "→ Sobreposição G/U [não revisar]"),
    ("s",                  "→ Salvar GUT"),

    # ── IBAPE ───────────────────────────────────────────────────────────────
    ("",                   "→ ENTER para iniciar IBAPE"),
    ("",                   "→ Aceitar título pré-preenchido"),
    ("",                   "→ Aceitar data (hoje)"),
    ("",                   "→ Confirmar origem Endógena (do GUT)"),
    # Natureza: auto-classificada como Vício Construtivo (1 opção)
    ("",                   "→ Aceitar sistema Acabamento (do GUT)"),
    ("",                   "→ Aceitar elemento muro externo"),
    # Sintomas multilinha
    ("Trinca horizontal com abertura ~0.9mm na interface alvenaria/viga. Ausência de junta de dilatação e tela galvanizada.", "→ Sintomas linha 1"),
    ("",                   "→ Linha vazia finaliza sintomas"),
    # Descrição multilinha
    ("Trinca horizontal em muro externo com abertura ~0.9mm na interface entre a alvenaria e a viga. Configuração típica de retração e movimentação diferencial por ausência de junta de dilatação.", "→ Descrição linha 1"),
    ("",                   "→ Linha vazia finaliza descrição"),
    # Falha
    ("n",                  "→ Endógena agravada por falha de manutenção? Não"),
    # Nexo causal
    ("",                   "→ Aceitar nexo pré-preenchido do GUT"),
    # GUT vínculo
    ("",                   "→ Confirmar G/U/T importados"),
    # Normas (se encontradas)
    ("s",                  "→ Referenciar normas do banco"),
    # Grau de risco
    ("",                   "→ Aceitar grau de risco (mapeado do GUT)"),
    # Justificativa
    ("",                   "→ Aceitar justificativa pré-preenchida do GUT"),
    # Ação
    ("",                   "→ Aceitar ação recomendada do GUT"),
    # Normas adicionais
    ("",                   "→ Normas adicionais [pular]"),
    # Salvar
    ("2",                  "→ Salvar como FINALIZADA"),
    ("2",                  "→ Não exportar DOCX agora"),

    # ── Pós-análise ─────────────────────────────────────────────────────────
    ("1",                  "→ Exportar DOCX completo"),

    # ── Encerramento do laudo ───────────────────────────────────────────────
    ("0",                  "→ Sair sem alterar"),
])

call_num = [0]

def mock_input(prompt=""):
    call_num[0] += 1
    n = call_num[0]
    if RESPOSTAS:
        resp, comentario = RESPOSTAS.popleft()
        print(f"\n{'─'*70}")
        print(f"  [INPUT #{n}] PERGUNTA: {str(prompt).strip()[:80]}")
        print(f"  [INPUT #{n}] RESPOSTA: '{resp}'  {comentario}")
        print(f"{'─'*70}")
        return resp
    else:
        print(f"\n  [INPUT #{n}] ESGOTOU RESPOSTAS — encerrando teste")
        raise EOFError("Fim dos inputs de teste")

# ── Executar ────────────────────────────────────────────────────────────────
print("=" * 70)
print("  TESTE GUIADO — analise_img")
print("=" * 70)

with patch("builtins.input", mock_input):
    try:
        from analise_imagem import AnalisadorImagem
        from database import DatabaseManager
        from ai_engine import AIEngine

        db = DatabaseManager("banco_pericial.db")
        ai = AIEngine()
        analisador = AnalisadorImagem(db, ai)
        analisador.processar_lote()
    except (SystemExit, EOFError, KeyboardInterrupt):
        pass
    except Exception as e:
        import traceback
        print(f"\n[ERRO]: {e}")
        traceback.print_exc()

print("\n" + "=" * 70)
print("  FIM DO TESTE")
print(f"  Total de inputs consumidos: {call_num[0]}")
print(f"  Inputs não utilizados: {len(RESPOSTAS)}")
print("=" * 70)

"""
main.py — Interface Principal do Cérebro de Engenharia Diagnóstica
Versão 2.0 — Tela de boas-vindas, modo evidências, sessões de consulta,
             gestão de fontes, parâmetros normativos, comparador de fontes.
             O sistema funciona de forma completa SEM depender de IA.
"""
import os
import re
import time
import threading
import tkinter as tk
import tkinter.messagebox
import tkinter.filedialog
from tkinter import ttk
from pathlib import Path
import openpyxl
from database import DatabaseManager, TIPOS_FONTE, PESO_AUTORIDADE
from ai_engine import AIEngine, SemIAError
from processors import FileProcessor, DICIONARIO_SINONIMOS
try:
    from ai_health_monitor import inicializar_monitor, EmbeddingCache
    _HEALTH_MONITOR_OK = True
except ImportError:
    _HEALTH_MONITOR_OK = False
try:
    # Novo módulo unificado (substitui database_resilience_migration)
    from migrations import aplicar_todas as _aplicar_migracoes_resilience
    _MIGRATION_OK = True
except ImportError:
    try:
        from database_resilience_migration import aplicar_migracoes as _aplicar_migracoes_resilience
        _MIGRATION_OK = True
    except ImportError:
        _MIGRATION_OK = False

try:
    from orchestrator import OrquestradorReprocessamento, MonitorEntrada
    from quality_manager import QualityManager
    _REPROCESSAMENTO_OK = True
except ImportError:
    _REPROCESSAMENTO_OK = False
try:
    from analise_imagem import AnalisadorImagem
    _ANALISE_IMAGEM_OK = True
except ImportError:
    _ANALISE_IMAGEM_OK = False
try:
    from gut_adaptativo import GUTAdaptativo
    _GUT_ADAPTATIVO_OK = True
except ImportError:
    _GUT_ADAPTATIVO_OK = False
try:
    from analise_ibape import analise_ibape_cli
    _ANALISE_IBAPE_OK = True
except ImportError:
    _ANALISE_IBAPE_OK = False
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

PASTAS = {
    'doc':             {'in': 'doc_entrada',           'out': 'doc_processados'},
    'pdf':             {'in': 'pdf_entrada',           'out': 'pdf_processados'},
    'img_normas':      {'in': 'img_normas_entrada',    'out': 'img_normas_processadas'},
    'img_patologias':  {'in': 'img_patologias_entrada','out': 'img_patologias_processadas'},
}

_RE_CHARS_ILEGAIS = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')
_RE_N_PARAM       = re.compile(r'\bn=(\d+)\b', re.IGNORECASE)


def _extrair_n(texto: str, padrao: int = 8) -> int:
    """Extrai parâmetro n= do texto. Ex: 'guarda-corpo n=15' → 15."""
    m = _RE_N_PARAM.search(texto)
    return min(max(1, int(m.group(1))), 30) if m else padrao


def _remover_n(texto: str) -> str:
    """Remove o parâmetro n= do texto da consulta."""
    return _RE_N_PARAM.sub('', texto).strip()

STOPWORDS_CONSULTA = {
    "de","da","do","das","dos","em","no","na","um","uma","o","a","e","ou",
    "que","se","por","para","com","não","mais","como","mas","foi","são",
}


def _celula(valor, max_chars: int = 5000) -> str:
    if valor is None: return ''
    texto = _RE_CHARS_ILEGAIS.sub('', str(valor)).replace('\r', ' ')
    return (texto[:max_chars] + '...[truncado]') if len(texto) > max_chars else texto


# ══════════════════════════════════════════════════════════════════════════════
#  TELA DE BOAS-VINDAS
# ══════════════════════════════════════════════════════════════════════════════

def exibir_boas_vindas(stats: dict = None):
    print("\n" + "█" * 70)
    print("""
  🧠  CÉREBRO DE ENGENHARIA DIAGNÓSTICA  v2.0
  ─────────────────────────────────────────────────────────────────────
  Sistema de Consulta e Gestão de Base Técnico-Pericial

  PARA QUE SERVE:
  ✦ Indexar normas (NBR/ABNT), laudos periciais, livros e pareceres
  ✦ Consultar textos técnicos com citação rastreável de fonte
  ✦ Extrair parâmetros normativos (alturas, cargas, prazos) automaticamente
  ✦ Responder quesitos periciais com base em casos anteriores
  ✦ Funciona sem IA — toda consulta textual funciona offline

  COMO USAR:
  1. Coloque arquivos PDF/DOCX nas pastas de entrada (ex: pdf_entrada/)
  2. Digite [arquivos] para processar e indexar
  3. Digite [consultar] + sua dúvida (mínimo 3 palavras)
  4. Use [evidencias] para ver trechos brutos SEM interpretação de IA
  5. Use [parametros] para buscar valores normativos (alturas, cargas etc.)
  6. Use [fontes] para gerenciar os documentos do banco
  7. Use [gut] para ver e editar a Matriz GUT / Grau de Risco
  7. Adicione n=X para controlar quantos resultados ver (ex: n=15)

  EXEMPLOS DE CONSULTA:
  • evidencias guarda-corpo altura          → trechos brutos + fontes
  • evidencias infiltração fachada n=15     → 15 resultados sem IA
  • consultar estanqueidade laje n=10       → 10 trechos para IA analisar
  • parametros altura                       → valores numéricos extraídos
  • comparar guarda-corpo NBR14718          → norma vs laudo lado a lado
    """)
    if stats:
        print(f"  📊 BANCO ATUAL: {stats.get('fontes_ativas',0)} fonte(s) ativa(s) | "
              f"{stats.get('trechos',0)} trecho(s) | "
              f"{stats.get('parametros',0)} parâmetro(s) | "
              f"{stats.get('quesitos',0)} quesito(s)")
    print("█" * 70 + "\n")


def exibir_menu():
    print("\n" + "═" * 70)
    print("  COMANDOS DISPONÍVEIS")
    print("═" * 70)
    print("  [arquivos]              → Fase 1: extrai e indexa arquivos das pastas (llama3.2)")
    print("  [reimportar]            → Move PDFs/DOCXs processados de volta e reextrai tópicos")
    print('  [reprocessar]           → Fase 2: mostra status e refina banco (mistral:7b)')
    print('  [reprocessar status]    → Status detalhado: confiança, risco e pendências')
    print('  [consultar] <texto>     → Busca híbrida com IA (min. 3 palavras)')
    print('  [evidencias] <texto>    → Trechos brutos + fontes (sem IA)')
    print('  [analise_img]           → Análise Integrada de Imagens (GUT + IBAPE + Banco + IA)')
    print('  [parametros] <termo>    → Parâmetros normativos extraídos')
    print('  [comparar] <tema>       → Norma vs Laudo lado a lado')
    print('  [fontes]                → Gerenciar documentos do banco')
    print('  [gut]                   → Matriz GUT / Grau de Risco dos laudos')
    print('  [gut_adaptativo]        → Avaliação GUT Assistida v4.0 (Nexo Causal + SHS)')
    print('  [analise_ibape]         → Análise Técnica IBAPE (Anomalia / Falha / Grau de Risco)')
    print('  [exportar]              → Gera planilha Excel completa')
    print('  [populares]             → Termos mais consultados')
    print('  [gui]                   → Interface gráfica')
    print('  [status]                → Diagnóstico do sistema (IA, cache, GUT pendente)')
    print('  [sair]                  → Encerrar')
    print("═" * 70)


# ══════════════════════════════════════════════════════════════════════════════
#  CLASSE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class CerebroEngenharia:
    def __init__(self):
        self.db  = DatabaseManager()
        api_key  = os.getenv("GEMINI_API_KEY", "")
        self.ai  = AIEngine(api_key=api_key)
        self.processor = FileProcessor(self.db, self.ai, PASTAS)
        self.sessao_id = self.db.criar_sessao()
        self._ia_disponivel = bool(api_key)
        # Se Gemini não configurado, verificar Ollama como provedor alternativo
        if not self._ia_disponivel:
            try:
                from ollama_engine import OllamaEngine as _OllamaInit
                if _OllamaInit().disponivel:
                    self._ia_disponivel = True
                    print("  🔄  Gemini não configurado — Ollama local disponível como provedor de IA.")
            except Exception:
                pass
        self.setup_folders()

        # ── Migrações de resiliência (tabelas novas) ─────────────────────
        if _MIGRATION_OK:
            try:
                conn_mig = self.db.get_connection()
                _aplicar_migracoes_resilience(conn_mig)
                conn_mig.close()
            except Exception as _e_mig:
                print(f"  ⚠️  Migração de resiliência falhou (não crítico): {_e_mig}")

        # ── Health Monitor ────────────────────────────────────────────────
        if _HEALTH_MONITOR_OK:
            self._monitor = inicializar_monitor({"gemini_api_key": api_key})
            conn_cache = self.db.get_connection()
            self.ai.configurar_cache(conn_cache)
            self.ai.configurar_health_monitor(self._monitor)
            conn_cache.close()
        else:
            self._monitor = None

    def setup_folders(self):
        for tipo in PASTAS.values():
            os.makedirs(tipo['in'],  exist_ok=True)
            os.makedirs(tipo['out'], exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────
    #  VALIDAÇÃO
    # ─────────────────────────────────────────────────────────────────────────

    def _validar_minimo_palavras(self, duvida: str, minimo: int = 3) -> bool:
        palavras = [p for p in duvida.lower().split()
                    if len(p) >= 3 and p not in STOPWORDS_CONSULTA]
        return len(palavras) >= minimo

    def _normalizar_termos(self, duvida: str):
        """
        Normaliza, limpa e expande termos com sinônimos usando 3 camadas:
          L1 — DICIONARIO_SINONIMOS de processors.py
          L2 — dicionario_pericial_sinonimos do banco de dados (dinâmico)
          L3 — busca por prefixo/substring (fallback genérico)

        Remove pontuação dos tokens antes de expandir, garantindo que entradas
        como "inclinação, escoamento, caimento" não gerem tokens com vírgula
        acoplada que falham silenciosamente na busca LIKE.

        Retorna (lista_de_termos, modo_exato).
        """
        termos_iniciais = []   # populado no bloco else; vazio no modo exato
        if '"' in duvida:
            termos     = re.findall(r'"([^"]*)"', duvida)
            modo_exato = True
        else:
            # Tokenizar por qualquer separador não-alfanumérico (vírgulas, ponto e vírgula, etc.)
            tokens_raw = re.split(r"[,;\s]+", duvida.strip())
            termos_iniciais = [
                re.sub(r"[^\w\sáéíóúàâêôãõüçÁÉÍÓÚÀÂÊÔÃÕÜÇ]", "", t).strip().lower()
                for t in tokens_raw
            ]
            # Carregar stopwords de ruído do config_pericial.yaml (inglês + verbos genéricos)
            # Não filtra "norma", "laudo" etc. — termos técnicos pesquisáveis
            try:
                from database import _garantir_yaml_carregado, _STOPWORDS_YAML_CACHE
                _garantir_yaml_carregado()
                _sw_ruido = _STOPWORDS_YAML_CACHE
            except Exception:
                _sw_ruido = set()
            termos_iniciais = [t for t in termos_iniciais if len(t) > 2
                               and t not in STOPWORDS_CONSULTA
                               and t not in _sw_ruido]

            expandidos = set(termos_iniciais)

            # L1 — DICIONARIO_SINONIMOS (processors.py)
            for termo in list(expandidos):
                for conceito, sins in DICIONARIO_SINONIMOS.items():
                    if termo == conceito or termo in sins:
                        expandidos.add(conceito)
                        expandidos.update(sins)

            # L2 — dicionario_pericial_sinonimos do banco
            sins_banco = self._carregar_sinonimos_banco()
            for termo in list(expandidos):
                for conceito, dados in sins_banco.items():
                    sinonimos = dados.get("sinonimos", [])
                    if termo == conceito or termo in sinonimos:
                        expandidos.add(conceito)
                        expandidos.update(sinonimos)

            # L3 — prefixo/substring (termos sem expansão exata)
            import json as _json
            try:
                from consulta_pericial import _EXPANSAO_PERICIAL
                for termo in list(termos_iniciais):
                    if termo in expandidos and len(expandidos) > len(termos_iniciais):
                        continue  # já foi expandido em L1 ou L2
                    if len(termo) < 4:
                        continue
                    min_len = max(4, len(termo) - 2)
                    for conceito, dados in _EXPANSAO_PERICIAL.items():
                        candidatos = [conceito] + dados.get("termos", [])
                        for c in candidatos:
                            c = c.lower()
                            if c.startswith(termo[:min_len]) or termo.startswith(c[:min_len]):
                                expandidos.update(dados.get("termos", []))
                                expandidos.add(conceito)
                                break
                            if len(termo) >= 6 and (termo in c or c in termo):
                                expandidos.update(dados.get("termos", []))
                                expandidos.add(conceito)
                                break
            except ImportError:
                pass

            termos     = [t for t in expandidos if t]
            modo_exato = False
        # termos_iniciais são os âncoras: os tokens originais do usuário
        # antes de qualquer expansão de sinônimos.
        termos_anchor = termos_iniciais if not modo_exato else []
        return termos, modo_exato, termos_anchor

    def _carregar_sinonimos_banco(self) -> dict:
        """
        Carrega o dicionário pericial do banco (tabela dicionario_pericial_sinonimos).
        Retorna dict {conceito: {sinonimos: [...]}}.
        Falha silenciosamente — nunca bloqueia a consulta.
        """
        import json as _json
        resultado: dict = {}
        try:
            conn = self.db.get_connection()
            rows = conn.execute(
                "SELECT conceito, sinonimos FROM dicionario_pericial_sinonimos"
            ).fetchall()
            conn.close()
            for conceito, sins_json in rows:
                try:
                    sins = _json.loads(sins_json) if isinstance(sins_json, str) else (sins_json or [])
                except Exception:
                    sins = []
                resultado[conceito.lower()] = {
                    "sinonimos": [s.lower() for s in sins]
                }
        except Exception:
            pass
        return resultado

    def _gerar_aviso_desatualizacao(self, data_ingestao: str) -> str:
        """Avisa se uma norma foi indexada há mais de 2 anos."""
        try:
            from datetime import datetime
            data = datetime.strptime(data_ingestao[:10], '%Y-%m-%d')
            anos = (datetime.now() - data).days / 365
            if anos > 2:
                return (f"\n  ⚠️  ATENÇÃO: esta fonte foi indexada há {anos:.0f} ano(s) "
                        f"({data.strftime('%m/%Y')}). Verifique se há versão mais recente.")
        except Exception:
            pass
        return ""

    # ─────────────────────────────────────────────────────────────────────────
    #  PREVIEWS (confirmação antes do conteúdo completo)
    # ─────────────────────────────────────────────────────────────────────────

    def _gerar_previews(self, resultados: list) -> list:
        previews = []
        for i, d in enumerate(resultados[:10], 1):
            fonte  = f"{d.get('nome_arquivo','?')} | {d.get('tipo_fonte','?')}"
            tit    = d.get('titulo_topico') or d.get('titulo','')
            texto  = d.get('texto_reescrito') or d.get('texto_original', '')
            palavras = str(texto).split()
            trecho = " ".join(palavras[:10]) + ("..." if len(palavras) > 10 else "")
            hier   = d.get('hierarquia', '')
            previews.append({'num': i, 'fonte': fonte, 'titulo': tit,
                             'hierarquia': hier, 'trecho': trecho})
        return previews

    def _exibir_preview_cli(self, previews: list, duvida: str):
        """
        Retorna:
          'todos'       → [S] ver todos os resultados
          'integral'    → [I] ver todos sem truncar (texto integral)
          [1,3,…]       → lista de índices escolhidos
          None          → [N] cancelar
        """
        print("\n" + "═" * 70)
        print(f"  🔍 PRÉVIA — \"{duvida}\"")
        print("═" * 70)
        for p in previews:
            hier = f"\n       ↳ {p['hierarquia']}" if p['hierarquia'] else ""
            print(f"\n  [{p['num']}] 📄 {p['fonte']}")
            if p['titulo']: print(f"       Seção: {p['titulo']}{hier}")
            print(f"       ✂  ...{p['trecho']}...")
        print("\n" + "─" * 70)
        print("  [S] Todos  [I] Texto integral  [N] Cancelar  [1,3…] Itens específicos")
        resp = input("  > ").strip()

        if resp.upper() in ('S', ''):    return 'todos'
        if resp.upper() == 'I':          return 'integral'
        if resp.upper() == 'N':          return None
        nums_validos = {p['num'] for p in previews}
        try:
            selecionados = [int(x.strip()) for x in resp.split(',')
                            if x.strip().isdigit() and int(x.strip()) in nums_validos]
            if selecionados: return selecionados
        except ValueError:
            pass
        print("  ⚠️  Entrada inválida — cancelando.")
        return None

    def _exibir_preview_gui(self, *_):
        """GUI retorna sempre 'todos' — não chama messagebox de thread de fundo."""
        return 'todos'

    # ─────────────────────────────────────────────────────────────────────────
    #  MODO EVIDÊNCIAS (sem IA — texto bruto com citação completa)
    # ─────────────────────────────────────────────────────────────────────────

    def consultar_evidencias(self, duvida: str, tipo_fonte: str = None,
                             n: int = 8, modo_gui: bool = False) -> str:
        """
        Retorna APENAS os trechos brutos do banco, sem IA.
        Ideal para copiar diretamente para laudos com rastreabilidade total.
        n: número de resultados a exibir (padrão 8, máximo 30).
        modo_gui: quando True, retorna string formatada sem loop interativo.
        """
        if not self._validar_minimo_palavras(duvida):
            return self._mensagem_minimo_palavras()

        termos, _, termos_anchor = self._normalizar_termos(duvida)
        resultados_todos = self.db.busca_textual(termos, tipo_fonte=tipo_fonte, termos_anchor=termos_anchor)

        if not resultados_todos:
            return "  📭 Nenhum trecho encontrado para os termos informados."

        self.db.registrar_consulta(duvida)
        sep = "─" * 70
        n   = min(max(1, n), 30)

        # ── MODO GUI: retorna texto formatado sem bloquear no input() ─────────
        if modo_gui:
            linhas = [
                f"📋 EVIDÊNCIAS — \"{duvida}\" (sem IA)",
                f"  {len(resultados_todos)} trecho(s) encontrado(s) | exibindo {min(n, len(resultados_todos))}",
                "═" * 70,
            ]
            for i, d in enumerate(resultados_todos[:n], 1):
                nome  = d.get('nome_arquivo', '?')
                tipo_ = TIPOS_FONTE.get(d.get('tipo_fonte', ''), d.get('tipo_fonte', '?'))
                ano   = d.get('ano_edicao', '')
                num   = d.get('numero_topico', '')
                pag   = d.get('pagina', 0)
                tit   = d.get('titulo_topico', '')
                hier  = d.get('hierarquia', '')
                texto = d.get('texto_original', d.get('texto_reescrito', ''))
                obs   = d.get('comentario_usuario', '') or ''
                aviso = self._gerar_aviso_desatualizacao(d.get('data_ingestao', ''))
                cab = f"[REF {i}] {nome}"
                if ano: cab += f" ({ano})"
                cab += f" | {tipo_}"
                if num: cab += f" | Item {num}"
                if pag: cab += f" | Pág. {pag}"
                if d.get('favorito'): cab += "  ★"
                linhas.append(f"\n{sep}")
                linhas.append(cab)
                if hier:  linhas.append(f"  Hierarquia: {hier}")
                if tit:   linhas.append(f"  Seção: {tit}")
                if obs:   linhas.append(f"  Obs.: {obs}")
                if aviso: linhas.append(aviso)
                linhas.append(sep)
                linhas.append(texto[:1500] + ("\n  [...trecho truncado]" if len(texto) > 1500 else ""))
            return "\n".join(linhas)

        def _cabec_item(i, d, favorito_atual=None):
            """Monta cabeçalho de um item, incluindo badges de favorito e comentário."""
            nome  = d.get('nome_arquivo', '?')
            tipo  = TIPOS_FONTE.get(d.get('tipo_fonte', ''), d.get('tipo_fonte', '?'))
            ano   = d.get('ano_edicao', '')
            num   = d.get('numero_topico', '')
            pag   = d.get('pagina', 0)
            fav   = favorito_atual if favorito_atual is not None else d.get('favorito', 0)
            c = f"[REF {i}] {nome}"
            if ano: c += f" ({ano})"
            c += f" | {tipo}"
            if num: c += f" | Item {num}"
            if pag: c += f" | Pág. {pag}"
            if fav: c += "  ★ FAVORITO"
            return c

        def _exibir_resultados(lista, modo_integral=False):
            """Imprime os trechos do banco na tela."""
            print(f"\n{'═'*70}")
            print(f"  📋 EVIDÊNCIAS — \"{duvida}\" (Modo sem IA)")
            print(f"  {len(lista)} trecho(s) | exibindo {min(n, len(lista))}\n{'═'*70}")
            for i, d in enumerate(lista[:n], 1):
                tit   = d.get('titulo_topico', '')
                hier  = d.get('hierarquia', '')
                texto = d.get('texto_original', d.get('texto_reescrito', ''))
                obs   = d.get('comentario_usuario', '') or ''
                aviso = self._gerar_aviso_desatualizacao(d.get('data_ingestao', ''))
                print(f"\n{sep}\n{_cabec_item(i, d)}")
                if hier:  print(f"  Hierarquia: {hier}")
                if tit:   print(f"  Seção: {tit}")
                if obs:   print(f"  Obs. perito: {obs}")
                if aviso: print(aviso)
                print(sep)
                limite = len(texto) if modo_integral else 1500
                print(texto[:limite] + (
                    "\n  [...trecho truncado — use [I]ntegral]"
                    if not modo_integral and len(texto) > 1500 else ""))

        previews = self._gerar_previews(resultados_todos)

        while True:  # loop de navegação — [V] retorna aqui
            selecao = self._exibir_preview_cli(previews, duvida) if previews else 'todos'
            if selecao is None:
                return "  🔎 Consulta cancelada."

            modo_integral = (selecao == 'integral')
            if isinstance(selecao, list):
                resultados = [r for i, r in enumerate(resultados_todos, 1) if i in selecao]
            else:
                resultados = resultados_todos

            _exibir_resultados(resultados, modo_integral)

            # ── Prompt de ações ──────────────────────────────────────────────
            print(f"\n{sep}")
            print("  Ações: [I] Integral  [V] Voltar aos resultados  [ENTER] Menu")
            print("         Por item: F1=favorito  C1=comentário  X1=excluir")

            while True:
                resp = input("  > ").strip()
                ru = resp.upper()

                if ru == 'I':
                    _exibir_resultados(resultados, modo_integral=True)
                    print(f"\n{sep}")
                    print("  Ações: [V] Voltar aos resultados  [ENTER] Menu")
                    print("         Por item: F1=favorito  C1=comentário  X1=excluir")
                    continue

                if ru == 'V':
                    break  # volta ao loop externo → exibe preview novamente

                # ── F<n> — toggle favorito ────────────────────────────────
                import re as _re
                m_fav = _re.fullmatch(r'[Ff](\d+)', resp)
                if m_fav:
                    idx = int(m_fav.group(1)) - 1
                    if 0 <= idx < len(resultados):
                        tid = resultados[idx].get('id')
                        if tid:
                            atual = resultados[idx].get('favorito', 0)
                            novo  = 0 if atual else 1
                            res   = self.db.avaliar_topico(tid, favorito=bool(novo))
                            resultados[idx]['favorito'] = res['favorito']
                            estado = "★ marcado como FAVORITO" if novo else "desmarcado de favorito"
                            print(f"  REF {idx+1}: {estado}.")
                            print(f"  (aparecerá primeiro nas próximas buscas e na aba 'Textos Manuais' do Excel)")
                    else:
                        print(f"  REF {m_fav.group(1)} não existe.")
                    continue

                # ── C<n> — comentário ─────────────────────────────────────
                m_com = _re.fullmatch(r'[Cc](\d+)', resp)
                if m_com:
                    idx = int(m_com.group(1)) - 1
                    if 0 <= idx < len(resultados):
                        tid = resultados[idx].get('id')
                        if tid:
                            obs_atual = resultados[idx].get('comentario_usuario', '') or ''
                            if obs_atual:
                                print(f"  Comentário atual: {obs_atual}")
                            nova_obs = input("  Nova observação (ENTER mantém): ").strip()
                            if nova_obs:
                                res = self.db.avaliar_topico(tid, comentario=nova_obs)
                                resultados[idx]['comentario_usuario'] = res['comentario_usuario']
                                print(f"  Observação salva.")
                    else:
                        print(f"  REF {m_com.group(1)} não existe.")
                    continue

                # ── X<n> — excluir ────────────────────────────────────────
                m_del = _re.fullmatch(r'[Xx](\d+)', resp)
                if m_del:
                    idx = int(m_del.group(1)) - 1
                    if 0 <= idx < len(resultados):
                        tid = resultados[idx].get('id')
                        if tid:
                            conf = input(f"  ⚠️  Confirma exclusão do REF {idx+1}? [S/N]: ").strip().upper()
                            if conf == 'S':
                                self.db.deletar_topico(tid)
                                resultados.pop(idx)
                                print(f"  ✅ REF {idx+1} removido.")
                    else:
                        print(f"  REF {m_del.group(1)} não existe.")
                    continue

                # ENTER ou qualquer outra tecla → sai
                return ""

    # ─────────────────────────────────────────────────────────────────────────
    #  PARÂMETROS NORMATIVOS
    # ─────────────────────────────────────────────────────────────────────────

    def consultar_parametros(self, termo: str, n: int = 50) -> str:
        """
        Exibe parâmetros normativos extraídos automaticamente (alturas, cargas etc.).
        Funciona completamente SEM IA.
        n: máximo de parâmetros a exibir por documento (padrão 50).
        """
        params = self.db.buscar_parametros(termo)
        if not params:
            return f"  📭 Nenhum parâmetro encontrado para '{termo}'."

        sep   = "─" * 70
        saida = [f"\n{'═'*70}",
                 f"  📐 PARÂMETROS NORMATIVOS — \"{termo}\"",
                 f"  {len(params)} resultado(s) encontrado(s)\n{'═'*70}"]

        # Agrupa por documento
        por_doc: dict = {}
        for p in params:
            chave = f"{p['nome_arquivo']} ({p.get('ano_edicao','') or 'ano ?'})"
            por_doc.setdefault(chave, []).append(p)

        for doc, itens in por_doc.items():
            tipo = TIPOS_FONTE.get(itens[0].get('tipo_fonte', ''), '?')
            saida.append(f"\n  📄 {doc} | {tipo}")
            saida.append(sep)
            for p in itens:
                item  = f" Item {p['item_ref']}" if p['item_ref'] else ''
                pag   = f" Pág.{p['pagina']}" if p['pagina'] else ''
                uni   = p['unidade'] or ''
                saida.append(
                    f"  • {p['parametro'].replace('_',' ').title()}: "
                    f"{p['valor']} {uni}{item}{pag}"
                )
                if p.get('contexto'):
                    saida.append(f"    ↳ Contexto: ...{p['contexto'][:80]}...")

        return "\n".join(saida)

    # ─────────────────────────────────────────────────────────────────────────
    #  COMPARADOR DE FONTES (norma vs laudo)
    # ─────────────────────────────────────────────────────────────────────────

    def comparar_fontes(self, tema: str) -> str:
        """
        Busca o tema em normas E laudos separadamente,
        exibe lado a lado para identificar concordâncias e divergências.
        Funciona SEM IA.
        """
        termos, _, termos_anchor = self._normalizar_termos(tema)
        normas  = self.db.busca_textual(termos, tipo_fonte='norma_abnt',      termos_anchor=termos_anchor)[:3]
        normas += self.db.busca_textual(termos, tipo_fonte='norma_iso',       termos_anchor=termos_anchor)[:2]
        laudos  = self.db.busca_textual(termos, tipo_fonte='laudo_judicial',  termos_anchor=termos_anchor)[:3]
        laudos += self.db.busca_textual(termos, tipo_fonte='parecer_tecnico', termos_anchor=termos_anchor)[:2]

        if not normas and not laudos:
            return f"  📭 Nenhuma fonte encontrada para '{tema}'."

        sep   = "─" * 70
        saida = [f"\n{'═'*70}", f"  ⚖️  COMPARADOR DE FONTES — \"{tema}\"", f"{'═'*70}"]

        saida.append(f"\n  {'─'*30}  NORMAS TÉCNICAS  {'─'*30}")
        if normas:
            for i, d in enumerate(normas, 1):
                tit  = d.get('titulo_topico', d.get('numero_topico', ''))
                hier = d.get('hierarquia', '')
                txt  = d.get('texto_original', '')[:600]
                saida.append(f"\n  [N{i}] {d.get('nome_arquivo','')} | Item {d.get('numero_topico','')}")
                if hier: saida.append(f"       ↳ {hier}")
                saida.append(f"  {sep}")
                saida.append(f"  {txt}{'...' if len(d.get('texto_original',''))>600 else ''}")
        else:
            saida.append("  (Nenhuma norma encontrada para este tema)")

        saida.append(f"\n  {'─'*29}  LAUDOS / PARECERES  {'─'*29}")
        if laudos:
            for i, d in enumerate(laudos, 1):
                txt = d.get('texto_original', '')[:600]
                saida.append(f"\n  [L{i}] {d.get('nome_arquivo','')} | {d.get('tipo_fonte','')}")
                saida.append(f"  {sep}")
                saida.append(f"  {txt}{'...' if len(d.get('texto_original',''))>600 else ''}")
        else:
            saida.append("  (Nenhum laudo/parecer encontrado para este tema)")

        saida.append(f"\n{'═'*70}")
        saida.append("  💡 Use [evidencias] para ver os trechos completos com referência.")
        return "\n".join(saida)

    # ─────────────────────────────────────────────────────────────────────────
    #  CONSULTA COM IA (com contexto de sessão acumulado)
    # ─────────────────────────────────────────────────────────────────────────

    def consultar(self, duvida: str, modo_gui: bool = False,
                  tipo_fonte: str = None, n: int = 6) -> str:
        """
        Consulta híbrida com IA. n controla quantos trechos são passados para a IA (padrão 6).
        Quando a IA não está configurada, delega imediatamente para consultar_evidencias
        para evitar que o preview seja exibido duas vezes.
        """
        if not self._validar_minimo_palavras(duvida):
            return self._mensagem_minimo_palavras()

        self.db.registrar_consulta(duvida)

        # ── Sem IA: delegar antes de qualquer preview ─────────────────────
        # Evita o preview duplo que ocorria quando a verificação ficava após
        # a prévia: o usuário selecionava o item, consultar_evidencias era
        # chamada do zero e exibia um segundo preview idêntico.
        if not self._ia_disponivel:
            return self.consultar_evidencias(duvida, tipo_fonte, n=n)

        termos, _, termos_anchor = self._normalizar_termos(duvida)

        # ── Expansão de query via Ollama (Possibilidade C) ────────────────
        # Enriquece os termos com reformulação semântica antes da busca.
        # Additive: termos Ollama são fundidos com a expansão por dicionário.
        # Fallback silencioso se Ollama indisponível ou lento demais.
        try:
            from ollama_engine import OllamaEngine as _OllamaQE
            _ollama_qe = _OllamaQE()
            if _ollama_qe.disponivel:
                _prompt_qe = (
                    f"Consulta técnica pericial: \"{duvida}\"\n"
                    "Liste termos técnicos de busca: sinônimos, variações, NBRs relacionadas.\n"
                    "Retorne APENAS uma lista separada por vírgulas. Máximo 15 termos."
                )
                _resp_qe = _ollama_qe.gerar_rapido(_prompt_qe, max_tokens=120)
                if _resp_qe:
                    _termos_ollama = [
                        t.strip().lower() for t in _resp_qe.split(',')
                        if 2 < len(t.strip()) <= 60
                    ]
                    termos = list(dict.fromkeys(termos + _termos_ollama))
        except Exception:
            pass  # Ollama indisponível — continua com expansão por dicionário

        # Embedding da query
        embedding_query = []
        try:
            embedding_query = self.ai.gerar_embedding(duvida)
        except Exception:
            pass

        # Busca híbrida
        resultados = self.db.busca_hibrida(termos, embedding_query, tipo_fonte, termos_anchor=termos_anchor)
        quesitos   = self.db.busca_quesitos(termos)

        if not resultados and not quesitos:
            return "  📭 Nenhuma informação técnica encontrada com os termos informados."

        # Prévia
        todos = resultados + [
            {'titulo_topico': q.get('pergunta', '')[:60],
             'nome_arquivo': q.get('nome_arquivo', ''),
             'tipo_fonte': q.get('tipo_fonte', ''),
             'hierarquia': '',
             'texto_reescrito': q.get('resposta_perito', ''),
             'texto_original': q.get('pergunta', ''),
             'data_ingestao': ''}
            for q in quesitos[:3]
        ]
        previews = self._gerar_previews(todos)
        selecao_c = 'todos'
        if previews:
            selecao_c = (self._exibir_preview_gui(previews, duvida) if modo_gui
                         else self._exibir_preview_cli(previews, duvida))
            if selecao_c is None:
                return "  🔎 Consulta cancelada. Refine os termos."
            if isinstance(selecao_c, list):
                todos_filtrados = [d for i, d in enumerate(todos, 1) if i in selecao_c]
                resultados = [d for d in todos_filtrados if 'score_textual' in d or 'score_hibrido' in d]
                quesitos   = [d for d in todos_filtrados if 'pergunta' in d]
            if not resultados and not quesitos:
                return "  📭 Nenhum item selecionado."

        # Prepara contexto acumulado da sessão
        historico = self.db.buscar_historico_sessao(self.sessao_id, n=3)
        contexto_sessao = ""
        if historico:
            trocas = [f"[{h['papel'].upper()}]: {h['conteudo'][:300]}" for h in historico]
            contexto_sessao = "\n".join(trocas)

        # Formata chunks para a IA
        chunks_formatados = []
        for d in resultados[:6]:
            aviso = self._gerar_aviso_desatualizacao(d.get('data_ingestao', ''))
            texto_chunk = d.get('texto_reescrito') or d.get('texto_original', '')
            # Inclui contexto do tópico pai quando disponível
            pai = d.get('pai')
            if pai:
                pai_titulo = pai.get('titulo_topico', '')
                pai_texto = (pai.get('texto_reescrito') or pai.get('texto_original', ''))[:400]
                if pai_texto:
                    texto_chunk = (
                        f"[Contexto da seção '{pai_titulo}']: {pai_texto}...\n\n"
                        f"{texto_chunk}"
                    )
            chunks_formatados.append({
                'titulo': f"{d.get('nome_arquivo','')} | {d.get('titulo_topico','')}",
                'texto':  texto_chunk,
                'numero': d.get('numero_topico', ''),
                'metadata': {
                    'page':       d.get('pagina', 0),
                    'tipo_fonte': d.get('tipo_fonte', ''),
                    'hierarquia': d.get('hierarquia', ''),
                    'aviso':      aviso,
                    'pai_titulo': pai.get('titulo_topico', '') if pai else '',
                },
                'similarity': d.get('score_hibrido', 0),
            })
        # Armazena para expand interativo no loop CLI
        self._ultimos_chunks = chunks_formatados

        # Adiciona quesitos similares ao contexto
        for q in quesitos[:3]:
            chunks_formatados.append({
                'titulo': f"[QUESITO SIMILAR] {q.get('nome_arquivo','')}",
                'texto':  f"P: {q.get('pergunta','')}\nR: {q.get('resposta_perito','')}",
                'numero': '-',
                'metadata': {'page': 0, 'tipo_fonte': 'laudo_judicial', 'hierarquia': ''},
                'similarity': 0.5,
            })

        try:
            resposta = self.ai.consultar_base(
                duvida, chunks_formatados, contexto_sessao=contexto_sessao
            )
            # Aviso de normas desatualizadas
            avisos = [d.get('aviso', '') for d in [c['metadata'] for c in chunks_formatados] if d.get('aviso')]
            if avisos:
                resposta += "\n\n" + "\n".join(set(avisos))
            # Bloco resumido de fontes ao final da resposta
            resposta += self._bloco_fontes_resumido(chunks_formatados)
            # Registra trechos efetivamente usados pela IA (Opção D)
            for d in resultados[:6]:
                tid = d.get('id')
                if tid:
                    try:
                        self.db.registrar_uso_trecho(tid, self.sessao_id, duvida)
                    except Exception:
                        pass
            # Salva na sessão
            self.db.salvar_historico(self.sessao_id, 'usuario', duvida)
            self.db.salvar_historico(self.sessao_id, 'sistema', resposta[:2000])
            return resposta
        except (SemIAError, Exception):
            # IA falhou após a prévia: renderizar os resultados já selecionados
            # diretamente, sem nova busca e sem segundo preview.
            return self._renderizar_evidencias(duvida, resultados, n=n)

    def _renderizar_evidencias(self, duvida: str, resultados: list, n: int = 8) -> str:
        """
        Renderiza evidências a partir de resultados já buscados e selecionados,
        sem executar nova busca nem exibir preview novamente.
        Usado como fallback quando a IA falha após a prévia já ter sido exibida.
        """
        if not resultados:
            return "  📭 Nenhum trecho disponível para exibição."

        sep   = "─" * 70
        saida = [
            f"\n{'═'*70}",
            f"  📋 EVIDÊNCIAS — \"{duvida}\" (Modo sem IA)",
            f"  {len(resultados)} trecho(s) | exibindo {min(n, len(resultados))}\n{'═'*70}",
        ]
        for i, d in enumerate(resultados[:n], 1):
            nome  = d.get('nome_arquivo', '?')
            tipo  = TIPOS_FONTE.get(d.get('tipo_fonte', ''), d.get('tipo_fonte', '?'))
            ano   = d.get('ano_edicao', '')
            tit   = d.get('titulo_topico', '')
            num   = d.get('numero_topico', '')
            pag   = d.get('pagina', 0)
            hier  = d.get('hierarquia', '')
            texto = d.get('texto_original', d.get('texto_reescrito', ''))
            aviso = self._gerar_aviso_desatualizacao(d.get('data_ingestao', ''))

            cabec = f"[REF {i}] {nome}"
            if ano:  cabec += f" ({ano})"
            cabec += f" | {tipo}"
            if num:  cabec += f" | Item {num}"
            if pag:  cabec += f" | Pág. {pag}"

            saida.append(f"\n{sep}\n{cabec}")
            if hier:  saida.append(f"  Hierarquia: {hier}")
            if tit:   saida.append(f"  Seção: {tit}")
            if aviso: saida.append(aviso)
            saida.append(sep)
            saida.append(texto[:1500] + ("\n  [...trecho truncado]" if len(texto) > 1500 else ""))

        return "\n".join(saida)

    def _bloco_fontes_resumido(self, chunks: list) -> str:
        """
        Retorna bloco compacto com prévia de cada fonte utilizada na resposta.
        Exibido ao final da resposta da IA — 200 chars por trecho.
        """
        if not chunks:
            return ""
        sep = "─" * 70
        linhas = [f"\n\n{sep}", f"  📚 FONTES DESTA CONSULTA ({len(chunks)} trecho(s))", sep]
        for i, c in enumerate(chunks, 1):
            titulo = c.get('titulo', '?')
            meta   = c.get('metadata', {})
            pag    = meta.get('page', '')
            tipo   = TIPOS_FONTE.get(meta.get('tipo_fonte', ''), meta.get('tipo_fonte', ''))
            texto  = c.get('texto', '')
            trecho = " ".join(texto.split()[:30])
            if len(texto.split()) > 30:
                trecho += "..."
            cabec = f"  [REF_{i}] {titulo}"
            if pag:  cabec += f" | Pág. {pag}"
            if tipo: cabec += f" | {tipo}"
            linhas.append(cabec)
            linhas.append(f"           → {trecho}")
        linhas.append(sep)
        linhas.append("  💡 [ver fontes] para texto completo  |  [evidencias] <consulta> para nova busca")
        return "\n".join(linhas)

    def _renderizar_ultimas_fontes(self) -> str:
        """
        Exibe texto completo das fontes da última consulta com IA.
        Acionado pelo comando [ver fontes] no loop CLI.
        """
        chunks = getattr(self, '_ultimos_chunks', [])
        if not chunks:
            return "  📭 Nenhuma fonte disponível. Faça uma consulta primeiro."
        sep = "─" * 70
        linhas = [f"\n{'═'*70}", f"  📚 FONTES COMPLETAS — {len(chunks)} trecho(s)", f"{'═'*70}"]
        for i, c in enumerate(chunks, 1):
            titulo = c.get('titulo', '?')
            meta   = c.get('metadata', {})
            pag    = meta.get('page', '')
            tipo   = TIPOS_FONTE.get(meta.get('tipo_fonte', ''), meta.get('tipo_fonte', ''))
            hier   = meta.get('hierarquia', '')
            texto  = c.get('texto', '')
            score  = c.get('similarity', 0)
            cabec  = f"  [REF_{i}] {titulo}"
            if pag:  cabec += f" | Pág. {pag}"
            if tipo: cabec += f" | {tipo}"
            if score: cabec += f" | Score: {score:.2f}"
            linhas.append(f"\n{sep}\n{cabec}")
            if hier: linhas.append(f"  Hierarquia: {hier}")
            linhas.append(sep)
            linhas.append(texto)
        linhas.append(f"\n{'═'*70}")
        return "\n".join(linhas)

    # ─────────────────────────────────────────────────────────────────────────
    #  GESTÃO DE FONTES
    # ─────────────────────────────────────────────────────────────────────────

    def gerenciar_fontes(self):
        while True:
            fontes = self.db.listar_fontes(status=None)
            print("\n" + "═" * 70)
            print(f"  📚 GESTÃO DE FONTES ({len(fontes)} documento(s) no banco)")
            print("═" * 70)
            if not fontes:
                print("  (banco vazio)")
            else:
                print(f"  {'ID':<5} {'Tipo':<20} {'Arquivo':<30} {'Ano':<6} {'Status':<10} {'Trechos'}")
                print("  " + "─" * 68)
                for f in fontes:
                    tipo  = TIPOS_FONTE.get(f['tipo_fonte'], f['tipo_fonte'])[:18]
                    nome  = f['nome_arquivo'][:28]
                    ano   = f.get('ano_edicao', '')[:5] or '-'
                    stat  = f.get('status', 'ativo')
                    n     = f.get('n_trechos', 0)
                    print(f"  {f['id']:<5} {tipo:<20} {nome:<30} {ano:<6} {stat:<10} {n}")

            print("\n  [1] Alterar tipo de uma fonte")
            print("  [2] Marcar como revogada")
            print("  [3] Reativar fonte")
            print("  [4] Deletar fonte (remove trechos e parâmetros)")
            print("  [5] Ver parâmetros de uma norma")
            print("  [0] Voltar")
            op = input("\n  Escolha: ").strip()

            if op == '0':
                break

            elif op in ('1', '2', '3', '4', '5'):
                try:
                    fid = int(input("  ID da fonte: ").strip())
                except ValueError:
                    print("  ❌ ID inválido."); continue

                if op == '1':
                    print("  Tipos disponíveis:")
                    for k, v in TIPOS_FONTE.items():
                        print(f"    {k:<25} → {v}")
                    novo_tipo = input("  Novo tipo: ").strip()
                    if novo_tipo in TIPOS_FONTE:
                        self.db.atualizar_fonte(fid, tipo_fonte=novo_tipo)
                        print(f"  ✅ Tipo atualizado para '{novo_tipo}'.")
                    else:
                        print("  ❌ Tipo inválido.")

                elif op == '2':
                    self.db.atualizar_fonte(fid, status='revogado')
                    print("  ✅ Fonte marcada como revogada (não aparecerá em buscas).")

                elif op == '3':
                    self.db.atualizar_fonte(fid, status='ativo')
                    print("  ✅ Fonte reativada.")

                elif op == '4':
                    conf = input("  ⚠️  Confirma exclusão permanente? [S/N]: ").strip().upper()
                    if conf == 'S':
                        self.db.deletar_fonte(fid)
                        print("  ✅ Fonte e todos os seus dados removidos.")

                elif op == '5':
                    params = self.db.listar_parametros_norma(fid)
                    if not params:
                        print("  📭 Nenhum parâmetro extraído desta fonte.")
                    else:
                        print(f"\n  📐 {len(params)} parâmetro(s) extraído(s):")
                        for p in params:
                            print(f"   • {p['parametro'].replace('_',' ').title()}: "
                                  f"{p['valor']} {p['unidade']}  "
                                  f"[Item {p['item_ref']}] | {p['contexto'][:60]}...")
            else:
                print("  Opção inválida.")

    # ─────────────────────────────────────────────────────────────────────────
    #  MATRIZ GUT / GRAU DE RISCO
    # ─────────────────────────────────────────────────────────────────────────

    def gerenciar_gut(self):
        """
        Exibe a Matriz GUT de todas as anomalias classificadas nos laudos.
        Permite ao perito ajustar risco e GUT manualmente (G:X, U:X, T:X).
        """
        _COR_RISCO = {'Crítico':'🔴','Grave':'🟠','Médio':'🟡','Mínimo':'🟢','-':'⚪'}
        while True:
            anomalias = self.db.listar_anomalias_risco()
            sep = "─" * 72
            print("\n" + "═" * 72)
            print(f"  ⚠️  MATRIZ GUT — {len(anomalias)} anomalia(s) classificada(s)")
            print("═" * 72)
            if not anomalias:
                print("  (Nenhuma anomalia com grau de risco encontrada.)")
                print("  Reprocesse os laudos para extrair grau de risco automaticamente.")
            else:
                print(f"  {'ID':<5} {'Risco':<12} {'GUT (auto)':<18} {'GUT (perito)':<18} {'Título'}")
                print("  " + sep)
                for a in anomalias:
                    icone = _COR_RISCO.get(a['grau_risco'], '⚪')
                    risco = f"{icone} {a['grau_risco']}"
                    gut_a = a['matriz_gut']   or '-'
                    gut_p = a['avaliacao_gut_usuario'] or '-'
                    nome  = a['titulo_topico'][:35]
                    print(f"  {a['id']:<5} {risco:<12} {gut_a:<18} {gut_p:<18} {nome}")
            print(f"\n  [1] Ajustar GUT e risco de uma anomalia")
            print(f"  [R] Reavaliar com GUT Adaptativo v4.0")
            print(f"  [2] Exportar matriz para Excel")
            print(f"  [0] Voltar")
            op = input("\n  Escolha: ").strip()
            if op == '0': break
            elif op == '1':
                try:
                    tid = int(input("  ID da anomalia: ").strip())
                except ValueError:
                    print("  ❌ ID inválido."); continue
                risco_p = input("  Grau de risco (Crítico/Grave/Médio/Mínimo): ").strip().capitalize()
                print("  GUT: ex.  G:5, U:4, T:3   (Gravidade, Urgência, Tendência  — escala 1-5)")
                gut_p   = input("  GUT: ").strip()
                if risco_p and gut_p:
                    self.db.atualizar_risco_gut(tid, risco_p, gut_p)
                    print("  ✅ Avaliação registrada.")
            elif op in ('R', 'r'):
                self._reavaliar_com_gut_adaptativo()
            elif op == '2':
                self._exportar_gut_excel()
            else:
                print("  Opção inválida.")

    def _exportar_gut_excel(self):
        """Exporta apenas a aba Matriz de Risco para Excel."""
        try:
            import openpyxl
            wb  = openpyxl.Workbook()
            ws  = wb.active; ws.title = "Matriz de Risco"
            ws.append(['ID','Laudo','Título','Grau (auto)','GUT (auto)',
                       'Grau (perito)','GUT (perito)','Tipo Anomalia'])
            for a in self.db.listar_anomalias_risco():
                ws.append([a['id'], a['nome_arquivo'], a['titulo_topico'],
                            a['grau_risco'], a['matriz_gut'],
                            a['avaliacao_risco_usuario'] or '', a['avaliacao_gut_usuario'] or '',
                            a['criterio_ia'] or ''])
            fname = "Matriz_GUT_Pericial.xlsx"
            wb.save(fname)
            print(f"  ✅ Exportado: {fname}")
        except Exception as e:
            print(f"  ❌ Erro: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    #  GUT ADAPTATIVO
    # ─────────────────────────────────────────────────────────────────────────

    def gut_adaptativo_cli(self, descricao: str = '', topico_id: int = None):
        """
        Ponto de entrada CLI para o GUT Adaptativo v4.0.
        Conforme Seção 13 do prompt de implementação gut_adaptativo.py v4.0.
        """
        if not _GUT_ADAPTATIVO_OK:
            print("\n  ⚠️  gut_adaptativo.py não encontrado.")
            print("     Copie o arquivo para a pasta do projeto e tente novamente.")
            return

        print("\n" + "=" * 65)
        print("  📊 GUT ADAPTATIVO v4.0 — Avaliação Científica de Anomalias")
        print("  Ref: Knapp & Olivan (2021) | Grossi (2025) | NBR 15575-1:2024")
        print("=" * 65)

        if topico_id and not descricao:
            try:
                conn_tmp = self.db.get_connection()
                cur = conn_tmp.cursor()
                cur.execute(
                    "SELECT titulo_topico, grau_risco FROM topicos WHERE id = ?",
                    (topico_id,)
                )
                row = cur.fetchone()
                conn_tmp.close()
                if row:
                    descricao = row[0]
                    print(f"\n  📎 Tópico {topico_id}: {descricao}")
                    if row[1] and row[1] != '-':
                        print(f"     Risco atual: {row[1]}")
            except Exception as e:
                print(f"  ⚠️  Não foi possível carregar o tópico: {e}")

        if not descricao:
            print("\n  Digite a descrição da anomalia ou 'topico:ID' para carregar do banco.")
            entrada = input("  > ").strip()
            if entrada.lower().startswith('topico:'):
                try:
                    tid = int(entrada.split(':')[1].strip())
                    conn_tmp = self.db.get_connection()
                    cur = conn_tmp.cursor()
                    cur.execute("SELECT titulo_topico FROM topicos WHERE id = ?", (tid,))
                    row = cur.fetchone()
                    conn_tmp.close()
                    if row:
                        descricao = row[0]
                        topico_id = tid
                        print(f"  📎 Tópico {tid}: {descricao}")
                    else:
                        print(f"  ⚠️  Tópico {tid} não encontrado.")
                        return
                except (ValueError, IndexError):
                    descricao = entrada
            else:
                descricao = entrada

        if len(descricao.strip()) < 5:
            print("  ⚠️  Descrição muito curta. Informe ao menos 5 caracteres.")
            return

        conn = self.db.get_connection()
        try:
            ai_eng = getattr(self, 'ai', None)
            engine = GUTAdaptativo(
                conn=conn,
                ai_engine=ai_eng,
                db_manager=self.db,   # ← permite [C] Consultar banco dentro do GUT
            )
            resultado = engine.avaliar(descricao)
            if resultado and topico_id:
                print(f"\n  🔗 Vincular resultado ao Tópico {topico_id}? [S/N]: ", end="")
                if input().upper().strip() == 'S':
                    if engine.exportar_para_gut(resultado, topico_id):
                        print(f"  ✅ GUT exportado para Tópico {topico_id}.")
                    else:
                        print("  ⚠️  Não foi possível exportar.")
        except KeyboardInterrupt:
            print("\n\n  Avaliação cancelada.")
        except Exception as e:
            print(f"\n  ❌ Erro: {e}")
            import logging; logging.getLogger(__name__).exception("gut_adaptativo_cli")
        finally:
            conn.close()

    def _reavaliar_com_gut_adaptativo(self):
        """Atalho [R] dentro do [gut]. Carrega anomalia pelo ID do tópico."""
        print("\n  Informe o ID do tópico para reavaliar com GUT Adaptativo:")
        try:
            tid = int(input("  ID: ").strip())
        except ValueError:
            print("  ⚠️  ID inválido.")
            return
        self.gut_adaptativo_cli(topico_id=tid)

    # ─────────────────────────────────────────────────────────────────────────
    #  CONSULTAS POPULARES
    # ─────────────────────────────────────────────────────────────────────────

    def exibir_consultas_populares(self, n: int = 10):
        sep = "─" * 70

        # ── Seção 1: Termos mais pesquisados ─────────────────────────────────
        print(f"\n  {sep}")
        print("  📊  TERMOS MAIS PESQUISADOS")
        print(f"  {sep}")
        top = self.db.top_consultas(n)
        if not top:
            print("  (nenhuma consulta registrada ainda)")
        else:
            for i, (termo, cnt, ultima) in enumerate(top, 1):
                barra = "█" * min(cnt, 20)
                print(f"  {i:>2}. {barra:<20} {cnt:>4}x  \"{termo}\"  ({ultima[:10]})")

        # ── Seção 2: Trechos mais enviados ao LLM ────────────────────────────
        print(f"\n  {sep}")
        print("  🔁  TRECHOS MAIS UTILIZADOS PELA IA")
        print(f"  {sep}")
        usados = self.db.top_trechos_utilizados(n)
        if not usados:
            print("  (nenhum trecho registrado ainda — disponível após consultas com IA)")
        else:
            for i, row in enumerate(usados, 1):
                titulo, arq, usos, fav, ultimo = row[1], row[3], row[5], row[6], row[7]
                fav_badge = " ★" if fav else "  "
                data_txt  = str(ultimo)[:10] if ultimo else "-"
                titulo_tx = (titulo or '')[:38]
                print(f"  {i:>2}.{fav_badge} [{usos:>3}x]  {arq[:25]} › {titulo_tx}  ({data_txt})")

        # ── Seção 3: Favoritos com histórico de uso ───────────────────────────
        print(f"\n  {sep}")
        print("  ★  FAVORITOS DO PERITO  (contagem de uso pela IA)")
        print(f"  {sep}")
        favs = self.db.top_favoritos_com_uso(n)
        if not favs:
            print("  (nenhum trecho marcado como favorito — use F<n> nos resultados de busca)")
        else:
            for i, row in enumerate(favs, 1):
                titulo, arq, usos, ultimo = row[1], row[3], row[5], row[6]
                usos_txt = f"{usos}x" if usos else "não usado pela IA ainda"
                data_txt = str(ultimo)[:10] if ultimo else "-"
                titulo_tx = (titulo or '')[:38]
                print(f"  {i:>2}. ★  {arq[:25]} › {titulo_tx}  |  {usos_txt}  ({data_txt})")
        print()

    # ─────────────────────────────────────────────────────────────────────────
    #  INTERAÇÃO COM PATOLOGIA
    # ─────────────────────────────────────────────────────────────────────────

    def interagir_patologia(self, dados_ia: dict, arquivo_nome: str):
        print("\n" + "=" * 70)
        print(f"  ⚠️  AVALIAÇÃO DE PATOLOGIA — {arquivo_nome}")
        print("-" * 70)
        print(f"  [1] RISCO sugerido: {dados_ia.get('risco','')}")
        ar = input("  Sua avaliação de Risco (ENTER para manter): ").strip()
        if not ar: ar = dados_ia.get('risco', '')
        print(f"\n  [2] GUT sugerida: {dados_ia.get('gut','')}")
        ag = input("  Sua avaliação GUT (ENTER para manter): ").strip()
        if not ag: ag = dados_ia.get('gut', '')
        print("  ✅ Avaliações registradas!")
        return ar, ag

    # ─────────────────────────────────────────────────────────────────────────
    #  EXPORTAÇÃO EXCEL
    # ─────────────────────────────────────────────────────────────────────────

    def exportar_excel(self):
        try:
            conn   = self.db.get_connection()
            cursor = conn.cursor()
            wb     = openpyxl.Workbook()

            # Aba 1 — Banco documental (com colunas llama)
            ws_doc = wb.active
            ws_doc.title = "Banco Documental e Normas"
            ws_doc.append([
                'Arquivo', 'Tipo', 'Item', 'Hierarquia',
                'Texto Original', 'Justificativa (llama)', 'Palavras-Chave',
                'Status llama', 'Classif. Uso', 'Score Final',
                'Classif. Texto', 'Patologias', 'Normas', 'Estruturas',
                'Score Qualidade', 'Score Fundament.', 'Score Aplicab.',
                'Sugestão de Uso',
            ])

            # Aba 2 — Parâmetros normativos
            ws_param = wb.create_sheet("Parâmetros Normativos")
            ws_param.append(['Norma', 'Tipo', 'Parâmetro', 'Valor', 'Unidade',
                             'Item', 'Pág.', 'Contexto'])

            # Aba 3 — Matriz de Risco
            ws_risco = wb.create_sheet("Matriz de Risco")
            ws_risco.append(['Origem', 'Análise', 'Risco (IA)', 'Risco (Perito)',
                             'GUT (IA)', 'GUT (Perito)', 'Critério', 'Palavras-Chave'])

            # Aba 4 — Quesitos
            ws_q = wb.create_sheet("Quesitos Respondidos")
            ws_q.append(['Laudo Fonte', 'Sessão', 'Pergunta', 'Resposta'])

            # Aba 5 — Textos manuais + favoritos do perito
            ws_man = wb.create_sheet("Textos Manuais")
            ws_man.append(['Origem', 'Favorito', 'Tópico', 'Texto Original', 'Análise',
                           'Palavras-Chave', 'Observação do Perito'])

            import json as _json_exp
            cursor.execute('''
                SELECT l.nome_arquivo, l.tipo_fonte,
                       t.numero_topico, t.hierarquia,
                       t.texto_original, t.texto_reescrito,
                       t.grau_risco, t.matriz_gut, t.criterio_ia,
                       t.avaliacao_risco_usuario, t.avaliacao_gut_usuario,
                       t.palavras_chave, t.id,
                       t.status_processamento,
                       COALESCE(t.favorito, 0), COALESCE(t.comentario_usuario, '')
                FROM topicos t JOIN laudos l ON t.laudo_id = l.id
            ''')
            erros = 0
            topico_rows = cursor.fetchall()

            # Carregar dados completos do laudos_estruturado
            le_dict = {}
            try:
                le_rows = cursor.execute(
                    "SELECT topico_id, sumario, patologias, normas_identificadas, estruturas, "
                    "confianca_extracao, status_relevancia, classificacao_texto, "
                    "score_qualidade, score_fundamentacao, score_aplicabilidade, "
                    "classificacao_uso, sugestao_uso "
                    "FROM laudos_estruturado WHERE processado_fase1=1"
                ).fetchall()
                for r in le_rows:
                    le_dict[r[0]] = r
            except Exception:
                try:
                    le_rows = cursor.execute(
                        "SELECT topico_id, sumario, patologias, normas_identificadas, "
                        "estruturas, confianca_extracao, status_relevancia "
                        "FROM laudos_estruturado WHERE processado_fase1=1"
                    ).fetchall()
                    for r in le_rows:
                        le_dict[r[0]] = r
                except Exception:
                    pass

            for row in topico_rows:
                try:
                    origem    = _celula(row[0])
                    topico_id = row[12]
                    status_p  = _celula(row[13]) if len(row) > 13 else ""
                    le        = le_dict.get(topico_id)

                    # Justificativa técnica (NÃO reescrita — texto original intacto)
                    justif = _celula(le[1]) if (le and le[1]) else ""

                    if le:
                        try: patologias = ", ".join(_json_exp.loads(le[2] or "[]")[:5])
                        except Exception: patologias = ""
                        try: normas = ", ".join(_json_exp.loads(le[3] or "[]")[:5])
                        except Exception: normas = ""
                        try: estruturas = ", ".join(_json_exp.loads(le[4] or "[]")[:4])
                        except Exception: estruturas = ""
                        confianca    = _celula(le[5])
                        status_llama = _celula(le[6]) if le[6] else "fase_1_ia"
                        class_texto  = _celula(le[7])  if len(le) > 7  else ""
                        sc_qual      = le[8]            if len(le) > 8  else ""
                        sc_fund      = le[9]            if len(le) > 9  else ""
                        sc_aplic     = le[10]           if len(le) > 10 else ""
                        class_uso    = _celula(le[11])  if len(le) > 11 else confianca
                        sugestao     = _celula(le[12])  if len(le) > 12 else ""
                    else:
                        patologias = normas = estruturas = confianca = ""
                        status_llama = status_p or "nao_processado"
                        class_texto = class_uso = sugestao = ""
                        sc_qual = sc_fund = sc_aplic = ""

                    _eh_favorito = row[14] if len(row) > 14 else 0
                    _obs_perito  = row[15] if len(row) > 15 else ''
                    if origem == 'INSERÇÃO MANUAL' or _eh_favorito:
                        ws_man.append([_celula(c) for c in [
                            row[0],
                            "★ Favorito" if _eh_favorito else "",
                            row[2], row[4], row[5], row[11],
                            _obs_perito,
                        ]])
                    elif _celula(row[6]) != '-':
                        ws_risco.append([_celula(c) for c in
                                        [row[0],row[5],row[6],row[9],row[7],row[10],row[8],row[11]]])
                    else:
                        ws_doc.append([
                            _celula(row[0]), _celula(row[1]), _celula(row[2]),
                            _celula(row[3]), _celula(row[4]), justif,
                            _celula(row[11]), status_llama, class_uso, sc_qual,
                            class_texto, patologias, normas, estruturas,
                            sc_qual, sc_fund, sc_aplic, sugestao,
                        ])
                except Exception: erros += 1

            cursor.execute('''
                SELECT l.nome_arquivo, l.tipo_fonte,
                       p.parametro, p.valor, p.unidade, p.item_ref, p.pagina, p.contexto
                FROM parametros_normativos p JOIN laudos l ON p.laudo_id = l.id
            ''')
            for row in cursor.fetchall():
                try: ws_param.append([_celula(c) for c in row])
                except Exception: erros += 1

            cursor.execute('''
                SELECT l.nome_arquivo, q.origem_quesito, q.pergunta, q.resposta_perito
                FROM quesitos_respondidos q JOIN laudos l ON q.laudo_id = l.id
            ''')
            for row in cursor.fetchall():
                try: ws_q.append([_celula(c) for c in row])
                except Exception: erros += 1

            filename = "Banco_Pericial_Multimodal.xlsx"
            wb.save(filename)
            conn.close()
            msg = f"✅ Excel gerado: {filename}"
            if erros: msg += f" (⚠️ {erros} linhas ignoradas)"
            print(f"\n  {msg}")
        except Exception as e:
            print(f"\n  ❌ Erro ao gerar Excel: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    #  SALVAR TEXTO AVULSO
    # ─────────────────────────────────────────────────────────────────────────

    def salvar_manual(self, texto: str) -> str:
        laudo_id = (self.db.buscar_laudo_por_nome('INSERÇÃO MANUAL') or
                    self.db.registrar_laudo('INSERÇÃO MANUAL'))
        resumo  = texto[:40].replace("\n", " ") + "..."
        analise = self.ai.processar_texto(texto, f"Texto Avulso: {resumo}")
        self.db.salvar_topico(laudo_id, "-", "Texto Manual Avulso",
                              texto, analise)
        return analise

    # ─────────────────────────────────────────────────────────────────────────
    #  GUI TKINTER
    # ─────────────────────────────────────────────────────────────────────────

    def abrir_gui(self):
        """Inicia a interface gráfica moderna (dark theme)."""
        try:
            root = tk.Tk()
            gui  = CerebroPericialGUI(root, self)
            gui.iniciar()
        except Exception as e:
            print(f"\n  ❌ Interface gráfica indisponível: {e}")
            print("  ℹ️  Execute em ambiente com display gráfico (Windows/macOS/X11).")


# ══════════════════════════════════════════════════════════════════════════════
#  GUI — DESIGN SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

def _detectar_fontes() -> dict:
    """Detecta as melhores fontes disponíveis no sistema operacional."""
    import sys
    if sys.platform == "win32":
        return {"ui": "Segoe UI", "mono": "Consolas"}
    elif sys.platform == "darwin":
        return {"ui": "SF Pro Display", "mono": "Menlo"}
    else:
        return {"ui": "Ubuntu", "mono": "DejaVu Sans Mono"}

_F = _detectar_fontes()

CORES = {
    "bg_principal":      "#0F1923",
    "bg_secundario":     "#1A2535",
    "bg_terciario":      "#243044",
    "bg_hover":          "#2D3F55",
    "accent_azul":       "#3B82F6",
    "accent_azul_hover": "#2563EB",
    "accent_verde":      "#10B981",
    "accent_amarelo":    "#F59E0B",
    "accent_vermelho":   "#EF4444",
    "texto_primario":    "#F1F5F9",
    "texto_secundario":  "#94A3B8",
    "texto_muted":       "#64748B",
    "borda":             "#2D3F55",
    "separador":         "#1E2D3D",
    "badge_critico_bg":  "#EF4444",
    "badge_critico_fg":  "#FFFFFF",
    "badge_alto_bg":     "#F59E0B",
    "badge_alto_fg":     "#1A1A1A",
    "badge_medio_bg":    "#3B82F6",
    "badge_medio_fg":    "#FFFFFF",
    "badge_minimo_bg":   "#10B981",
    "badge_minimo_fg":   "#FFFFFF",
}

FONTES = {
    "titulo":     (_F["ui"], 16, "bold"),
    "subtitulo":  (_F["ui"], 13, "bold"),
    "corpo":      (_F["ui"], 11),
    "corpo_bold": (_F["ui"], 11, "bold"),
    "pequena":    (_F["ui"], 9),
    "mono":       (_F["mono"], 10),
    "mono_bold":  (_F["mono"], 10, "bold"),
}


# ══════════════════════════════════════════════════════════════════════════════
#  CP — COMPONENTES PERICIAL
# ══════════════════════════════════════════════════════════════════════════════

class CPBotao(tk.Frame):
    """
    Botão estilizado com hover, pressed state e variantes.
    Variantes: 'primario' | 'secundario' | 'perigo' | 'sucesso' | 'ghost'
    Exemplo: CPBotao(frame, "Buscar", cmd=buscar, variante="primario")
    """
    _VARS = {
        "primario":   (CORES["accent_azul"],     CORES["accent_azul_hover"], CORES["texto_primario"]),
        "secundario": (CORES["bg_terciario"],    CORES["bg_hover"],          CORES["texto_primario"]),
        "perigo":     (CORES["accent_vermelho"], "#DC2626",                  CORES["texto_primario"]),
        "sucesso":    (CORES["accent_verde"],    "#059669",                  CORES["texto_primario"]),
        "ghost":      (CORES["bg_secundario"],   CORES["bg_terciario"],      CORES["texto_secundario"]),
    }

    def __init__(self, parent, texto: str, cmd=None,
                 variante: str = "primario", largura: int = None,
                 icone: str = "", **kw):
        cor_n, cor_h, cor_fg = self._VARS.get(variante, self._VARS["primario"])
        super().__init__(parent, bg=cor_n, cursor="hand2", **kw)
        self._cor_n = cor_n
        self._cor_h = cor_h
        self._cmd   = cmd

        txt = f"{icone} {texto}".strip() if icone else texto
        self._lbl = tk.Label(self, text=txt, bg=cor_n, fg=cor_fg,
                             font=FONTES["corpo_bold"], padx=14, pady=7,
                             width=largura or 0)
        self._lbl.pack(fill="x")

        for w in (self, self._lbl):
            w.bind("<Enter>",    self._hover_on)
            w.bind("<Leave>",    self._hover_off)
            w.bind("<Button-1>", self._click)
            w.bind("<ButtonRelease-1>", self._release)

    def _hover_on(self, _=None):
        self.config(bg=self._cor_h)
        self._lbl.config(bg=self._cor_h)

    def _hover_off(self, _=None):
        self.config(bg=self._cor_n)
        self._lbl.config(bg=self._cor_n)

    def _click(self, _=None):
        self.config(bg=CORES["bg_principal"])
        self._lbl.config(bg=CORES["bg_principal"])

    def _release(self, _=None):
        self._hover_on()
        if self._cmd:
            try:
                self._cmd()
            except Exception as e:
                import logging, traceback
                logging.getLogger(__name__).error(f"CPBotao cmd: {e}")
                traceback.print_exc()
                try:
                    tk.messagebox.showerror("Erro", str(e))
                except Exception:
                    pass


class CPCard(tk.Frame):
    """
    Container estilizado com borda, padding e título opcional.
    Exemplo: card = CPCard(frame, titulo="Resultados", padding=16)
    """
    def __init__(self, parent, titulo: str = None, padding: int = 16, **kw):
        super().__init__(parent, bg=CORES["bg_secundario"],
                         highlightbackground=CORES["borda"],
                         highlightthickness=1, **kw)
        self._inner = tk.Frame(self, bg=CORES["bg_secundario"])
        self._inner.pack(fill="both", expand=True,
                         padx=padding, pady=padding)
        if titulo:
            tk.Label(self._inner, text=titulo, bg=CORES["bg_secundario"],
                     fg=CORES["texto_primario"], font=FONTES["subtitulo"],
                     anchor="w").pack(fill="x", pady=(0, 4))
            tk.Frame(self._inner, bg=CORES["separador"], height=1).pack(
                fill="x", pady=(0, padding // 2))

    @property
    def inner(self) -> tk.Frame:
        return self._inner


class CPTabela(tk.Frame):
    """
    Tabela estilizada com Treeview, scroll, linhas alternadas e ordenação.
    Exemplo:
        tb = CPTabela(frame, colunas=["ID","Título","Risco"])
        tb.popular([{"ID": 1, "Título": "Fissura", "Risco": "Crítico"}])
    """
    def __init__(self, parent, colunas: list[str], larguras: dict = None, **kw):
        super().__init__(parent, bg=CORES["bg_secundario"], **kw)
        self._colunas    = colunas
        self._larguras   = larguras or {}
        self._sort_col   = None
        self._sort_asc   = True
        self._dados      = []
        self._on_select  = None

        style = ttk.Style()
        for _t in ("clam", "alt", "default"):
            try:
                style.theme_use(_t)
                break
            except Exception:
                pass
        style.configure("Pericial.Treeview",
            background=CORES["bg_secundario"],
            foreground=CORES["texto_primario"],
            fieldbackground=CORES["bg_secundario"],
            rowheight=30, font=FONTES["corpo"],
            borderwidth=0, relief="flat")
        style.configure("Pericial.Treeview.Heading",
            background=CORES["bg_terciario"],
            foreground=CORES["texto_secundario"],
            font=FONTES["corpo_bold"], relief="flat")
        style.map("Pericial.Treeview",
            background=[("selected", CORES["accent_azul"])],
            foreground=[("selected", "#FFFFFF")])
        style.configure("Vertical.TScrollbar",
            background=CORES["bg_terciario"],
            troughcolor=CORES["bg_principal"],
            arrowcolor=CORES["texto_muted"],
            borderwidth=0, width=8)

        self._tv = ttk.Treeview(
            self, columns=colunas, show="headings",
            style="Pericial.Treeview",
            selectmode="browse"
        )
        for col in colunas:
            larg = self._larguras.get(col, 120)
            self._tv.heading(col, text=col,
                             command=lambda c=col: self._ordenar(c))
            self._tv.column(col, width=larg, minwidth=40, anchor="w")

        vsb = ttk.Scrollbar(self, orient="vertical",
                                command=self._tv.yview,
                                style="Vertical.TScrollbar")
        self._tv.configure(yscrollcommand=vsb.set)
        self._tv.tag_configure("par",   background=CORES["bg_secundario"])
        self._tv.tag_configure("impar", background=CORES["bg_terciario"])
        self._tv.tag_configure("hover", background=CORES["bg_hover"])

        self._tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._tv.bind("<<TreeviewSelect>>", self._ao_selecionar)
        self._tv.bind("<Motion>", self._hover_row)
        self._hover_item = None

    def popular(self, dados: list[dict]) -> None:
        """Preenche a tabela. dados = lista de dicts com chaves = colunas."""
        self._dados = dados
        self._tv.delete(*self._tv.get_children())
        for i, row in enumerate(dados):
            valores = [str(row.get(c, "")) for c in self._colunas]
            tag     = "par" if i % 2 == 0 else "impar"
            self._tv.insert("", "end", iid=str(i), values=valores, tags=(tag,))

    def item_selecionado(self) -> dict | None:
        """Retorna o dict do item selecionado ou None."""
        sel = self._tv.selection()
        if not sel:
            return None
        idx = int(sel[0])
        return self._dados[idx] if idx < len(self._dados) else None

    def ao_selecionar(self, callback) -> None:
        """Define callback chamado ao selecionar linha: callback(dict_linha)."""
        self._on_select = callback

    def _ao_selecionar(self, _=None):
        if self._on_select:
            d = self.item_selecionado()
            if d:
                try:
                    self._on_select(d)
                except Exception:
                    pass

    def _ordenar(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        dados_ord = sorted(self._dados, key=lambda r: str(r.get(col, "")),
                           reverse=not self._sort_asc)
        self.popular(dados_ord)

    def _hover_row(self, event):
        item = self._tv.identify_row(event.y)
        if item != self._hover_item:
            if self._hover_item:
                idx = int(self._hover_item) if self._hover_item.isdigit() else 0
                tag = "par" if idx % 2 == 0 else "impar"
                try:
                    self._tv.item(self._hover_item, tags=(tag,))
                except tk.TclError:
                    pass
            self._hover_item = item
            if item:
                try:
                    self._tv.item(item, tags=("hover",))
                except tk.TclError:
                    pass


class CPBadgeRisco(tk.Label):
    """
    Badge colorido de risco. Cores por nível.
    Exemplo: CPBadgeRisco(frame, "Crítico")
    """
    _MAP = {
        "crítico": (CORES["badge_critico_bg"], CORES["badge_critico_fg"]),
        "alto":    (CORES["badge_alto_bg"],    CORES["badge_alto_fg"]),
        "médio":   (CORES["badge_medio_bg"],   CORES["badge_medio_fg"]),
        "medio":   (CORES["badge_medio_bg"],   CORES["badge_medio_fg"]),
        "mínimo":  (CORES["badge_minimo_bg"],  CORES["badge_minimo_fg"]),
        "minimo":  (CORES["badge_minimo_bg"],  CORES["badge_minimo_fg"]),
        "baixo":   (CORES["badge_minimo_bg"],  CORES["badge_minimo_fg"]),
    }

    def __init__(self, parent, risco: str = "", **kw):
        key   = risco.lower().strip()
        bg, fg = self._MAP.get(key, (CORES["bg_terciario"], CORES["texto_muted"]))
        super().__init__(parent, text=risco,
                         bg=bg, fg=fg,
                         font=FONTES["pequena"],
                         padx=8, pady=3,
                         relief="flat", **kw)


class CPEntrada(tk.Frame):
    """
    Campo de entrada estilizado com placeholder e suporte multilinhas.
    Exemplo:
        e = CPEntrada(frame, placeholder="Buscar anomalia...")
        e.get()  # retorna o texto atual
    """
    # Cores fixas para alta visibilidade (fundo branco, texto escuro)
    _BG_ENTRY  = "#FFFFFF"
    _FG_TEXT   = "#1E293B"
    _FG_PH     = "#94A3B8"
    _BD_NORMAL = "#CBD5E1"
    _BD_FOCUS  = "#3B82F6"

    def __init__(self, parent, placeholder: str = "",
                 multilinhas: bool = False, altura: int = 4, **kw):
        super().__init__(parent, bg=self._BD_NORMAL,
                         highlightthickness=0, **kw)
        self._ph    = placeholder
        self._multi = multilinhas
        self._ph_on = False

        # Borda interna visível (2px cinza claro, fica azul no foco)
        self._border = tk.Frame(self, bg=self._BD_NORMAL)
        self._border.pack(fill="both", expand=True, padx=2, pady=2)

        common = dict(
            bg=self._BG_ENTRY, fg=self._FG_TEXT,
            insertbackground=CORES["accent_azul"],
            highlightthickness=0, relief="flat",
            font=FONTES["corpo"],
        )
        if multilinhas:
            self._w = tk.Text(self._border, height=altura, wrap="word", **common)
        else:
            self._w = tk.Entry(self._border, **common)

        self._w.pack(fill="both", expand=True, padx=6, pady=5)
        self._w.bind("<FocusIn>",  self._focus_in)
        self._w.bind("<FocusOut>", self._focus_out)
        # Clicar em qualquer área do frame foca o entry interno
        for w in (self, self._border):
            w.bind("<Button-1>", lambda _: self._w.focus_set())

        if placeholder:
            self._mostrar_placeholder()

    def _mostrar_placeholder(self):
        self._ph_on = True
        if self._multi:
            self._w.delete("1.0", "end")
            self._w.insert("1.0", self._ph)
        else:
            self._w.delete(0, "end")
            self._w.insert(0, self._ph)
        self._w.config(fg=self._FG_PH)

    def _limpar_placeholder(self):
        if self._ph_on:
            if self._multi:
                self._w.delete("1.0", "end")
            else:
                self._w.delete(0, "end")
            self._w.config(fg=self._FG_TEXT)
            self._ph_on = False

    def _focus_in(self, _=None):
        self.config(bg=self._BD_FOCUS)
        self._border.config(bg=self._BD_FOCUS)
        self._limpar_placeholder()

    def _focus_out(self, _=None):
        self.config(bg=self._BD_NORMAL)
        self._border.config(bg=self._BD_NORMAL)
        if not self.get():
            self._mostrar_placeholder()

    def _hover_on(self, _=None):
        pass

    def _hover_off(self, _=None):
        pass

    def get(self) -> str:
        """Retorna o texto atual (vazio se placeholder ativo)."""
        if self._ph_on:
            return ""
        if self._multi:
            return self._w.get("1.0", "end-1c")
        return self._w.get()

    def set(self, texto: str) -> None:
        """Define o texto programaticamente."""
        self._ph_on = False
        if self._multi:
            self._w.delete("1.0", "end")
            self._w.insert("1.0", texto)
        else:
            self._w.delete(0, "end")
            self._w.insert(0, texto)
        self._w.config(fg=CORES["texto_primario"])

    def bind_enter(self, callback) -> None:
        """Bind Enter para disparo de busca (útil em campo single-line)."""
        self._w.bind("<Return>", lambda _: callback())

    @property
    def widget(self):
        return self._w


class CPNotificacao:
    """
    Toast de notificação deslizante no canto inferior direito.
    Exemplo:
        CPNotificacao.sucesso(root, "Salvo com sucesso!")
        CPNotificacao.erro(root, "Falha ao conectar")
    """
    _fila: list = []

    @classmethod
    def sucesso(cls, root, msg: str, duracao: int = 3000):
        cls._mostrar(root, msg, CORES["accent_verde"], duracao)

    @classmethod
    def erro(cls, root, msg: str, duracao: int = 5000):
        cls._mostrar(root, msg, CORES["accent_vermelho"], duracao)

    @classmethod
    def info(cls, root, msg: str, duracao: int = 3000):
        cls._mostrar(root, msg, CORES["accent_azul"], duracao)

    @classmethod
    def _mostrar(cls, root, msg: str, cor: str, duracao: int):
        try:
            top = tk.Toplevel(root)
            top.overrideredirect(True)
            top.attributes("-topmost", True)
            top.configure(bg=cor)
            tk.Label(top, text=msg, bg=cor, fg="#FFFFFF",
                     font=FONTES["corpo"], padx=16, pady=10,
                     wraplength=280).pack()
            top.bind("<Button-1>", lambda _: top.destroy())

            def _posicionar(offset_y: int = 0):
                root.update_idletasks()
                w  = top.winfo_reqwidth()
                h  = top.winfo_reqheight()
                rx = root.winfo_x() + root.winfo_width()  - w - 20
                ry = root.winfo_y() + root.winfo_height() - h - 30 - offset_y
                top.geometry(f"+{rx}+{ry}")

            _posicionar(offset_y=len(cls._fila) * 60)
            cls._fila.append(top)
            root.after(duracao, lambda: cls._fechar(top))
        except Exception:
            pass

    @classmethod
    def _fechar(cls, top):
        try:
            if top in cls._fila:
                cls._fila.remove(top)
            top.destroy()
        except Exception:
            pass


class CPProgresso(tk.Frame):
    """
    Barra de progresso customizada com animação indeterminada.
    Exemplo:
        pb = CPProgresso(frame, largura=400)
        pb.indeterminado()
        pb.atualizar(0.6)
        pb.resetar()
    """
    def __init__(self, parent, largura: int = 400, altura: int = 6, **kw):
        super().__init__(parent, bg=CORES["bg_secundario"], **kw)
        self._larg  = largura
        self._alt   = altura
        self._after = None

        self._canvas = tk.Canvas(
            self, width=largura, height=altura,
            bg=CORES["bg_terciario"], highlightthickness=0
        )
        self._canvas.pack()
        self._barra = self._canvas.create_rectangle(
            0, 0, 0, altura, fill=CORES["accent_azul"], outline=""
        )

    def atualizar(self, valor: float) -> None:
        """valor: 0.0 a 1.0"""
        self._cancelar_anim()
        w = max(0, min(int(self._larg * valor), self._larg))
        self._canvas.coords(self._barra, 0, 0, w, self._alt)

    def indeterminado(self) -> None:
        """Animação de varredura contínua."""
        self._cancelar_anim()
        self._pos   = 0
        self._dir   = 1
        self._tam   = self._larg // 4
        self._anim_loop()

    def _anim_loop(self):
        self._pos += self._dir * 6
        if self._pos + self._tam > self._larg:
            self._dir = -1
        elif self._pos < 0:
            self._dir = 1
        self._canvas.coords(self._barra, self._pos, 0,
                             self._pos + self._tam, self._alt)
        self._after = self.after(30, self._anim_loop)

    def resetar(self) -> None:
        self._cancelar_anim()
        self._canvas.coords(self._barra, 0, 0, 0, self._alt)

    def _cancelar_anim(self):
        if self._after:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
            self._after = None


class CPDropdown(tk.Frame):
    """
    Combobox estilizado com tema escuro.
    Exemplo:
        dd = CPDropdown(frame, opcoes=["NBR","DOCX"], callback=on_change)
        dd.get()  # retorna a opção selecionada
    """
    def __init__(self, parent, opcoes: list[str], callback=None,
                 largura: int = 20, **kw):
        super().__init__(parent, bg=CORES["bg_secundario"], **kw)
        self._var = tk.StringVar(value=opcoes[0] if opcoes else "")
        self._cb  = callback

        style = ttk.Style()
        style.configure("Pericial.TCombobox",
            background=CORES["bg_terciario"],
            foreground=CORES["texto_primario"],
            fieldbackground=CORES["bg_terciario"],
            selectbackground=CORES["accent_azul"],
            arrowcolor=CORES["texto_secundario"],
            borderwidth=0)
        style.map("Pericial.TCombobox",
            background=[("readonly", CORES["bg_terciario"])],
            foreground=[("readonly", CORES["texto_primario"])])

        self._combo = ttk.Combobox(
            self, textvariable=self._var,
            values=opcoes, state="readonly",
            width=largura, style="Pericial.TCombobox",
            font=FONTES["corpo"]
        )
        self._combo.pack(fill="x")
        if callback:
            self._combo.bind("<<ComboboxSelected>>",
                             lambda _: callback(self._var.get()))

    def get(self) -> str:
        return self._var.get()

    def set(self, valor: str) -> None:
        self._var.set(valor)


class SidebarBtn(tk.Frame):
    """
    Botão de navegação da sidebar com estados: normal | hover | ativo.
    Exemplo: SidebarBtn(sidebar, "🔍 Consultar", lambda: nav("consultar"))
    """
    def __init__(self, parent, texto: str, cmd=None, **kw):
        super().__init__(parent, bg=CORES["bg_secundario"],
                         cursor="hand2", **kw)
        self._cmd    = cmd
        self._ativo  = False
        self._acento = tk.Frame(self, bg=CORES["bg_secundario"], width=3)
        self._acento.pack(side="left", fill="y")
        self._lbl = tk.Label(self, text=texto,
                              bg=CORES["bg_secundario"],
                              fg=CORES["texto_secundario"],
                              font=FONTES["corpo"], anchor="w",
                              padx=12, pady=10)
        self._lbl.pack(side="left", fill="x", expand=True)

        for w in (self, self._lbl):
            w.bind("<Enter>",    self._hover_on)
            w.bind("<Leave>",    self._hover_off)
            w.bind("<Button-1>", self._click)

    def _hover_on(self, _=None):
        if not self._ativo:
            self.config(bg=CORES["bg_hover"])
            self._lbl.config(bg=CORES["bg_hover"],
                             fg=CORES["texto_primario"])
            self._acento.config(bg=CORES["bg_hover"])

    def _hover_off(self, _=None):
        if not self._ativo:
            self.config(bg=CORES["bg_secundario"])
            self._lbl.config(bg=CORES["bg_secundario"],
                             fg=CORES["texto_secundario"])
            self._acento.config(bg=CORES["bg_secundario"])

    def _click(self, _=None):
        if self._cmd:
            try:
                self._cmd()
            except Exception:
                pass

    def ativar(self):
        self._ativo = True
        self.config(bg=CORES["bg_terciario"])
        self._lbl.config(bg=CORES["bg_terciario"], fg=CORES["accent_azul"])
        self._acento.config(bg=CORES["accent_azul"])

    def desativar(self):
        self._ativo = False
        self._hover_off()


# ══════════════════════════════════════════════════════════════════════════════
#  PAINÉIS POR MÓDULO
# ══════════════════════════════════════════════════════════════════════════════

class _PainelBase(tk.Frame):
    """Base comum para todos os painéis."""
    def __init__(self, parent, app: "CerebroEngenharia", **kw):
        super().__init__(parent, bg=CORES["bg_principal"], **kw)
        self.app = app

    def _titulo(self, frame: tk.Frame, texto: str) -> None:
        tk.Label(frame, text=texto, bg=CORES["bg_principal"],
                 fg=CORES["texto_primario"], font=FONTES["titulo"],
                 anchor="w").pack(fill="x", padx=20, pady=(16, 4))
        tk.Frame(frame, bg=CORES["separador"], height=1).pack(
            fill="x", padx=20, pady=(0, 12))


class PainelConsultar(_PainelBase):
    """Painel 🔍 Consulta Pericial com busca, cards de resultado e resposta IA."""

    def __init__(self, parent, app, gui_root, **kw):
        super().__init__(parent, app, **kw)
        self._root   = gui_root
        self._thread = None
        self._build()

    def _build(self):
        self._titulo(self, "🔍  CONSULTA PERICIAL")

        # --- Caixa de busca visível ---
        caixa = tk.Frame(self, bg=CORES["bg_secundario"],
                         highlightbackground=CORES["borda"], highlightthickness=1)
        caixa.pack(fill="x", padx=20, pady=(0, 4))

        tk.Label(caixa, text="Digite sua consulta:", bg=CORES["bg_secundario"],
                 fg=CORES["texto_secundario"], font=FONTES["corpo"]).pack(
                     anchor="w", padx=12, pady=(8, 2))

        bar = tk.Frame(caixa, bg=CORES["bg_secundario"])
        bar.pack(fill="x", padx=12, pady=(0, 8))

        self._entrada = tk.Entry(
            bar,
            bg="#FFFFFF", fg="#1E293B",
            insertbackground=CORES["accent_azul"],
            highlightthickness=2,
            highlightcolor=CORES["accent_azul"],
            highlightbackground="#CBD5E1",
            relief="flat",
            font=FONTES["corpo"],
        )
        self._entrada.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=6)
        self._entrada.bind("<Return>", lambda _: self._buscar())

        self._modo = CPDropdown(bar, ["Consultar (IA)", "Evidências", "Parâmetros"],
                                largura=18)
        self._modo.pack(side="left", padx=(0, 8))
        CPBotao(bar, "Buscar", self._buscar, variante="primario",
                icone="🔍").pack(side="left")

        # Dica de uso
        tk.Label(self, text="  Dica: use 'Evidências' para ver trechos do banco sem IA  |  "
                            "'Parâmetros' para valores normativos (alturas, cargas...)",
                 bg=CORES["bg_principal"], fg=CORES["texto_muted"],
                 font=FONTES["pequena"]).pack(anchor="w", padx=20, pady=(0, 8))

        # Progresso
        self._pb = CPProgresso(self, largura=600, altura=4)
        self._pb.pack(fill="x", padx=20, pady=(0, 8))

        # Área de resultados
        self._area = tk.Frame(self, bg=CORES["bg_principal"])
        self._area.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        self._canvas_r = tk.Canvas(self._area, bg=CORES["bg_principal"],
                                   highlightthickness=0)
        self._vsb_r    = ttk.Scrollbar(self._area, orient="vertical",
                                           command=self._canvas_r.yview)
        self._frame_r  = tk.Frame(self._canvas_r, bg=CORES["bg_principal"])
        self._frame_r.bind("<Configure>",
            lambda e: self._canvas_r.configure(
                scrollregion=self._canvas_r.bbox("all")))
        self._canvas_win = self._canvas_r.create_window(
            (0, 0), window=self._frame_r, anchor="nw")
        self._canvas_r.configure(yscrollcommand=self._vsb_r.set)
        self._canvas_r.pack(side="left", fill="both", expand=True)
        self._vsb_r.pack(side="right", fill="y")
        # Manter _frame_r com a largura total do canvas ao redimensionar
        self._canvas_r.bind("<Configure>",
            lambda e: self._canvas_r.itemconfig(self._canvas_win, width=e.width))
        self._canvas_r.bind("<MouseWheel>",
            lambda e: self._canvas_r.yview_scroll(-1*(e.delta//120), "units"))

    def _buscar(self):
        q = self._entrada.get().strip()
        if not q:
            return
        # Limpar resultados anteriores
        for w in self._frame_r.winfo_children():
            w.destroy()
        self._pb.indeterminado()
        modo = self._modo.get()
        self._thread = threading.Thread(target=self._executar_busca,
                                        args=(q, modo), daemon=True)
        self._thread.start()

    def _executar_busca(self, q: str, modo: str):
        try:
            if "Evidências" in modo:
                resultado = self.app.consultar_evidencias(q, modo_gui=True)
                tipo = "evidencias"
            elif "Parâmetros" in modo:
                resultado = self.app.consultar_parametros(q)
                tipo = "parametros"
            else:
                resultado = self.app.consultar(q, modo_gui=True)
                tipo = "consulta"
            self.after(0, lambda: self._mostrar_resultado(resultado, tipo))
        except Exception as e:
            self.after(0, lambda: self._mostrar_resultado(f"Erro: {e}", "erro"))
        finally:
            self.after(0, self._pb.resetar)

    def _mostrar_resultado(self, texto: str, tipo: str):
        for w in self._frame_r.winfo_children():
            w.destroy()

        # Exibir em card de texto
        card = CPCard(self._frame_r, titulo="Resultado")
        card.pack(fill="x", pady=4)
        t = tk.Text(card.inner, bg=CORES["bg_secundario"],
                    fg=CORES["texto_primario"], font=FONTES["mono"],
                    wrap="word", relief="flat",
                    height=min(30, max(8, texto.count("\n") + 3)))
        t.insert("1.0", texto)
        t.config(state="disabled")
        vsb = ttk.Scrollbar(card.inner, orient="vertical",
                                command=t.yview)
        t.config(yscrollcommand=vsb.set)
        # card.inner já usa pack (título + separador) — manter pack para t e vsb
        vsb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)

        # Botão copiar
        def copiar():
            self._root.clipboard_clear()
            self._root.clipboard_append(texto)
            CPNotificacao.sucesso(self._root, "Texto copiado!")

        CPBotao(self._frame_r, "📋 Copiar", copiar,
                variante="ghost").pack(anchor="w", pady=(4, 0))


class PainelFontes(_PainelBase):
    """Painel 📚 Gerenciamento de fontes do banco."""

    def __init__(self, parent, app, gui_root, **kw):
        super().__init__(parent, app, **kw)
        self._root = gui_root
        self._build()

    def _build(self):
        self._titulo(self, "📚  FONTES DO BANCO")

        # Cabeçalho com stats e botão
        cab = tk.Frame(self, bg=CORES["bg_principal"])
        cab.pack(fill="x", padx=20, pady=(0, 8))
        self._lbl_stats = tk.Label(
            cab, bg=CORES["bg_principal"], fg=CORES["texto_secundario"],
            font=FONTES["corpo"], anchor="w")
        self._lbl_stats.pack(side="left", fill="x", expand=True)
        CPBotao(cab, "Ingerir Arquivo", self._ingerir,
                variante="primario", icone="📥").pack(side="right")

        # Tabela
        self._tb = CPTabela(
            self,
            colunas=["ID", "Nome", "Tipo", "Tópicos", "Status"],
            larguras={"ID": 45, "Nome": 260, "Tipo": 100,
                      "Tópicos": 70, "Status": 80}
        )
        self._tb.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        # Botões de ação
        acs = tk.Frame(self, bg=CORES["bg_principal"])
        acs.pack(fill="x", padx=20, pady=(0, 12))
        CPBotao(acs, "Revogar",  self._revogar,  variante="secundario", icone="⏸️").pack(side="left", padx=(0, 6))
        CPBotao(acs, "Deletar",  self._deletar,  variante="perigo",     icone="❌").pack(side="left", padx=(0, 6))
        CPBotao(acs, "Atualizar", self._carregar, variante="ghost",      icone="🔄").pack(side="right")

        self._carregar()

    def _carregar(self):
        try:
            fontes = self.app.db.listar_fontes()
            stats  = self.app.db.estatisticas_banco()
            self._lbl_stats.config(
                text=f"{stats['fontes_ativas']} fontes ativas  •  "
                     f"{stats['trechos']} tópicos indexados  •  "
                     f"{stats['parametros']} parâmetros")
            dados = [{"ID": f["id"], "Nome": f["nome_arquivo"][:45],
                      "Tipo": f.get("tipo_fonte", "-"),
                      "Tópicos": f.get("n_trechos", f.get("total_topicos", 0)),
                      "Status": f.get("status", "ativo")}
                     for f in fontes]
            self._tb.popular(dados)
        except Exception as e:
            CPNotificacao.erro(self._root, f"Erro ao carregar fontes: {e}")

    def _revogar(self):
        item = self._tb.item_selecionado()
        if not item:
            CPNotificacao.info(self._root, "Selecione uma fonte.")
            return
        try:
            self.app.db.atualizar_fonte(int(item["ID"]), status='revogado')
            self._carregar()
            CPNotificacao.sucesso(self._root, "Fonte revogada.")
        except Exception as e:
            CPNotificacao.erro(self._root, f"Erro: {e}")

    def _deletar(self):
        item = self._tb.item_selecionado()
        if not item:
            CPNotificacao.info(self._root, "Selecione uma fonte.")
            return
        if not tk.messagebox.askyesno("Confirmar",
                f"Deletar fonte '{item['Nome']}'? Esta ação não pode ser desfeita."):
            return
        try:
            self.app.db.deletar_fonte(int(item["ID"]))
            self._carregar()
            CPNotificacao.sucesso(self._root, "Fonte deletada.")
        except Exception as e:
            CPNotificacao.erro(self._root, f"Erro: {e}")

    def _ingerir(self):
        from tkinter import filedialog
        arq = filedialog.askopenfilename(
            title="Selecionar arquivo",
            filetypes=[("Documentos", "*.pdf *.docx *.doc"),
                       ("PDF", "*.pdf"), ("Word", "*.docx")])
        if not arq:
            return
        import shutil
        ext   = arq.lower().rsplit(".", 1)[-1]
        pasta = "pdf_entrada" if ext == "pdf" else "doc_entrada"
        try:
            dest = os.path.join(pasta, os.path.basename(arq))
            shutil.copy2(arq, dest)
            CPNotificacao.info(self._root,
                               f"Copiado para {pasta}/. Use [arquivos] no CLI para processar.")
        except Exception as e:
            CPNotificacao.erro(self._root, f"Erro ao copiar: {e}")


class PainelGUT(_PainelBase):
    """Painel 📊 Matriz GUT / Grau de Risco."""

    def __init__(self, parent, app, gui_root, **kw):
        super().__init__(parent, app, **kw)
        self._root = gui_root
        self._build()

    def _build(self):
        self._titulo(self, "📊  MATRIZ GUT / GRAU DE RISCO")

        # Cards de contadores
        kpis = tk.Frame(self, bg=CORES["bg_principal"])
        kpis.pack(fill="x", padx=20, pady=(0, 12))
        self._kpi_vars = {}
        for label, chave in [("🔴 Crítico", "critico"), ("🟡 Alto", "alto"),
                              ("🔵 Médio", "medio"), ("🟢 Mínimo", "minimo"),
                              ("Total", "total")]:
            card = CPCard(kpis, titulo=label, padding=10)
            card.pack(side="left", padx=4, fill="y")
            var = tk.StringVar(value="0")
            tk.Label(card.inner, textvariable=var,
                     bg=CORES["bg_secundario"], fg=CORES["texto_primario"],
                     font=FONTES["titulo"]).pack()
            self._kpi_vars[chave] = var

        # Tabela de anomalias
        self._tb = CPTabela(
            self,
            colunas=["ID", "Título", "Risco (auto)", "GUT (auto)",
                     "Risco (perito)", "GUT (perito)"],
            larguras={"ID": 40, "Título": 260, "Risco (auto)": 90,
                      "GUT (auto)": 110, "Risco (perito)": 90, "GUT (perito)": 110}
        )
        self._tb.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        # Ações
        acs = tk.Frame(self, bg=CORES["bg_principal"])
        acs.pack(fill="x", padx=20, pady=(0, 12))
        CPBotao(acs, "Editar GUT",       self._editar,    variante="primario",   icone="✏️").pack(side="left", padx=(0, 6))
        CPBotao(acs, "GUT Adaptativo",   self._adaptativo, variante="secundario", icone="📐").pack(side="left", padx=(0, 6))
        CPBotao(acs, "Exportar Excel",   self._exportar,  variante="ghost",      icone="📥").pack(side="left", padx=(0, 6))
        CPBotao(acs, "Atualizar",        self._carregar,  variante="ghost",      icone="🔄").pack(side="right")

        self._carregar()

    def _carregar(self):
        try:
            anomalias = self.app.db.listar_anomalias_risco()
            contadores = {"critico": 0, "alto": 0, "medio": 0, "minimo": 0, "total": 0}
            dados = []
            for a in anomalias:
                risco = (a.get("grau_risco") or "-").lower()
                if "crit" in risco:   contadores["critico"] += 1
                elif "alto" in risco: contadores["alto"]    += 1
                elif "méd"  in risco or "med" in risco: contadores["medio"] += 1
                elif "mín"  in risco or "min" in risco: contadores["minimo"] += 1
                contadores["total"] += 1
                dados.append({
                    "ID":            a["id"],
                    "Título":        (a.get("titulo_topico") or "")[:50],
                    "Risco (auto)":  a.get("grau_risco")  or "-",
                    "GUT (auto)":    a.get("matriz_gut")   or "-",
                    "Risco (perito)": a.get("avaliacao_risco_usuario") or "-",
                    "GUT (perito)":  a.get("avaliacao_gut_usuario") or "-",
                })
            for k, v in contadores.items():
                self._kpi_vars[k].set(str(v))
            self._tb.popular(dados)
        except Exception as e:
            CPNotificacao.erro(self._root, f"Erro ao carregar GUT: {e}")

    def _editar(self):
        item = self._tb.item_selecionado()
        if not item:
            CPNotificacao.info(self._root, "Selecione uma anomalia.")
            return
        tid   = int(item["ID"])
        dlg   = tk.Toplevel(self._root)
        dlg.title(f"Editar GUT — Tópico {tid}")
        dlg.configure(bg=CORES["bg_secundario"])
        dlg.geometry("420x200")
        dlg.grab_set()

        tk.Label(dlg, text=f"Tópico: {item['Título']}", bg=CORES["bg_secundario"],
                 fg=CORES["texto_primario"], font=FONTES["corpo"],
                 wraplength=380, anchor="w").pack(fill="x", padx=16, pady=(12, 4))

        f_risco = tk.Frame(dlg, bg=CORES["bg_secundario"])
        f_risco.pack(fill="x", padx=16, pady=4)
        tk.Label(f_risco, text="Grau de Risco:", bg=CORES["bg_secundario"],
                 fg=CORES["texto_secundario"], font=FONTES["corpo"],
                 width=14, anchor="w").pack(side="left")
        e_risco = CPEntrada(f_risco, placeholder="Crítico / Grave / Médio / Mínimo")
        e_risco.pack(side="left", fill="x", expand=True)

        f_gut = tk.Frame(dlg, bg=CORES["bg_secundario"])
        f_gut.pack(fill="x", padx=16, pady=4)
        tk.Label(f_gut, text="GUT:", bg=CORES["bg_secundario"],
                 fg=CORES["texto_secundario"], font=FONTES["corpo"],
                 width=14, anchor="w").pack(side="left")
        e_gut = CPEntrada(f_gut, placeholder="G:5, U:4, T:3")
        e_gut.pack(side="left", fill="x", expand=True)

        def salvar():
            r = e_risco.get().strip()
            g = e_gut.get().strip()
            if r and g:
                try:
                    self.app.db.atualizar_risco_gut(tid, r, g)
                    dlg.destroy()
                    self._carregar()
                    CPNotificacao.sucesso(self._root, "GUT atualizado!")
                except Exception as ex:
                    CPNotificacao.erro(self._root, f"Erro: {ex}")

        CPBotao(dlg, "Salvar", salvar, variante="primario",
                icone="✅").pack(pady=12)

    def _adaptativo(self):
        item = self._tb.item_selecionado()
        tid  = int(item["ID"]) if item else None
        msg = (
            "O GUT Adaptativo é uma ferramenta interativa de terminal.\n\n"
            "Para usá-lo:\n"
            "1. Feche ou minimize esta janela\n"
            "2. No terminal, digite: gut_adaptativo\n"
        )
        if tid:
            msg += f"\nOu para avaliar o tópico {tid} diretamente:\n   gut_adaptativo (depois informe topico:{tid})"
        tk.messagebox.showinfo("GUT Adaptativo — Use o Terminal", msg)

    def _exportar(self):
        try:
            self.app._exportar_gut_excel()
            CPNotificacao.sucesso(self._root, "Exportado: Matriz_GUT_Pericial.xlsx")
        except Exception as e:
            CPNotificacao.erro(self._root, f"Erro exportar: {e}")


class PainelAnaliseIBAPE(_PainelBase):
    """Painel 📐 Análise Técnica IBAPE."""

    def __init__(self, parent, app, gui_root, **kw):
        super().__init__(parent, app, **kw)
        self._root    = gui_root
        self._conn_ib = None
        self._build()

    def _build(self):
        self._titulo(self, "📐  ANÁLISE TÉCNICA IBAPE")

        if not _ANALISE_IBAPE_OK:
            tk.Label(self, text="⚠️  analise_ibape.py não encontrado.\n"
                     "Copie o arquivo para a pasta do projeto.",
                     bg=CORES["bg_principal"], fg=CORES["accent_amarelo"],
                     font=FONTES["corpo"]).pack(pady=40)
            return

        # Filtros
        fil = tk.Frame(self, bg=CORES["bg_principal"])
        fil.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(fil, text="Grau:", bg=CORES["bg_principal"],
                 fg=CORES["texto_secundario"], font=FONTES["corpo"]).pack(side="left")
        self._filtro_grau = CPDropdown(
            fil, ["Todos", "Crítico", "Relevante", "Mínimo"], largura=12)
        self._filtro_grau.pack(side="left", padx=(4, 16))
        CPBotao(fil, "Nova Análise", self._nova_analise,
                variante="primario", icone="➕").pack(side="right")
        CPBotao(fil, "Atualizar", self._carregar,
                variante="ghost", icone="🔄").pack(side="right", padx=(0, 6))

        # Divisão esquerda / direita
        div = tk.Frame(self, bg=CORES["bg_principal"])
        div.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        div.grid_columnconfigure(0, weight=3)
        div.grid_columnconfigure(1, weight=2)
        div.grid_rowconfigure(0, weight=1)

        # Tabela
        self._tb = CPTabela(
            div,
            colunas=["Código", "Título", "Grau", "Status"],
            larguras={"Código": 80, "Título": 220, "Grau": 80, "Status": 70}
        )
        self._tb.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._tb.ao_selecionar(self._mostrar_detalhe)

        # Detalhe
        self._card_det = CPCard(div, titulo="Detalhe", padding=12)
        self._card_det.grid(row=0, column=1, sticky="nsew")
        self._lbl_det = tk.Text(
            self._card_det.inner,
            bg=CORES["bg_secundario"], fg=CORES["texto_primario"],
            font=FONTES["corpo"], wrap="word", relief="flat",
            height=15, state="disabled")
        self._lbl_det.pack(fill="both", expand=True)

        # Ações
        acs = tk.Frame(self, bg=CORES["bg_principal"])
        acs.pack(fill="x", padx=20, pady=(0, 12))
        CPBotao(acs, "Exportar DOCX", self._exportar,
                variante="secundario", icone="📄").pack(side="right", padx=(0,6))
        CPBotao(acs, "Atualizar", self._carregar,
                variante="ghost", icone="🔄").pack(side="right", padx=(0,6))

        self._carregar()

    def _get_conn(self):
        if self._conn_ib is None:
            try:
                from analise_ibape import inicializar_banco
                self._conn_ib = inicializar_banco()
            except Exception:
                self._conn_ib = None
        return self._conn_ib

    def _carregar(self):
        conn = self._get_conn()
        if not conn:
            return
        try:
            from analise_ibape import buscar_analises
            grau_f = self._filtro_grau.get() if hasattr(self, "_filtro_grau") else "Todos"
            grau   = None if grau_f == "Todos" else grau_f
            lista  = buscar_analises(conn, grau_risco=grau, limite=200)
            dados  = [{"Código": a.get("codigo_analise", ""),
                       "Título": (a.get("titulo") or a.get("titulo_anomalia") or "")[:50],
                       "Grau":   a.get("grau_risco", "-"),
                       "Status": a.get("status", "-"),
                       "_full":  a}
                      for a in lista]
            self._tb.popular(dados)
        except Exception as e:
            CPNotificacao.erro(self._root, f"Erro ao carregar IBAPE: {e}")

    def _mostrar_detalhe(self, item: dict):
        a = item.get("_full", item)
        gr   = str(a.get("grau_risco","")).lower()
        icon = "🔴" if "crit" in gr else ("🟡" if "méd" in gr or "med" in gr else "🟢")
        linhas = [
            f"📋  {a.get('codigo_analise', '')}  —  {a.get('titulo','')}",
            f"\n12.1  ANOMALIA",
            f"  Origem:     {a.get('anomalia_origem', '-')}",
            f"  Sistema:    {a.get('anomalia_sistema', '-')}",
            f"  Elemento:   {a.get('anomalia_elemento', '-')}",
            f"  Natureza:   {a.get('anomalia_natureza', '-')}",
            f"  Sintomas:   {(a.get('anomalia_sintomas') or '')[:120]}",
            f"  Descrição:  {(a.get('anomalia_descricao') or '')[:200]}",
            f"\n12.2  FALHA",
            f"  Origem:     {a.get('falha_origem', '-')}",
            f"  Nexo:       {(a.get('nexo_causal') or '')[:200]}",
            f"\n12.3  GRAU DE RISCO",
            f"  {icon}  {a.get('grau_risco', '-')}",
            f"  Prazo:      {a.get('prazo_intervencao', '-')}",
            f"  Ação:       {(a.get('acao_recomendada') or '')[:120]}",
            f"  GUT:        G={a.get('G_gut','-')} U={a.get('U_gut','-')} T={a.get('T_gut','-')} P={a.get('prioridade_gut','-')}",
        ]
        self._lbl_det.config(state="normal")
        self._lbl_det.delete("1.0", "end")
        self._lbl_det.insert("1.0", "\n".join(linhas))
        self._lbl_det.config(state="disabled")

    def _nova_analise(self):
        CPNotificacao.info(self._root,
            "Para criar uma análise completa:\n"
            "1. Feche ou minimize a janela\n"
            "2. No terminal, use o comando [analise_ibape]")

    def _exportar(self):
        conn = self._get_conn()
        if not conn:
            return
        item = self._tb.item_selecionado()
        if not item:
            CPNotificacao.info(self._root, "Selecione uma análise para exportar.")
            return
        a = item.get("_full", item)
        try:
            from analise_ibape import AnaliseIBAPE, inicializar_banco
            import json as _j
            conn_ib = inicializar_banco("analise_ibape.db")
            mod = AnaliseIBAPE(conn_ib, self.app.db)
            analise = dict(a)
            for key in ("normas_referencias","topicos_banco","flags_inconsistencia"):
                if analise.get(key) and isinstance(analise[key], str):
                    try: analise[key] = _j.loads(analise[key])
                    except: pass
            caminho = mod._exportar_docx_analise(analise)
            conn_ib.close()
            if caminho:
                CPNotificacao.sucesso(self._root, f"Exportado:\n{caminho}")
            else:
                CPNotificacao.erro(self._root, "Falha. pip install python-docx")
        except Exception as e:
            CPNotificacao.erro(self._root, f"Erro: {e}")


class PainelAnalytics(_PainelBase):
    """Painel 📈 Analytics e estatísticas de uso."""

    def __init__(self, parent, app, gui_root, **kw):
        super().__init__(parent, app, **kw)
        self._root = gui_root
        self._build()

    def _build(self):
        self._titulo(self, "📈  ANALYTICS")

        try:
            stats = self.app.db.estatisticas_banco()
        except Exception:
            stats = {}

        # KPI cards
        kpi_f = tk.Frame(self, bg=CORES["bg_principal"])
        kpi_f.pack(fill="x", padx=20, pady=(0, 16))
        for label, valor in [
            ("📄 Tópicos", str(stats.get("trechos", 0))),
            ("📚 Fontes ativas", str(stats.get("fontes_ativas", 0))),
            ("📐 Parâmetros", str(stats.get("parametros", 0))),
        ]:
            c = CPCard(kpi_f, titulo=label, padding=12)
            c.pack(side="left", padx=4, fill="y", expand=True)
            tk.Label(c.inner, text=valor,
                     bg=CORES["bg_secundario"], fg=CORES["texto_primario"],
                     font=FONTES["titulo"]).pack()

        # Consultas populares
        card = CPCard(self, titulo="🔥 Consultas Mais Frequentes", padding=12)
        card.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        tb = CPTabela(card.inner, colunas=["#", "Termo", "Consultas", "Última vez"],
                      larguras={"#": 30, "Termo": 260, "Consultas": 80, "Última vez": 110})
        tb.pack(fill="both", expand=True)
        try:
            top = self.app.db.top_consultas(15)
            dados = [{"#": i + 1, "Termo": t,
                      "Consultas": str(c), "Última vez": str(u)[:10]}
                     for i, (t, c, u) in enumerate(top)]
            tb.popular(dados)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  PAINEL 📸 ANÁLISE DE IMAGENS
# ══════════════════════════════════════════════════════════════════════════════

class PainelAnaliseImg(_PainelBase):
    """Painel 📸 Análise Integrada de Imagens de Patologia."""

    def __init__(self, parent, app, gui_root, **kw):
        super().__init__(parent, app, **kw)
        self._root = gui_root
        self._build()

    def _build(self):
        self._titulo(self, "📸  ANÁLISE INTEGRADA DE IMAGENS DE PATOLOGIA")

        if not _ANALISE_IMAGEM_OK:
            tk.Label(self,
                text="⚠️  analise_imagem.py não encontrado.\n"
                     "Copie o arquivo para a pasta do projeto.",
                bg=CORES["bg_principal"], fg=CORES["accent_amarelo"],
                font=FONTES["corpo"]).pack(pady=40)
            return

        # Cards de orientação
        info = tk.Frame(self, bg=CORES["bg_principal"])
        info.pack(fill="x", padx=20, pady=(0, 12))
        for ico, txt in [
            ("1️⃣", "Coloque imagens em\nimg_patologias_entrada/"),
            ("2️⃣", "Use [analise_img]\nno terminal"),
            ("3️⃣", "GUT + IBAPE\npor imagem"),
            ("4️⃣", "Exporte DOCX\ncompleto do laudo"),
        ]:
            card = CPCard(info, titulo=ico, padding=10)
            card.pack(side="left", padx=4, fill="y", expand=True)
            tk.Label(card.inner, text=txt,
                     bg=CORES["bg_secundario"], fg=CORES["texto_secundario"],
                     font=FONTES["corpo"], justify="center").pack()

        # Status da pasta
        self._lbl_pasta = tk.Label(
            self, bg=CORES["bg_principal"],
            fg=CORES["texto_secundario"], font=FONTES["corpo"], anchor="w")
        self._lbl_pasta.pack(fill="x", padx=20, pady=(0, 8))
        self._atualizar_pasta()

        # Tabela de laudos
        card_laudos = CPCard(self, titulo="📋 Laudos em Andamento", padding=12)
        card_laudos.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        self._tb_laudos = CPTabela(
            card_laudos.inner,
            colunas=["ID", "Laudo", "Imagens", "Última edição", "Status"],
            larguras={"ID": 40, "Laudo": 220, "Imagens": 70,
                      "Última edição": 110, "Status": 70},
        )
        self._tb_laudos.pack(fill="both", expand=True)
        self._carregar_laudos()

        # Ações
        acs = tk.Frame(self, bg=CORES["bg_principal"])
        acs.pack(fill="x", padx=20, pady=(0, 12))
        CPBotao(acs, "Abrir pasta entrada", self._abrir_pasta,
                variante="ghost", icone="📂").pack(side="left", padx=(0, 6))
        CPBotao(acs, "Atualizar", self._atualizar,
                variante="ghost", icone="🔄").pack(side="left", padx=(0, 6))
        CPBotao(acs, "Exportar DOCX do laudo",
                self._exportar_laudo, variante="secundario",
                icone="📥").pack(side="left", padx=(0, 6))
        CPBotao(acs, "ℹ️ Como usar", self._orientar,
                variante="ghost").pack(side="right")

    def _atualizar_pasta(self):
        try:
            from analise_imagem import PASTA_ENTRADA, PASTA_SAIDA
            ext_ok = {".jpg",".jpeg",".png",".bmp",".tif",".tiff",".webp"}
            n_e = sum(1 for f in os.listdir(PASTA_ENTRADA)
                      if os.path.splitext(f)[1].lower() in ext_ok
                      ) if os.path.exists(PASTA_ENTRADA) else 0
            n_s = len(os.listdir(PASTA_SAIDA)) if os.path.exists(PASTA_SAIDA) else 0
            self._lbl_pasta.config(
                text=f"📂 Entrada: {n_e} imagem(ns) aguardando  •  "
                     f"Processadas: {n_s}")
        except Exception as e:
            try: self._lbl_pasta.config(text=f"Pasta: {e}")
            except: pass

    def _atualizar(self):
        self._atualizar_pasta()
        self._carregar_laudos()

    def _carregar_laudos(self):
        try:
            import sqlite3 as _sq
            DB = "laudos_imagem.db"
            if not os.path.exists(DB):
                return
            conn = _sq.connect(DB); conn.row_factory = _sq.Row
            laudos = conn.execute(
                "SELECT l.id, l.nome_laudo, l.status, l.data_edicao, "
                "COUNT(i.id) as n_img FROM laudos_img l "
                "LEFT JOIN imagens_laudo_img i ON i.laudo_id=l.id "
                "GROUP BY l.id ORDER BY l.data_edicao DESC LIMIT 50"
            ).fetchall()
            conn.close()
            dados = [{"ID": r["id"], "Laudo": r["nome_laudo"][:40],
                      "Imagens": r["n_img"],
                      "Última edição": str(r["data_edicao"])[:16],
                      "Status": r["status"]} for r in laudos]
            self._tb_laudos.popular(dados)
        except Exception:
            pass

    def _abrir_pasta(self):
        try:
            import subprocess, sys
            pasta = os.path.abspath("img_patologias_entrada")
            os.makedirs(pasta, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(pasta)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", pasta])
            else:
                subprocess.Popen(["xdg-open", pasta])
        except Exception as e:
            CPNotificacao.erro(self._root, f"Erro ao abrir pasta: {e}")

    def _exportar_laudo(self):
        item = self._tb_laudos.item_selecionado()
        if not item:
            CPNotificacao.info(self._root, "Selecione um laudo na tabela.")
            return
        laudo_id = int(item["ID"])
        try:
            import sqlite3 as _sq, json as _j
            conn = _sq.connect("laudos_imagem.db"); conn.row_factory = _sq.Row
            _row = conn.execute(
                "SELECT * FROM laudos_img WHERE id=?", (laudo_id,)).fetchone()
            if not _row:
                conn.close()
                CPNotificacao.erro(self._root, "Laudo não encontrado no banco.")
                return
            laudo = dict(_row)
            imagens = [dict(r) for r in conn.execute(
                "SELECT * FROM imagens_laudo_img WHERE laudo_id=? ORDER BY id",
                (laudo_id,)).fetchall()]
            conn.close()
            if not imagens:
                CPNotificacao.info(self._root, "Este laudo não tem imagens.")
                return
            from analise_imagem import AnalisadorImagem
            analisador = AnalisadorImagem(self.app.db, self.app.ai)
            caminho = analisador._exportar_docx_laudo_completo(laudo, imagens)
            if caminho:
                CPNotificacao.sucesso(self._root, f"DOCX exportado:\n{caminho}")
            else:
                CPNotificacao.erro(self._root, "Falha. pip install python-docx")
        except Exception as e:
            CPNotificacao.erro(self._root, f"Erro: {e}")

    def _orientar(self):
        tk.messagebox.showinfo("Como usar [analise_img]",
            "1. Coloque imagens em img_patologias_entrada/\n"
            "2. Feche ou minimize esta janela\n"
            "3. No terminal, digite: analise_img\n\n"
            "O fluxo abrirá:\n"
            "  • Seleção/criação do laudo\n"
            "  • GUT Adaptativo por imagem\n"
            "  • Análise IBAPE por imagem\n"
            "  • Exportação DOCX do laudo")


# ══════════════════════════════════════════════════════════════════════════════
#  CLASSE PRINCIPAL DA GUI
# ══════════════════════════════════════════════════════════════════════════════

class CerebroPericialGUI:
    """
    Interface gráfica moderna do Cérebro de Engenharia Diagnóstica v2.0.
    Dark theme com sidebar de navegação, painéis modulares e componentes CP*.

    Exemplo de uso:
        root = tk.Tk()
        gui  = CerebroPericialGUI(root, app_cerebro)
        gui.iniciar()
    """
    _PAGINAS = [
        ("🔍  Consultar",       "consultar"),
        ("📚  Fontes",          "fontes"),
        ("📊  Matriz GUT",      "gut"),
        ("📐  Análise IBAPE",   "ibape"),
        ("📸  Análise IMG",     "analise_img"),
        ("📈  Analytics",       "analytics"),
    ]

    def __init__(self, root: tk.Tk, app: "CerebroEngenharia"):
        self.root        = root
        self.app         = app
        self._pagina_ativa: str = ""
        self._btns_nav:  dict   = {}
        self._painel_ativo = None
        self._tokens_usados = 0
        self._configurar_janela()
        self._aplicar_tema_ttk()
        self._construir_layout()
        self._atualizar_status_ia()
        # Defer to ensure all widgets are fully rendered before populating
        self.root.after(80, lambda: self.navegar("consultar"))

    def _configurar_janela(self) -> None:
        self.root.title("🧠  Cérebro de Engenharia Diagnóstica  v2.0")
        self.root.geometry("1200x800")
        self.root.minsize(900, 600)
        self.root.configure(bg=CORES["bg_principal"])
        self.root.protocol("WM_DELETE_WINDOW", self.root.quit)

    def _aplicar_tema_ttk(self) -> None:
        style = ttk.Style()
        for _t in ("clam", "alt", "default"):
            try:
                style.theme_use(_t)
                break
            except Exception:
                pass

    def _construir_layout(self) -> None:
        # ── Topbar ────────────────────────────────────────────────────────────
        self._topbar = tk.Frame(self.root, bg=CORES["bg_secundario"], height=52)
        self._topbar.pack(fill="x", side="top")
        self._topbar.pack_propagate(False)

        tk.Label(self._topbar, text="🧠  Cérebro Pericial  v2.0",
                 bg=CORES["bg_secundario"], fg=CORES["texto_primario"],
                 font=FONTES["subtitulo"]).pack(side="left", padx=16)

        # Indicador de IA
        self._ia_canvas = tk.Canvas(self._topbar, width=14, height=14,
                                     bg=CORES["bg_secundario"], highlightthickness=0)
        self._ia_oval = self._ia_canvas.create_oval(2, 2, 12, 12,
                                                      fill=CORES["texto_muted"])
        self._ia_canvas.pack(side="right", padx=(0, 4))
        self._lbl_ia = tk.Label(self._topbar, text="IA: —",
                                 bg=CORES["bg_secundario"],
                                 fg=CORES["texto_muted"],
                                 font=FONTES["pequena"])
        self._lbl_ia.pack(side="right", padx=(0, 16))

        tk.Frame(self._topbar, bg=CORES["separador"], width=1).pack(
            side="right", fill="y", pady=8)

        # Separador topbar
        # ── Statusbar — packed BEFORE corpo para reservar espaço ──────────────
        tk.Frame(self.root, bg=CORES["separador"], height=1).pack(
            fill="x", side="bottom")
        self._statusbar = tk.Frame(self.root, bg=CORES["bg_secundario"], height=30)
        self._statusbar.pack(fill="x", side="bottom")
        self._statusbar.pack_propagate(False)
        self._lbl_status = tk.Label(
            self._statusbar, text="Sistema pronto.",
            bg=CORES["bg_secundario"], fg=CORES["texto_secundario"],
            font=FONTES["pequena"], anchor="w")
        self._lbl_status.pack(side="left", padx=12)
        tk.Label(
            self._statusbar,
            text="Desenvolvido por  Eng. Thomaz Rodrigo Silverol",
            bg=CORES["bg_secundario"], fg=CORES["texto_muted"],
            font=FONTES["pequena"],
        ).pack(side="right", padx=16)
        tk.Frame(self._statusbar, bg=CORES["separador"], width=1).pack(
            side="right", fill="y", pady=4)
        tk.Label(
            self._statusbar,
            text="Cérebro de Engenharia Diagnóstica  v2.0",
            bg=CORES["bg_secundario"], fg=CORES["texto_muted"],
            font=FONTES["pequena"],
        ).pack(side="right", padx=12)

        tk.Frame(self.root, bg=CORES["separador"], height=1).pack(fill="x")

        # ── Corpo (sidebar + área principal) ────────────────────────────────
        self._corpo = tk.Frame(self.root, bg=CORES["bg_principal"])
        self._corpo.pack(fill="both", expand=True)

        # Sidebar
        self._sidebar = tk.Frame(self._corpo, bg=CORES["bg_secundario"],
                                  width=210)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # Logo / título sidebar
        tk.Label(self._sidebar, text="🧠 MENU",
                 bg=CORES["bg_secundario"], fg=CORES["texto_muted"],
                 font=FONTES["pequena"], anchor="w",
                 padx=16).pack(fill="x", pady=(12, 0))
        tk.Frame(self._sidebar, bg=CORES["separador"],
                 height=1).pack(fill="x", pady=(4, 4))

        for texto, pagina in self._PAGINAS:
            btn = SidebarBtn(self._sidebar, texto,
                             cmd=lambda p=pagina: self.navegar(p))
            btn.pack(fill="x")
            self._btns_nav[pagina] = btn

        tk.Frame(self._sidebar, bg=CORES["separador"],
                 height=1).pack(fill="x", pady=(4, 0))

        # Separador sidebar
        tk.Frame(self._corpo, bg=CORES["separador"], width=1).pack(
            side="left", fill="y")

        # Área principal
        self._area = tk.Frame(self._corpo, bg=CORES["bg_principal"])
        self._area.pack(side="left", fill="both", expand=True)

    def navegar(self, pagina: str) -> None:
        """Navega para um painel. Limpa área e instancia o painel destino."""
        if self._pagina_ativa == pagina:
            return

        # Desativar botão anterior
        if self._pagina_ativa and self._pagina_ativa in self._btns_nav:
            self._btns_nav[self._pagina_ativa].desativar()

        # Destruir painel atual (fechar conexões abertas antes de destruir)
        if self._painel_ativo:
            try:
                conn_ib = getattr(self._painel_ativo, "_conn_ib", None)
                if conn_ib:
                    try:
                        conn_ib.close()
                    except Exception:
                        pass
                    self._painel_ativo._conn_ib = None
            except Exception:
                pass
            try:
                self._painel_ativo.destroy()
            except Exception:
                pass

        # Ativar novo botão
        self._pagina_ativa = pagina
        if pagina in self._btns_nav:
            self._btns_nav[pagina].ativar()

        # Instanciar novo painel
        try:
            if pagina == "consultar":
                self._painel_ativo = PainelConsultar(
                    self._area, self.app, self.root)
            elif pagina == "fontes":
                self._painel_ativo = PainelFontes(
                    self._area, self.app, self.root)
            elif pagina == "gut":
                self._painel_ativo = PainelGUT(
                    self._area, self.app, self.root)
            elif pagina == "ibape":
                self._painel_ativo = PainelAnaliseIBAPE(
                    self._area, self.app, self.root)
            elif pagina == "analise_img":
                self._painel_ativo = PainelAnaliseImg(self._area, self.app, self.root)
            elif pagina == "analytics":
                self._painel_ativo = PainelAnalytics(self._area, self.app, self.root)
            else:
                return

            self._painel_ativo.pack(fill="both", expand=True)
            self.atualizar_statusbar(f"Módulo: {pagina.capitalize()}")
        except Exception as e:
            import logging, traceback
            logging.getLogger(__name__).error(f"Erro ao navegar para {pagina}: {e}")
            traceback.print_exc()
            self.atualizar_statusbar(f"Erro: {e}", "erro")
            try:
                for w in self._area.winfo_children():
                    w.destroy()
                tk.Label(self._area,
                    text=f"⚠️  Erro ao carregar '{pagina}':\n\n{e}\n\nVeja o terminal para detalhes.",
                    bg=CORES["bg_principal"], fg=CORES["accent_vermelho"],
                    font=FONTES["corpo"], justify="left").pack(anchor="nw", padx=24, pady=24)
            except Exception:
                pass

    def _atualizar_status_ia(self) -> None:
        """Verifica IA e atualiza indicador. Reagenda a cada 30s."""
        try:
            ok = getattr(self.app, "ai", None) and self.app.ai.ia_disponivel
        except Exception:
            ok = False
        cor  = CORES["accent_verde"]   if ok else CORES["accent_vermelho"]
        txt  = "IA: Online"            if ok else "IA: Offline"
        ctxt = CORES["accent_verde"]   if ok else CORES["texto_muted"]
        self._ia_canvas.itemconfig(self._ia_oval, fill=cor)
        self._lbl_ia.config(text=txt, fg=ctxt)
        self.root.after(30_000, self._atualizar_status_ia)

    def atualizar_statusbar(self, msg: str, tipo: str = "info") -> None:
        """Atualiza a mensagem na barra de status inferior."""
        cor = {
            "info":  CORES["texto_secundario"],
            "sucesso": CORES["accent_verde"],
            "erro":  CORES["accent_vermelho"],
        }.get(tipo, CORES["texto_secundario"])
        try:
            self._lbl_status.config(text=msg, fg=cor)
        except Exception:
            pass

    def iniciar(self) -> None:
        """Inicia o loop principal do Tkinter."""
        self.root.mainloop()

    def _mensagem_minimo_palavras(self) -> str:
        return (
            "  ⚠️  A pesquisa precisa de ao menos 3 palavras significativas.\n\n"
            "  Exemplos válidos:\n"
            "    • guarda-corpo altura mínima\n"
            "    • infiltração fachada critério normativo\n"
            "    • estanqueidade lâmina d'água NBR\n"
            "    • recalque fundação tolerância\n\n"
            "  Use aspas para busca exata: \"fissura estrutural\""
        )


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def _exibir_status_sistema(app: "CerebroEngenharia") -> None:
    """
    Comando [status] — Diagnóstico em tempo real do sistema.
    Exibe: IA, cache de embeddings, sessão GUT pendente, banco.
    Ref: Seção 8 do Prompt de Arquitetura Resiliente Offline-First v1.0.
    """
    sep = "═" * 62
    print(f"\n{sep}")
    print("  🔍 STATUS DO SISTEMA — Cérebro de Engenharia Diagnóstica")
    print(sep)

    # ── IA ────────────────────────────────────────────────────────────
    monitor = getattr(app, "_monitor", None)
    if monitor is not None:
        status = monitor.verificar_saude(forcar=True)
        icone  = "🟢" if status["disponivel"] else "🔴"
        print(f"\n  IA (Gemini):    {icone} {status['modo'].upper()}")
        if not status["disponivel"]:
            print(f"  Motivo:         {status['motivo']}")
            print(f"  Impacto:        Busca vetorial desativada | GUT modo autônomo desativado")
            print(f"  Ação:           Verificar GEMINI_API_KEY no arquivo .env")
    else:
        print(f"\n  IA (Gemini):    {'🟢 Configurada' if app._ia_disponivel else '🔴 Não configurada'}")

    # ── Cache de Embeddings ───────────────────────────────────────────
    cache = getattr(app.ai, "_embedding_cache", None)
    if cache is not None:
        info = cache.obter_estatisticas()
        print(f"\n  Cache L1 (mem): {info['l1_size']} entrada(s)")
        print(f"  Cache L2 (DB):  {info['total']} entrada(s) | Hits hoje: {info['hits_hoje']}")
    else:
        print("\n  Cache Embeddings: desativado (ai_health_monitor.py não encontrado)")

    # ── Sessão GUT Pendente ───────────────────────────────────────────
    try:
        import sqlite3
        conn_st = app.db.get_connection()
        row_gut = conn_st.execute("""
            SELECT descricao, etapa_atual, timestamp
            FROM gut_sessao_parcial
            WHERE expirado = 0
            ORDER BY timestamp DESC LIMIT 1
        """).fetchone()
        conn_st.close()
        if row_gut:
            print(f"\n  ⚠️  GUT pendente: {row_gut[0][:50]}")
            print(f"     Etapa: {row_gut[1]} | Data: {row_gut[2][:16]}")
            print(f"     Digite [gut_adaptativo] para retomar.")
        else:
            print("\n  GUT Pendente:   nenhum")
    except Exception:
        print("\n  GUT Pendente:   (tabela não encontrada — executar migração)")

    # ── Banco ─────────────────────────────────────────────────────────
    try:
        stats = app.db.estatisticas_banco()
        print(f"\n  Banco:          {stats['fontes_ativas']} fonte(s) ativas")
        print(f"  Trechos:        {stats['trechos']} | Com embedding: {stats['com_embedding']}")
        sem_emb = stats['trechos'] - stats['com_embedding']
        if sem_emb > 0:
            print(f"  ⚠️  {sem_emb} trecho(s) sem embedding — execute verify_embeddings.py")
    except Exception as exc:
        print(f"\n  Banco: erro ao ler estatísticas: {exc}")

    print(f"\n{sep}\n")


def _cmd_reprocessar(app, entrada: str) -> None:
    """Comando [reprocessar]: mostra status e executa Fase 2 (offline + mistral:7b)."""
    if not _REPROCESSAMENTO_OK:
        print("\n  orchestrator.py ou quality_manager.py nao encontrado.")
        exibir_menu()
        return

    import sqlite3 as _sq

    def _exibir_status_banco():
        """Exibe painel de status completo: qualidade, confiança e pendências."""
        print("\n" + "=" * 65)
        print("  STATUS DO BANCO")
        print("=" * 65)

        conn_s = _sq.connect(app.db.db_path)
        try:
            # Topicos totais
            total_top = conn_s.execute("SELECT COUNT(*) FROM topicos").fetchone()[0]
            print(f"\n  Topicos indexados: {total_top}")

            # Distribuição por status de processamento
            rows_status = conn_s.execute(
                "SELECT status_processamento, COUNT(*) FROM topicos "
                "GROUP BY status_processamento ORDER BY COUNT(*) DESC"
            ).fetchall()
            if rows_status:
                print("\n  Por status:")
                for st, cnt in rows_status:
                    bar = "#" * min(30, cnt // max(1, total_top // 30))
                    print(f"    {(st or 'nao_iniciado'):<22} {cnt:>5}  {bar}")

            # laudos_estruturado — confiança Fase 1
            rows_conf = conn_s.execute(
                "SELECT confianca_extracao, COUNT(*) FROM laudos_estruturado "
                "GROUP BY confianca_extracao ORDER BY confianca_extracao"
            ).fetchall()
            total_est = sum(r[1] for r in rows_conf)
            if total_est:
                print(f"\n  Extracao estruturada (Fase 1 IA): {total_est} topico(s)")
                for conf, cnt in rows_conf:
                    print(f"    Confianca {conf or 'BAIXA':<6}: {cnt:>4}")

            # Pendentes para Fase 2 IA
            pend_f2 = conn_s.execute(
                "SELECT COUNT(*) FROM laudos_estruturado "
                "WHERE processado_fase1=1 AND processado_fase2=0"
            ).fetchone()[0]
            print(f"\n  Pendentes para Fase 2 (mistral:7b): {pend_f2} topico(s)")

            # Tópicos sem Fase 1 IA (laudos_estruturado vazio para esses tópicos)
            sem_fase1 = conn_s.execute(
                "SELECT COUNT(*) FROM topicos t "
                "WHERE t.texto_original IS NOT NULL "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM laudos_estruturado le "
                "  WHERE le.topico_id = t.id AND le.processado_fase1 = 1"
                ")"
            ).fetchone()[0]
            if sem_fase1 > 0:
                print(f"  Sem Fase 1 IA (serao processados no proximo [reprocessar]): {sem_fase1} topico(s)")

            # Score de risco já calculado
            rows_risco = conn_s.execute(
                "SELECT score_risco, COUNT(*) FROM laudos_estruturado "
                "WHERE score_risco != '' GROUP BY score_risco ORDER BY score_risco"
            ).fetchall()
            if rows_risco:
                print("\n  Score de risco calculado:")
                for risco, cnt in rows_risco:
                    print(f"    {risco:<8}: {cnt}")

            # Normas indexadas
            n_normas = conn_s.execute(
                "SELECT COUNT(*) FROM contextos_normativos"
            ).fetchone()[0]
            print(f"\n  Normas em contextos_normativos: {n_normas}")

        except Exception as e:
            print(f"  Erro ao calcular status: {e}")
        finally:
            conn_s.close()

        # Score geral do banco
        try:
            qm = QualityManager(db_path=app.db.db_path)
            print(f"\n  Score geral do banco: {qm.score_banco()*100:.1f}%")
        except Exception:
            pass

        print("=" * 65)

    sub = entrada.replace('reprocessar', '').strip().lower()

    # ── [reprocessar status] ──────────────────────────────────────────────────
    if sub == 'status':
        _exibir_status_banco()
        exibir_menu()
        return

    # ── [reprocessar] — mostra status e executa Fase 2 ───────────────────────
    _exibir_status_banco()

    print("\n  O que sera feito:")
    print("    Fase 2 offline : preenche lacunas e expande sinonimos")
    print("    Fase 2 IA      : mistral:7b refina confianca < ALTA")
    print("                     detecta causa raiz, score de risco e nexo causal")
    print("    (itens ja com processado_fase2=1 sao ignorados)")

    confirma = input("\n  Iniciar reprocessamento? [S/N]: ").strip().upper()
    if confirma != 'S':
        print("  Cancelado.")
        exibir_menu()
        return

    api_key = os.getenv("GEMINI_API_KEY", "")
    orq = OrquestradorReprocessamento(db_path=app.db.db_path, api_key=api_key)

    # _fase2() agora inclui: offline gap-fill + mistral:7b refinement
    orq._fase2()

    # Mostrar status atualizado ao final
    print("\n  Reprocessamento concluido.")
    _exibir_status_banco()
    exibir_menu()


def main():
    try:
        app   = CerebroEngenharia()
        stats = app.db.estatisticas_banco()
        exibir_boas_vindas(stats)

        # ── Status da IA na inicialização (uma única vez) ─────────────────
        if app._monitor is not None:
            app._monitor.exibir_status_startup()
        elif app._ia_disponivel:
            print("  Gemini: configurado")
        else:
            # Verifica Ollama mesmo sem monitor de saúde
            try:
                from ollama_engine import OllamaEngine as _OllamaEngine
                _ol = _OllamaEngine()
                if _ol.disponivel:
                    print(f"  Gemini: sem API key (opcional)")
                    print(f"  Ollama: llama={_ol.modelo_rapido} | mistral={_ol.modelo_qualidade}")
                else:
                    print("  IA: indisponivel (Gemini sem API key, Ollama nao encontrado)")
                    print("     Todas as funcoes offline continuam ativas.")
            except Exception:
                print("  IA: indisponivel — funcoes offline ativas.")

        exibir_menu()

        while True:
            entrada = input("\n📝 Comando ou consulta:\n> ").strip()
            if not entrada: continue
            cmd = entrada.lower()

            if cmd == 'sair':
                print("\n  👋 Encerrando. Banco salvo. Até logo!"); break

            elif cmd in ('ver fontes', 'fontes ver', 'ver_fontes'):
                print(app._renderizar_ultimas_fontes())
                exibir_menu()

            elif cmd == 'status':
                _exibir_status_sistema(app)
                exibir_menu()

            elif cmd in ('analise_img', 'analise_imagem'):
                if not _ANALISE_IMAGEM_OK:
                    print("\n  ⚠️  analise_imagem.py não encontrado.")
                    print("     Copie o arquivo para a pasta do projeto e tente novamente.")
                else:
                    try:
                        analisador = AnalisadorImagem(
                            db_manager=app.db,
                            ai_engine=app.ai,
                        )
                        analisador.processar_lote()
                    except Exception as e:
                        import traceback
                        print(f"\n  ❌ Erro no módulo de análise de imagens: {e}")
                        traceback.print_exc()
                exibir_menu()

            elif cmd == 'gui':
                try:
                    app.abrir_gui()
                except Exception as e:
                    print(f"\n  ❌ Interface gráfica indisponível: {e}")
                    print("  ℹ️  Execute em ambiente com display gráfico (Windows/macOS/X11).")
                exibir_menu()

            elif cmd == 'exportar':
                app.exportar_excel(); exibir_menu()

            elif cmd == 'populares':
                app.exibir_consultas_populares(10); exibir_menu()

            elif cmd == 'fontes':
                app.gerenciar_fontes(); exibir_menu()

            elif cmd == 'gut':
                app.gerenciar_gut(); exibir_menu()

            elif cmd in ('gut_adaptativo', 'gut_a'):
                app.gut_adaptativo_cli(); exibir_menu()

            elif cmd in ('analise_ibape', 'ibape'):
                if not _ANALISE_IBAPE_OK:
                    print("\n  ⚠️  analise_ibape.py não encontrado.")
                    print("     Copie o arquivo para a pasta do projeto e tente novamente.")
                else:
                    analise_ibape_cli(conn_principal=app.db)
                exibir_menu()

            elif cmd == 'reimportar':
                # ── Reextrai arquivos já processados ou com erro ──────────────
                import shutil as _shutil, sqlite3 as _sq2
                pares = [
                    (PASTAS['pdf']['out'],  PASTAS['pdf']['in'],  '.pdf'),
                    (PASTAS['doc']['out'],  PASTAS['doc']['in'],  '.docx'),
                    ('doc_erros',           PASTAS['doc']['in'],  '.docx'),
                    ('pdf_erros',           PASTAS['pdf']['in'],  '.pdf'),
                ]
                movidos = []
                for pasta_out, pasta_in, ext in pares:
                    if not os.path.isdir(pasta_out):
                        continue
                    for arq in os.listdir(pasta_out):
                        if arq.lower().endswith(ext):
                            src = os.path.join(pasta_out, arq)
                            dst = os.path.join(pasta_in, arq)
                            try:
                                _shutil.move(src, dst)
                                movidos.append(arq)
                            except Exception as _me:
                                print(f"  Erro ao mover {arq}: {_me}")

                if not movidos:
                    print("\n  Nenhum arquivo encontrado em pastas processadas.")
                else:
                    print(f"\n  {len(movidos)} arquivo(s) movido(s) para reprocessamento:")
                    for m in movidos:
                        print(f"    {m}")
                    # Remove tópicos e laudos dos arquivos que serão reprocessados
                    conn_ri = _sq2.connect(app.db.db_path)
                    try:
                        for arq in movidos:
                            lid = conn_ri.execute(
                                "SELECT id FROM laudos WHERE nome_arquivo=?", (arq,)
                            ).fetchone()
                            if lid:
                                conn_ri.execute(
                                    "DELETE FROM laudos_estruturado WHERE laudo_id=?", (lid[0],)
                                )
                                conn_ri.execute(
                                    "DELETE FROM topicos WHERE laudo_id=?", (lid[0],)
                                )
                                conn_ri.execute(
                                    "DELETE FROM laudos WHERE id=?", (lid[0],)
                                )
                                print(f"    Banco limpo para: {arq}")
                        conn_ri.commit()
                    finally:
                        conn_ri.close()
                    app.db._auto_sync_fts()
                    print("\n  Execute [arquivos] para reindexar com a nova extração.")
                exibir_menu()

            elif cmd == 'arquivos':
                # ── FASE 1: extração offline ──────────────────────────────────
                app.processor.processar_lote(app.interagir_patologia)

                # ── FASE 1 IA: enriquecimento com llama3.2:3b ─────────────────
                if _REPROCESSAMENTO_OK:
                    try:
                        from ia_integrator import IntegradorIA
                        integrador = IntegradorIA(
                            api_key=os.getenv("GEMINI_API_KEY", ""),
                            db_path=app.db.db_path,
                        )
                        if integrador.is_available():
                            print("\n  Fase 1 IA (llama3.2): buscando topicos pendentes...")
                            # Enriquecer laudos recém inseridos (sem fase_1_ia ainda)
                            import sqlite3 as _sq
                            conn_tmp = _sq.connect(app.db.db_path)
                            # Busca laudos que têm tópicos ainda não processados pelo llama
                            # (verifica laudos_estruturado, independente do status legado)
                            try:
                                laudos_novos = [r[0] for r in conn_tmp.execute(
                                    "SELECT DISTINCT t.laudo_id FROM topicos t "
                                    "WHERE t.texto_original IS NOT NULL "
                                    "AND length(t.texto_original) > 30 "
                                    "AND NOT EXISTS ("
                                    "  SELECT 1 FROM laudos_estruturado le "
                                    "  WHERE le.topico_id = t.id AND le.processado_fase1 = 1"
                                    ") "
                                    "ORDER BY t.laudo_id DESC LIMIT 30"
                                ).fetchall()]
                            except Exception:
                                laudos_novos = [r[0] for r in conn_tmp.execute(
                                    "SELECT DISTINCT laudo_id FROM topicos "
                                    "WHERE texto_original IS NOT NULL "
                                    "AND length(texto_original) > 30 "
                                    "ORDER BY laudo_id DESC LIMIT 30"
                                ).fetchall()]
                            conn_tmp.close()

                            if not laudos_novos:
                                print("  Nenhum topico pendente encontrado para Fase 1 IA.")
                                print("  (todos ja foram processados ou banco vazio)")
                            else:
                                print(f"  {len(laudos_novos)} laudo(s) com topicos pendentes para llama.")

                            # Mapa laudo_id → nome_arquivo para exibição
                            try:
                                conn_nomes = _sq.connect(app.db.db_path)
                                nomes_laudos = {
                                    r[0]: r[1] for r in conn_nomes.execute(
                                        "SELECT id, nome_arquivo FROM laudos"
                                    ).fetchall()
                                }
                                conn_nomes.close()
                            except Exception:
                                nomes_laudos = {}

                            total_enr    = 0
                            total_irrel  = 0
                            total_rev    = 0
                            total_falhas = 0
                            prompts_rev  = []

                            def _contar_pendentes(db_path, lid):
                                try:
                                    _c = _sq.connect(db_path)
                                    n = _c.execute(
                                        "SELECT COUNT(*) FROM topicos t "
                                        "WHERE t.laudo_id = ? "
                                        "AND t.texto_original IS NOT NULL "
                                        "AND length(t.texto_original) > 30 "
                                        "AND NOT EXISTS ("
                                        "  SELECT 1 FROM laudos_estruturado le "
                                        "  WHERE le.topico_id = t.id AND le.processado_fase1 = 1"
                                        ")", (lid,)
                                    ).fetchone()[0]
                                    _c.close()
                                    return n
                                except Exception:
                                    return 0

                            for n_lid, lid in enumerate(laudos_novos, 1):
                                nome_arq  = nomes_laudos.get(lid, f"laudo_id={lid}")
                                pendentes = _contar_pendentes(app.db.db_path, lid)
                                print(f"\n  ═══ Arquivo {n_lid}/{len(laudos_novos)}: {nome_arq[:60]}")
                                print(f"      Tópicos pendentes: {pendentes}")
                                tipo_doc  = "norma_abnt" if nome_arq.lower().endswith(".pdf") else "laudo_judicial"

                                enr_lid = irrel_lid = rev_lid = falhas_lid = 0
                                rodada  = 0
                                while True:
                                    rodada += 1
                                    r = integrador.processar_fase1({"tipo": tipo_doc}, lid)
                                    enr_r    = r.get("enriquecidos", 0)
                                    irrel_r  = r.get("irrelevantes", 0)
                                    rev_r    = r.get("revisao", 0)
                                    falhas_r = r.get("falhas_ia", 0)
                                    proc_r   = enr_r + irrel_r + rev_r + falhas_r

                                    enr_lid    += enr_r
                                    irrel_lid  += irrel_r
                                    rev_lid    += rev_r
                                    falhas_lid += falhas_r
                                    prompts_rev.extend(r.get("prompts_refinamento", []))

                                    restantes = _contar_pendentes(app.db.db_path, lid)
                                    print(f"      → Rodada {rodada}: {proc_r} processados | {restantes} restantes")

                                    if proc_r == 0 or restantes == 0:
                                        break

                                total_enr    += enr_lid
                                total_irrel  += irrel_lid
                                total_rev    += rev_lid
                                total_falhas += falhas_lid
                                print(f"      Arquivo concluído: {enr_lid} aprovados | {irrel_lid} filtrados | {rev_lid} revisão")

                            # Resumo da extração estruturada
                            conn_tmp2 = _sq.connect(app.db.db_path)
                            rows_est = conn_tmp2.execute(
                                "SELECT confianca_extracao, COUNT(*) "
                                "FROM laudos_estruturado "
                                "GROUP BY confianca_extracao"
                            ).fetchall()
                            conn_tmp2.close()

                            print(f"\n  ─── Fase 1 IA (llama3.2) ───────────────────────────")
                            print(f"  Aprovados (relevantes OK):   {total_enr}")
                            print(f"  Aguardando refinamento:      {total_rev}")
                            print(f"  Filtrados (irrelevantes):    {total_irrel}")
                            if total_falhas:
                                print(f"  Falhas IA:                   {total_falhas}")
                            if rows_est:
                                print(f"  Distribuição de confiança:")
                                for conf, qtd in rows_est:
                                    print(f"    {conf or 'BAIXA':<8}: {qtd} tópico(s)")
                            if prompts_rev:
                                print(f"\n  Tópicos para refinamento (use [reprocessar]):")
                                for p in prompts_rev[:5]:
                                    print(f"    Tópico {p['topico_id']}: {p['prompt']}")
                                if len(prompts_rev) > 5:
                                    print(f"    ... e mais {len(prompts_rev)-5} tópico(s)")
                            print(f"  ─────────────────────────────────────────────────────")
                            print("  Use [reprocessar] para refinamento semantico (mistral:7b).")
                        else:
                            print("\n  Ollama indisponivel. Fase 1 IA pulada.")
                            print("  Inicie o Ollama e execute [reprocessar] para refinar.")
                    except Exception as _e:
                        print(f"\n  Fase 1 IA: erro ao enriquecer ({_e})")

                stats = app.db.estatisticas_banco()
                print(f"\n  Banco: {stats['fontes_ativas']} fonte(s) | "
                      f"{stats['trechos']} trecho(s) | {stats['parametros']} parametro(s)")
                exibir_menu()

            elif cmd.startswith('reprocessar'):
                _cmd_reprocessar(app, entrada)

            elif cmd.startswith('consultar'):
                # Suporta: consultar guarda-corpo n=10  ou  consultar n=5
                resto  = entrada[9:].strip()
                n      = _extrair_n(resto)
                if not _remover_n(resto):
                    print(
                        "\n  📌 DICA DE PESQUISA"
                        "\n  ─────────────────────────────────────────────────"
                        "\n  Separe os termos por espaço, vírgula ou ponto e vírgula."
                        "\n  Todas as formas abaixo são equivalentes:"
                        "\n    inclinação escoamento caimento piso"
                        "\n    inclinação, escoamento, caimento, piso"
                        "\n    inclinação; escoamento; caimento; piso"
                        "\n  Para busca exata de uma frase, use aspas duplas:"
                        "\n    \"caimento mínimo de piso\""
                        "\n  Para controlar o número de resultados, use n=X:"
                        "\n    infiltração fachada n=15"
                        "\n  ─────────────────────────────────────────────────"
                    )
                duvida = _remover_n(resto) or input(
                    "  🔎 Consulta (mín. 3 palavras):\n  > "
                ).strip()
                print(f"\n  ⏳ Pesquisando... (exibindo {n} trecho(s) para IA)\n")
                print(app.consultar(duvida, n=n))
                if getattr(app, '_ultimos_chunks', None):
                    _exp = input("\n  📚 Ver texto completo das fontes? [S / Enter para pular] > ").strip().upper()
                    if _exp == 'S':
                        print(app._renderizar_ultimas_fontes())
                exibir_menu()

            elif cmd.startswith('evidencias') or cmd.startswith('evidência'):
                prefixo = 'evidencias' if cmd.startswith('evidencias') else 'evidência'
                resto   = entrada[len(prefixo):].strip()
                n       = _extrair_n(resto)
                if not _remover_n(resto):
                    print(
                        "\n  📌 DICA DE PESQUISA"
                        "\n  ─────────────────────────────────────────────────"
                        "\n  Separe os termos por espaço, vírgula ou ponto e vírgula."
                        "\n  Todas as formas abaixo são equivalentes:"
                        "\n    infiltração fachada esquadria"
                        "\n    infiltração, fachada, esquadria"
                        "\n    infiltração; fachada; esquadria"
                        "\n  Para busca exata de uma frase, use aspas duplas:"
                        "\n    \"infiltração por fachada\""
                        "\n  Para controlar o número de resultados, use n=X:"
                        "\n    guarda-corpo altura n=15"
                        "\n  ─────────────────────────────────────────────────"
                    )
                duvida  = _remover_n(resto) or input(
                    "  🔎 Termos para busca de evidências:\n  > "
                ).strip()
                print(f"\n  ⏳ Buscando evidências... (exibindo {n} resultado(s))\n")
                print(app.consultar_evidencias(duvida, n=n))
                exibir_menu()

            elif cmd.startswith('parametros') or cmd.startswith('parâmetros'):
                prefixo = 'parametros' if cmd.startswith('parametros') else 'parâmetros'
                resto   = entrada[len(prefixo):].strip()
                n       = _extrair_n(resto)
                termo   = _remover_n(resto) or input(
                    "  📐 Termo para busca de parâmetros (ex: altura, carga):\n  > "
                ).strip()
                print(f"\n  ⏳ Buscando parâmetros...\n")
                print(app.consultar_parametros(termo, n=n))
                exibir_menu()

            elif cmd.startswith('comparar'):
                tema = entrada[8:].strip() or input(
                    "  ⚖️  Tema para comparar Norma vs Laudo:\n  > "
                ).strip()
                print(f"\n  ⏳ Comparando fontes...\n")
                print(app.comparar_fontes(tema))
                exibir_menu()

            else:
                print(f"\n  ⚠️  Comando não reconhecido.")
                acao = input(
                    "  Deseja [S]alvar no banco, fazer uma [C]onsulta "
                    "ou buscar [E]vidências? (S/C/E): "
                ).strip().upper()
                if acao == 'S':
                    r = app.salvar_manual(entrada)
                    print(f"  ✅ Salvo: {str(r)[:80]}...")
                elif acao == 'C':
                    print(app.consultar(entrada))
                elif acao == 'E':
                    print(app.consultar_evidencias(entrada))
                exibir_menu()

    except ValueError as e:
        print(f"\n  ⚠️  {e}")
        print("  Configure o arquivo .env com GEMINI_API_KEY=sua_chave")
        print("  O sistema funciona sem IA — use [evidencias] e [parametros].")
        input("\n  Pressione ENTER para fechar...")
    except Exception as e:
        print(f"\n  ❌ ERRO CRÍTICO: {e}")
        input("\n  Pressione ENTER para fechar...")


if __name__ == "__main__":
    main()

# Levantamento da Arquitetura Atual

## 1) Panorama geral
Sistema atual: aplicacao Python monolitica com interface CLI + GUI Tkinter, processamento offline-first e opcao de IA (Gemini/Ollama).

Arquivos centrais:
- `main.py`: orquestra comandos, interface GUI e fluxos de consulta
- `database.py`: camada de persistencia, busca textual/hibrida, metricas
- `processors.py`: ingestao de arquivos, chunking, extracao de parametros/quesitos
- `orchestrator.py`: monitoramento por fases de reprocessamento
- `ia_integrator.py` e `ai_engine.py`: integracao de IA e fallback
- `analise_ibape.py`, `gut_adaptativo.py`, `analise_imagem.py`: modulos tecnicos especializados

## 2) Estado atual do banco (snapshot local)
Base principal (`banco_pericial.db`):
- laudos: 5
- topicos: 356
- parametros (unificado): 105
- parametros_normativos (legado): 82
- parametros_extraidos: 23
- laudos_estruturado: 347
- topicos_analise_ia: 90
- gut_historico: 10

Bases especializadas:
- `analise_ibape.db` -> `analises_ibape`: 11
- `laudos_imagem.db` -> `laudos_img`: 13, `imagens_laudo_img`: 11

## 3) Fluxos funcionais existentes

### 3.1 Ingestao e indexacao
- Entrada por pastas (`doc_entrada`, `pdf_entrada`, `img_*_entrada`)
- Extracao por tipo de arquivo (DOCX/PDF/TXT/IMG)
- Chunking hierarquico (NBR, ate 4 niveis)
- Extracao de parametros normativos e intervalos
- Extracao de quesitos (regex + fallback IA)
- Persistencia com rastreabilidade de fonte e hierarquia

### 3.2 Consulta tecnica
- Busca textual com FTS5 (fallback LIKE)
- Busca hibrida: textual + vetorial (Chroma opcional)
- Ranking por autoridade de fonte + ancora + favorito perito
- Modo evidencias (sem IA) e modo consulta com IA
- Sessao/historico de conversa e metricas de uso de trechos

### 3.3 Reprocessamento multifasico
- Fase 1: enriquecimento inicial (llama/Gemini se disponivel)
- Fase 2: preenchimento de lacunas + refinamento
- Fase 3: classificacao/normalizacao com retry e backoff
- Monitor de entrada, logs e score de qualidade do banco

### 3.4 Modulos especializados
- GUT Adaptativo: classificacao de risco com nexo causal e historico
- IBAPE: classificacao de anomalia/falha/grau de risco em banco dedicado
- Analise de imagem: fluxo 5 etapas (visual -> GUT -> IBAPE -> banco -> consolidacao)

## 4) Arquitetura de dados atual
Principais tabelas da base principal:
- `laudos`, `topicos`, `topicos_analise_ia`
- `parametros_normativos`, `parametros_extraidos`, `parametros`
- `quesitos_respondidos`, `consultas_populares`, `trechos_utilizados`
- `sessoes`, `historico_sessao`
- `laudos_estruturado`, `contextos_normativos`
- `reprocessamento_log`, `auditoria_mudancas`
- `dicionario_pericial_sinonimos`, `embedding_cache`, `gut_sessao_parcial`

## 5) Pontos fortes da implementacao atual
- Offline-first real
- Busca robusta com FTS5 + vetorial opcional
- Rastreabilidade tecnica alta
- Modulos periciais (GUT/IBAPE/imagem) com persistencia dedicada
- Migracoes idempotentes e operacao resiliente

## 6) Riscos tecnicos para migracao
- Forte acoplamento de regras de negocio no monolito
- Estado distribuido em multiplos bancos SQLite
- Fluxo de pastas locais acoplado a execucao desktop
- Regras de busca/ranking extensas embutidas na camada Python

## 7) Decisao de migracao recomendada
Migracao incremental por estrangulamento:
1. Frontend web em Next (feito no prototipo)
2. Adaptador para acionar pipeline Python existente
3. Consolidacao gradual da camada de leitura/escrita web em SQLite
4. Encapsulamento progressivo dos modulos GUT/IBAPE/imagem em APIs

# Plano de Migracao para Next.js Nativo (sem TanStack)

## Objetivo
Migrar de desktop Python (Tkinter) para plataforma web com Next.js App Router, mantendo rastreabilidade pericial e continuidade operacional.

## Diretrizes
- Sem TanStack
- Usar recursos nativos Next: Server Components, Route Handlers, Server Actions (quando aplicavel)
- SQLite como base transicional
- Preservar regras periciais existentes

## Arquitetura alvo (to-be)

### Camada Web
- Next.js App Router
- Rotas:
  - `/ingestao`
  - `/processamento`
  - `/consultas`
  - `/resultados`
- API nativa para upload e comando de processamento

### Camada de Dominio
- Modulos de dominio isolados por contexto:
  - Ingestao
  - Busca e consulta
  - GUT
  - IBAPE
  - Analise de imagem
- Contratos estaveis para migrar regras sem quebrar UI

### Camada de Persistencia
- SQLite principal com FTS5
- Bancos especializados podem continuar no inicio, com federacao por IDs
- Storage temporario local:
  - `frontend-next/storage/tmp/docs`
  - `frontend-next/storage/tmp/imagens`

## Fases propostas

### Fase 0 - Base web (ja iniciada)
- Prototipo visual com shadcn + Tailwind
- Upload nativo com Route Handler
- Telas de pipeline e resultados visuais

### Fase 1 - Integracao com legado
- Endpoint Next chama pipeline Python (`orchestrator`/`processors`)
- Grava status de execucao para UI em tempo real
- Sem alterar regras de negocio ainda

### Fase 2 - Leitura de consultas no web
- Expor busca textual/hibrida via API
- Reusar ranking e filtros do legado
- Renderizar respostas e evidencias no frontend

### Fase 3 - Migracao de dominio
- Extrair regras centrais para modulos isolados
- Migrar GUT/IBAPE/imagem por bounded contexts
- Cobertura de testes de regressao funcional

### Fase 4 - Cutover
- Operacao principal via web
- CLI/Tkinter como fallback temporario
- Desativacao controlada do desktop

## Backlog tecnico priorizado
1. Contrato de API para upload/processamento/consulta
2. Adaptador Python -> JSON (padrao unico de payload)
3. Observabilidade: logs por job + correlacao de request
4. Tabela de jobs de processamento no SQLite
5. Tela de detalhamento de laudo e trilha de evidencias
6. Exportacao de resultados (DOCX/XLSX) pela interface web
7. Controle de acesso por perfil (perito, apoio, auditor)

## Ideias novas para ganho de processo
- Fila assíncrona por prioridade (norma, laudo, imagem)
- Deduplicacao de upload por hash de arquivo
- Pre-check de qualidade de OCR antes da ingestao
- Snapshot de evidencia por consulta (versionamento)
- Painel de confianca por trecho e por fonte
- Alertas de inconsistencia entre GUT x IBAPE
- Comparador visual "antes/depois" para reprocessamentos

## Resultado visual esperado para consultas
- Cards de KPI (top score, total de resultados, fontes)
- Tabela de resultados com evidencias por trecho
- Barra de aderencia por score
- Indicadores de confianca e risco

# Frontend de Migracao (Next.js + shadcn + Tailwind)

## Objetivo
Prototipo visual para migrar a interface desktop (Tkinter) para web, usando recursos nativos do Next.js App Router.

## Stack
- Next.js App Router
- React 19
- Tailwind CSS
- Componentes no padrao shadcn/ui (pasta `components/ui`)

## Rotas
- `/` Visao geral da migracao
- `/ingestao` Upload de documentos e imagens
- `/processamento` Pipeline e rastreamento de fases
- `/consultas` Consulta e resultados esperados
- `/resultados` Visual por score de aderencia

## Upload temporario (provisorio)
- Docs: `storage/tmp/docs`
- Imagens: `storage/tmp/imagens`
- Endpoint nativo: `app/api/uploads/route.ts`

## Como executar
```bash
cd frontend-next
npm install
npm run dev
```

A aplicacao abriria em `http://localhost:3000`.

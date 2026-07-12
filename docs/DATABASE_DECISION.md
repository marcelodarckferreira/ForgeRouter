# ForgeRouter × Foundation — Banco de dados

> Atualizado em 2026-07-11. A primeira versão deste documento era a proposta
> de decisão (banco `proxyrouter`); esta versão descreve o que está
> **implantado hoje** e mantém a justificativa original ao final.

## Estado atual (implantado)

| Item | Valor |
| --- | --- |
| Instância | Foundation PostgreSQL — container **`foundation_postgres`** (pgvector/pg16), porta **5432** do host |
| Banco | **`forgerouter`** (renomeado; nasceu como `proxyrouter`) |
| Usuário da aplicação | `proxyrouter_user` (nome herdado do original — não foi renomeado) |
| Schema | `ai_router` (todos os objetos da aplicação) |
| Conexão | `DATABASE_URL` no `.env` (nunca commitado) — `postgresql://proxyrouter_user:…@127.0.0.1:5432/forgerouter` |
| Superusuário | `foundation` — dono das tabelas; obrigatório para migrations |

### Migrations

SQL numerado em `db/*.sql` (001–030), aplicado **manualmente** — não há
ferramenta de migração. Sempre como superusuário `foundation`, porque
`proxyrouter_user` não é dono das tabelas:

```bash
docker exec -i foundation_postgres psql -U foundation -d forgerouter < db/0NN_arquivo.sql
```

### Inventário de tabelas (schema `ai_router`, até a migration 030)

| Tabela | Papel |
| --- | --- |
| `providers` | Cadastro de providers (`access_type` subscription/api_key/local, `cost_type` free/paid, `api_format` openai/anthropic, `auth_config` JSONB) |
| `models` | Modelos por provider, join por `public_id` (ex.: `groq/llama-3.1-8b-instant`); `capabilities TEXT[]`, `enabled` |
| `provider_health` | Histórico de saúde **append-only**; `cooldown_seconds` (030) guarda o Retry-After de 429s |
| `route_events` | Uma linha por tentativa de provider: agente, tokens, custo, `demand` (029 — classe resolvida pelo auto) |
| `demand_routes` | Chain customizada por classe de demanda (tela Tasks) |
| `agents` | Keys de agente (`hermes_*`) para `/v1` e admin |
| `agent_models` | Controle de modelos por agente |
| `users` + `sessions` | Login do dashboard (PBKDF2; sessões de 7 dias) |
| `settings` | Chave/valor (ex.: `context_compaction_enabled`) |
| `task_map` | Tarefas auxiliares do Hermes → grupo/modelo |
| `subscription_catalog` | Providers de planos de assinatura conhecidos |
| `usage_monthly` | Roll-up mensal de eventos arquivados |

## Decisão original (mantida)

Usar um banco **separado** na mesma instância Foundation, em vez de reutilizar
o banco `foundation` (que já abriga `public` — checklist/pipeline/PIR,
`knowledge_base` e `hindsight`):

1. Sem colisão de namespace com as tabelas do Foundation.
2. Fronteira própria de backup/restore.
3. Raio de dano limitado se uma migration falhar.
4. Isolamento de permissões simples (`proxyrouter_user` só enxerga o próprio banco).
5. Ciclo de vida de migração independente — ForgeRouter é um produto separado.

Modelo de isolamento: mesma instância PostgreSQL, banco dedicado, usuário
dedicado, schema dedicado (`ai_router`).

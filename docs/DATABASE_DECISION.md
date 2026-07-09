# ForgeRouter Database Recommendation

## Decision
Use a separate PostgreSQL database for ProxyRouter.

Recommended database name:
- proxyrouter

Recommended schema layout inside that database:
- public only for bootstrap metadata, or better:
- ai_router schema for all application objects

## Why not use the Foundation database directly?
The Foundation database already contains multiple applications and domains:
- public: foundation_checklist, pipeline_*, pir_*, provider_groups, maintenance_*
- knowledge_base: checkpoints, checkpoint_log, llm_fallback_log
- hindsight: documents, entities, memory_units, directives, audit_log, webhooks

Using the same database would create avoidable risk:
1. Namespace collision with existing tables and future migrations.
2. Harder backup/restore boundaries.
3. Higher blast radius if ProxyRouter migrations fail.
4. More difficult permission isolation.
5. Operational confusion between Foundation core tables and app tables.

## Recommended isolation model
Best option:
- same PostgreSQL instance
- separate database: proxyrouter
- dedicated user: proxyrouter_user
- dedicated schema: ai_router

This keeps administration simple while preserving strong separation.

## Minimal ProxyRouter database design
### Option A — preferred
Database: proxyrouter
Schema: ai_router

Tables:
- ai_router.providers
- ai_router.models
- ai_router.provider_health
- ai_router.route_events
- ai_router.request_logs
- ai_router.validation_runs

### Option B — acceptable for very small MVP
Database: proxyrouter
Schema: public

This is simpler, but less clean for long-term maintenance.

## Recommendation
Create a new database instead of reusing `foundation`.

Reason:
- ProxyRouter is a separate product/service.
- It needs its own migration lifecycle.
- It should not share state with Foundation audit/pipeline/knowledge tables.
- It reduces risk and makes rollback easier.

## Next step
If approved, create:
- database: `proxyrouter`
- user: `proxyrouter_user`
- schema: `ai_router`
- `.env` updated to point ProxyRouter to the new database

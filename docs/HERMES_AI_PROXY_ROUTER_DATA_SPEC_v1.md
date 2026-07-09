
```md
# HERMES_AI_PROXY_ROUTER_DATA_SPEC_v1

## Tables

### ai_router_providers

```sql
CREATE TABLE ai_router_providers (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  provider_type TEXT NOT NULL,
  tier TEXT NOT NULL,
  auth_method TEXT NOT NULL,
  base_url TEXT,
  enabled BOOLEAN NOT NULL DEFAULT false,
  maturity TEXT NOT NULL DEFAULT 'experimental',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

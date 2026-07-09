CREATE SCHEMA IF NOT EXISTS ai_router AUTHORIZATION proxyrouter_user;

CREATE TABLE IF NOT EXISTS ai_router.providers (
    provider_id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    tier INTEGER NOT NULL,
    base_url TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_router.models (
    model_id BIGSERIAL PRIMARY KEY,
    provider_id BIGINT NOT NULL REFERENCES ai_router.providers(provider_id) ON DELETE CASCADE,
    public_id TEXT NOT NULL UNIQUE,
    provider_model TEXT NOT NULL,
    capabilities TEXT[] NOT NULL DEFAULT ARRAY['text'],
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    healthy BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_router.provider_health (
    health_id BIGSERIAL PRIMARY KEY,
    model_id BIGINT REFERENCES ai_router.models(model_id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    http_code INTEGER,
    latency_ms INTEGER,
    error_message TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_router.route_events (
    route_id BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL,
    selected_model_id BIGINT REFERENCES ai_router.models(model_id) ON DELETE SET NULL,
    required_capability TEXT NOT NULL,
    status TEXT NOT NULL,
    error_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

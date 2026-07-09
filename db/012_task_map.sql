-- Hermes task map: which ForgeRouter group (forgerouter/*) or concrete model each
-- Hermes task should use. Editable from the dashboard Tasks page.
CREATE TABLE IF NOT EXISTS ai_router.task_map (
    task TEXT PRIMARY KEY,
    hint TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_router.task_map TO proxyrouter_user;

INSERT INTO ai_router.task_map (task, hint, model, position) VALUES
    ('Main model', 'primary session model', 'forgerouter/auto', 1),
    ('Vision', 'image analysis', 'forgerouter/vision', 2),
    ('Web Extract', 'page summarization', 'forgerouter/simple', 3),
    ('Compression', 'context compaction', 'forgerouter/simple', 4),
    ('Skills Hub', 'skill search', 'forgerouter/simple', 5),
    ('Approval', 'smart auto-approve', 'forgerouter/simple', 6),
    ('MCP', 'MCP tool routing', 'forgerouter/standard', 7),
    ('Title Gen', 'session titles', 'forgerouter/simple', 8),
    ('Triage Specifier', 'Kanban spec fleshing', 'forgerouter/standard', 9),
    ('Kanban Decomposer', 'task decomposition', 'forgerouter/complex', 10),
    ('Profile Describer', 'auto profile descriptions', 'forgerouter/simple', 11),
    ('Curator', 'skill-usage review', 'forgerouter/standard', 12)
ON CONFLICT (task) DO NOTHING;

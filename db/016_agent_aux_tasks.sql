-- Exclusive auxiliary-tasks role: the one agent whose token authenticates the
-- Hermes auxiliary tasks (Tasks page). The partial unique index guarantees a
-- single holder; assigning the role to another agent clears the previous one.
ALTER TABLE ai_router.agents ADD COLUMN IF NOT EXISTS aux_tasks BOOLEAN NOT NULL DEFAULT FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS agents_single_aux_tasks ON ai_router.agents (aux_tasks) WHERE aux_tasks;

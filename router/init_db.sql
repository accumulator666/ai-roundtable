CREATE DATABASE ai_mesh;
\c ai_mesh;

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id),
    role TEXT NOT NULL,
    model TEXT,
    content TEXT NOT NULL,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost NUMERIC(10, 6) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS delegations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_model TEXT NOT NULL,
    target_model TEXT NOT NULL,
    conversation_id UUID REFERENCES conversations(id),
    request_content TEXT,
    response_content TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS routing_rules (
    id SERIAL PRIMARY KEY,
    task_pattern TEXT NOT NULL,
    preferred_model TEXT NOT NULL,
    fallback_model TEXT,
    priority INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS usage_tracking (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model TEXT NOT NULL,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost NUMERIC(10, 6) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_messages_created ON messages(created_at);
CREATE INDEX idx_usage_model ON usage_tracking(model);
CREATE INDEX idx_usage_created ON usage_tracking(created_at);

INSERT INTO routing_rules (task_pattern, preferred_model, fallback_model, priority) VALUES
    ('code', 'claude-opus-4-6', 'claude-sonnet-4-5', 10),
    ('creative', 'gpt-4o', 'claude-sonnet-4-5', 10),
    ('research', 'grok-3', 'gpt-4o', 10),
    ('image', 'gemini-2.0-flash', 'gpt-4o', 10),
    ('fast', 'claude-haiku-4-5', 'gpt-4o-mini', 10),
    ('default', 'claude-sonnet-4-5', 'gpt-4o', 0);

CREATE TABLE IF NOT EXISTS businesses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'planning',
    business_type TEXT,
    stripe_product_id TEXT,
    domain TEXT,
    deploy_url TEXT,
    total_revenue NUMERIC(12,2) DEFAULT 0,
    total_cost NUMERIC(12,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID REFERENCES businesses(id),
    agent TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    description TEXT NOT NULL,
    reasoning TEXT,
    outcome TEXT,
    cost NUMERIC(10,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS budget_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID,
    transaction_type TEXT NOT NULL,
    amount NUMERIC(10,2) NOT NULL,
    description TEXT,
    agent TEXT,
    stripe_transaction_id TEXT,
    approved_by TEXT DEFAULT 'auto',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID REFERENCES businesses(id),
    agent TEXT NOT NULL,
    task_type TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    input_data JSONB DEFAULT '{}',
    output_data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shared_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE NOT NULL,
    value JSONB NOT NULL,
    agent TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_businesses_status ON businesses(status);
CREATE INDEX IF NOT EXISTS idx_decisions_business ON decisions(business_id);
CREATE INDEX IF NOT EXISTS idx_ledger_business ON budget_ledger(business_id);
CREATE INDEX IF NOT EXISTS idx_ledger_type ON budget_ledger(transaction_type);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON agent_tasks(agent);
CREATE INDEX IF NOT EXISTS idx_memory_key ON shared_memory(key);

-- Agent job history (persists across restarts)
CREATE TABLE IF NOT EXISTS agent_job_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT DEFAULT 'queued',
    description TEXT,
    result TEXT,
    triggered_by TEXT DEFAULT 'manual',
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_job_history_status ON agent_job_history(status);
CREATE INDEX IF NOT EXISTS idx_job_history_type ON agent_job_history(job_type);

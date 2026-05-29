CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE task_state AS ENUM ('RECEIVED','PLANNED','VALUATED','ROUTED','EXECUTING','VALIDATING','PROMOTED','RETRYING','FAILED');
CREATE TYPE evaluation_tier AS ENUM ('DETERMINISTIC','SEMANTIC');
CREATE TYPE capability_status AS ENUM ('STABLE','CANARY','RETIRED');
CREATE TYPE memory_layer AS ENUM ('PERFORMANCE','FAILURE','VALIDATOR','MARKET','EXECUTION');

CREATE TABLE departments (
    department_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    base_currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE markets (
    market_id VARCHAR(32) PRIMARY KEY,
    language_code VARCHAR(8) NOT NULL,
    local_currency VARCHAR(3) NOT NULL,
    compliance_ruleset JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE capabilities (
    capability_id VARCHAR(64) PRIMARY KEY,
    parent_capability_id VARCHAR(64) REFERENCES capabilities(capability_id) ON DELETE SET NULL,
    department_id VARCHAR(64) NOT NULL REFERENCES departments(department_id),
    market_id VARCHAR(32) NOT NULL REFERENCES markets(market_id),
    version VARCHAR(32) NOT NULL DEFAULT '1.0',
    status capability_status NOT NULL DEFAULT 'CANARY',
    input_schema JSONB NOT NULL DEFAULT '{}',
    output_schema JSONB NOT NULL DEFAULT '{}',
    execution_graph JSONB NOT NULL DEFAULT '{}',
    tool_permissions JSONB NOT NULL DEFAULT '[]',
    latency_budget_ms INT NOT NULL DEFAULT 5000,
    cost_budget NUMERIC(12,4) NOT NULL DEFAULT 0.1,
    success_threshold NUMERIC(5,4) NOT NULL DEFAULT 0.9500,
    retirement_threshold NUMERIC(5,4) NOT NULL DEFAULT 0.8000,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_task_id UUID REFERENCES tasks(task_id) ON DELETE SET NULL,
    department_id VARCHAR(64) NOT NULL REFERENCES departments(department_id),
    market_id VARCHAR(32) NOT NULL REFERENCES markets(market_id),
    current_state task_state NOT NULL DEFAULT 'RECEIVED',
    business_context JSONB NOT NULL DEFAULT '{}',
    input_data JSONB NOT NULL DEFAULT '{}',
    output_data JSONB DEFAULT NULL,
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE task_valuations (
    valuation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL UNIQUE REFERENCES tasks(task_id) ON DELETE CASCADE,
    expected_revenue NUMERIC(12,4) NOT NULL DEFAULT 0,
    estimated_cost NUMERIC(12,4) NOT NULL DEFAULT 0,
    success_probability NUMERIC(5,4) NOT NULL DEFAULT 0.5,
    expected_value NUMERIC(12,4) GENERATED ALWAYS AS ((expected_revenue * success_probability) - estimated_cost) STORED,
    urgency_score INT NOT NULL DEFAULT 1,
    reuse_score INT NOT NULL DEFAULT 1,
    localization_score INT NOT NULL DEFAULT 1,
    strategic_score INT NOT NULL DEFAULT 1,
    risk_score INT NOT NULL DEFAULT 1,
    is_negative_override BOOLEAN NOT NULL DEFAULT FALSE,
    evaluated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE task_executions (
    execution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    capability_id VARCHAR(64) NOT NULL REFERENCES capabilities(capability_id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMPTZ,
    actual_cost NUMERIC(12,4) DEFAULT 0,
    latency_ms INT DEFAULT 0,
    error_payload JSONB DEFAULT NULL,
    execution_trace JSONB NOT NULL DEFAULT '[]'
);

CREATE TABLE task_validations (
    validation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    execution_id UUID NOT NULL REFERENCES task_executions(execution_id) ON DELETE CASCADE,
    tier evaluation_tier NOT NULL,
    quality_score NUMERIC(5,4) NOT NULL DEFAULT 0,
    risk_score NUMERIC(5,4) NOT NULL DEFAULT 0,
    business_score NUMERIC(5,4) NOT NULL DEFAULT 0,
    is_passed BOOLEAN NOT NULL DEFAULT FALSE,
    structured_explanation JSONB NOT NULL DEFAULT '{}',
    validated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pattern_memory (
    pattern_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    layer memory_layer NOT NULL,
    capability_id VARCHAR(64) REFERENCES capabilities(capability_id) ON DELETE CASCADE,
    market_id VARCHAR(32) REFERENCES markets(market_id) ON DELETE CASCADE,
    pattern_hash VARCHAR(64) NOT NULL,
    structured_trace_summary JSONB NOT NULL DEFAULT '{}',
    frequency_count INT NOT NULL DEFAULT 1,
    financial_impact_delta NUMERIC(12,4) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE governance_audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES tasks(task_id) ON DELETE SET NULL,
    capability_id VARCHAR(64) REFERENCES capabilities(capability_id) ON DELETE SET NULL,
    action_type VARCHAR(64) NOT NULL,
    operator_identity VARCHAR(128) NOT NULL DEFAULT 'system',
    rationale TEXT NOT NULL DEFAULT '',
    impacted_parameters JSONB NOT NULL DEFAULT '{}',
    logged_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tasks_state ON tasks(current_state);
CREATE INDEX idx_capabilities_status ON capabilities(status, department_id, market_id);
CREATE INDEX idx_valuations_ev ON task_valuations(expected_value);
CREATE INDEX idx_executions_lookup ON task_executions(task_id, capability_id);
CREATE INDEX idx_pattern_lookup ON pattern_memory(layer, pattern_hash);
CREATE UNIQUE INDEX idx_unique_pattern ON pattern_memory(layer, pattern_hash) WHERE layer != 'EXECUTION';

INSERT INTO departments(department_id,name,base_currency) VALUES
  ('maxai-dev','MaxAI Development','USD'),
  ('maxai-trade','MaxAI Trading','USD'),
  ('maxai-parse','MaxAI Parsing','USD'),
  ('maxai-sales','MaxAI Sales','USD');

INSERT INTO markets(market_id,language_code,local_currency,compliance_ruleset) VALUES
  ('RU','ru','RUB','{"gdpr":false,"data_retention_days":365}'),
  ('US','en','USD','{"gdpr":false,"data_retention_days":365}'),
  ('EU','en','EUR','{"gdpr":true,"data_retention_days":90}');

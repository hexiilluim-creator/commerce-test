-- 0062_email_events.sql
CREATE TABLE IF NOT EXISTS email_events (
  id SERIAL PRIMARY KEY,
  store_id INTEGER NULL,
  "to" VARCHAR(255) NOT NULL,
  subject VARCHAR(255) NOT NULL,
  template VARCHAR(100) NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT NULL,
  trace_id VARCHAR(128) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  sent_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS ix_email_events_store_id ON email_events(store_id);
CREATE INDEX IF NOT EXISTS ix_email_events_trace_id ON email_events(trace_id);

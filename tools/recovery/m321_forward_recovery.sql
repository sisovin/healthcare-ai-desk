-- M3.2.1 Phase A.2: REVIEW-ONLY, STATEMENT-SCOPED RECOVERY CANDIDATE.
-- AUTHORITATIVE SOURCE: 20261112_0012_protocol_message_contract.py (upgrade()).
-- NOT APPROVED FOR EXECUTION, INCLUDING ON DISPOSABLE DATABASES.
-- Must NEVER execute as a single SQL file / via mysql < file / via executescript.
-- Individual steps require independently approved rehearsal, zero-row guards,
-- post-statement verification and separate evidence, before starting next step.
-- Scope: a NEW isolated disposable MySQL 8.4. DB must be had_m321_a2_<12hex>
-- at loopback 127.0.0.1:34071, not historic ports 34068/34069/34070.
-- Baseline Alembic 20261112_0011, with nullable INT counter already injected.
-- Execute no ROLLBACK-based "recovery" of MySQL DDL: DDL is not transactional.
-- This SQL is deliberately NOT an Alembic revision and does not update alembic_version.
-- NOTE: Source's three ForeignKeyConstraint objects are unnamed. The MySQL engine
-- may auto-name the FKs; do not claim name-byte equivalence from this SQL text.

-- @step overflow_preflight SELECT gate expected result = 0; STOP otherwise
SELECT COUNT(*) AS exhausted_conversation_count
FROM (
    SELECT MAX(sequence_number) AS max_sequence
    FROM conversation_messages
    GROUP BY organization_id, conversation_id
) AS sequences
WHERE max_sequence >= 2147483647;

-- @step backfill UPDATE; ONLY IF overflow_preflight == 0
UPDATE conversations AS c
LEFT JOIN (
    SELECT organization_id, conversation_id, MAX(sequence_number) AS max_sequence
    FROM conversation_messages
    GROUP BY organization_id, conversation_id
) AS m ON m.organization_id = c.organization_id AND m.conversation_id = c.id
SET c.next_timeline_sequence = COALESCE(m.max_sequence, 0) + 1;

-- @step backfill_postcondition SELECT gate expected result = 0; STOP otherwise
SELECT COUNT(*) AS invalid_backfill_count
FROM conversations AS c
LEFT JOIN (
    SELECT organization_id, conversation_id, MAX(sequence_number) AS max_sequence
    FROM conversation_messages
    GROUP BY organization_id, conversation_id
) AS m ON m.organization_id = c.organization_id AND m.conversation_id = c.id
WHERE c.next_timeline_sequence IS NULL
   OR c.next_timeline_sequence <> COALESCE(m.max_sequence, 0) + 1
   OR c.next_timeline_sequence < 1
   OR c.next_timeline_sequence > 2147483647;

-- @step add_counter_check ALTER; verify named CHECK and enforced status after execution
ALTER TABLE conversations
    ADD CONSTRAINT ck_conversations_next_timeline_sequence
    CHECK (next_timeline_sequence >= 1 AND next_timeline_sequence <= 2147483647);

-- @step enforce_counter_not_null ALTER; verify signed INT NOT NULL DEFAULT 1
ALTER TABLE conversations
    MODIFY next_timeline_sequence INT NOT NULL DEFAULT 1;

-- @step create_protocol_table CREATE TABLE; verify full column/check/FK/unique contract
CREATE TABLE conversation_protocol_messages (
    id VARCHAR(36) COLLATE utf8mb4_unicode_ci NOT NULL,
    organization_id VARCHAR(36) COLLATE utf8mb4_unicode_ci NOT NULL,
    conversation_id VARCHAR(36) COLLATE utf8mb4_unicode_ci NOT NULL,
    sequence_number INT NOT NULL,
    sender_type VARCHAR(16) NOT NULL DEFAULT 'agent',
    sender_agent_profile_id VARCHAR(36) COLLATE utf8mb4_unicode_ci NOT NULL,
    recipient_type VARCHAR(16) NOT NULL,
    recipient_agent_profile_id VARCHAR(36) COLLATE utf8mb4_unicode_ci NULL,
    message_type VARCHAR(32) NOT NULL,
    payload_ciphertext TEXT NULL,
    payload_redacted TEXT NOT NULL,
    data_classification VARCHAR(40) NOT NULL DEFAULT 'internal',
    encryption_key_ref VARCHAR(128) NULL,
    retention_expires_at DATETIME NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    correlation_id VARCHAR(36) NOT NULL,
    causation_id VARCHAR(36) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uq_conversation_protocol_messages_org_id UNIQUE (organization_id, id),
    CONSTRAINT uq_conversation_protocol_messages_org_conversation_sequence UNIQUE (organization_id, conversation_id, sequence_number),
    CONSTRAINT uq_conversation_protocol_messages_org_conversation_idempotency UNIQUE (organization_id, conversation_id, idempotency_key),
    CONSTRAINT ck_conversation_protocol_messages_sender_type CHECK (sender_type = 'agent'),
    CONSTRAINT ck_conversation_protocol_messages_recipient_type CHECK (recipient_type IN ('agent','supervisor','conversation')),
    CONSTRAINT ck_conversation_protocol_messages_recipient_identity CHECK ((recipient_type = 'agent' AND recipient_agent_profile_id IS NOT NULL) OR (recipient_type IN ('supervisor','conversation') AND recipient_agent_profile_id IS NULL)),
    CONSTRAINT ck_conversation_protocol_messages_type CHECK (message_type IN ('task_assigned','agent_progress','agent_result','approval_requested','approval_decided','task_failed','conversation_started','conversation_completed','conversation_cancelled')),
    CONSTRAINT ck_conversation_protocol_messages_classification CHECK (data_classification IN ('public','internal','sensitive','potential_patient_identifying')),
    FOREIGN KEY (organization_id, conversation_id)
        REFERENCES conversations (organization_id, id) ON DELETE CASCADE,
    FOREIGN KEY (organization_id, sender_agent_profile_id)
        REFERENCES agent_profiles (organization_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (organization_id, recipient_agent_profile_id)
        REFERENCES agent_profiles (organization_id, id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- @step create_conversation_time_index CREATE INDEX; verify columns in order
CREATE INDEX ix_conversation_protocol_messages_org_conversation_time
    ON conversation_protocol_messages (organization_id, conversation_id, created_at);

-- @step create_recipient_time_index CREATE INDEX; verify columns in order
CREATE INDEX ix_conversation_protocol_messages_org_recipient_time
    ON conversation_protocol_messages (organization_id, recipient_type, recipient_agent_profile_id, created_at);

-- @postcondition: all 3 counters = 1,2,8 by assigned IDs; all exact semantic
-- columns and 5 CHECK constraints, 3 composite FKs, 3 named uniques, two
-- secondary indexes; compare with archived SUCCESSFUL Unicode 0012 schema.
-- @postcondition: Alembic remains 20261112_0011. No upgrade/stamp allowed.
-- @postcondition: not approved for any preserved/shared environment.

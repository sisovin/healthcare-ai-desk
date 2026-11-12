-- REVIEW ONLY. Exact forward recovery for the captured partial state:
-- had_m32_recovery / 127.0.0.1:34070 / Alembic 20261112_0011.
-- Execute no statement until the Python preflight has passed and each step is approved.
UPDATE conversations c LEFT JOIN (SELECT organization_id,conversation_id,MAX(sequence_number) max_sequence FROM conversation_messages GROUP BY organization_id,conversation_id) m ON m.organization_id=c.organization_id AND m.conversation_id=c.id SET c.next_timeline_sequence=COALESCE(m.max_sequence,0)+1;
SELECT COUNT(*) AS invalid_backfill_count FROM conversations c LEFT JOIN (SELECT organization_id,conversation_id,MAX(sequence_number) max_sequence FROM conversation_messages GROUP BY organization_id,conversation_id) m ON m.organization_id=c.organization_id AND m.conversation_id=c.id WHERE c.next_timeline_sequence IS NULL OR c.next_timeline_sequence<>COALESCE(m.max_sequence,0)+1 OR c.next_timeline_sequence<1 OR c.next_timeline_sequence>2147483647;
-- STOP unless invalid_backfill_count = 0. Remaining exact DDL must be copied
-- statement-for-statement from revision 20261112_0012 after joint review.
ALTER TABLE conversations ADD CONSTRAINT ck_conversations_next_timeline_sequence CHECK (next_timeline_sequence >= 1 AND next_timeline_sequence <= 2147483647);
ALTER TABLE conversations MODIFY next_timeline_sequence INT NOT NULL DEFAULT 1;
CREATE TABLE conversation_protocol_messages (
 id VARCHAR(36) COLLATE utf8mb4_unicode_ci NOT NULL, organization_id VARCHAR(36) COLLATE utf8mb4_unicode_ci NOT NULL, conversation_id VARCHAR(36) COLLATE utf8mb4_unicode_ci NOT NULL, sequence_number INT NOT NULL,
 sender_type VARCHAR(16) NOT NULL DEFAULT 'agent', sender_agent_profile_id VARCHAR(36) COLLATE utf8mb4_unicode_ci NOT NULL, recipient_type VARCHAR(16) NOT NULL, recipient_agent_profile_id VARCHAR(36) COLLATE utf8mb4_unicode_ci NULL,
 message_type VARCHAR(32) NOT NULL, payload_ciphertext TEXT NULL, payload_redacted TEXT NOT NULL, data_classification VARCHAR(40) NOT NULL DEFAULT 'internal', encryption_key_ref VARCHAR(128) NULL, retention_expires_at DATETIME NULL,
 idempotency_key VARCHAR(128) NOT NULL, request_fingerprint VARCHAR(64) NOT NULL, correlation_id VARCHAR(36) NOT NULL, causation_id VARCHAR(36) NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (id),
 CONSTRAINT uq_conversation_protocol_messages_org_id UNIQUE (organization_id,id),
 CONSTRAINT uq_conversation_protocol_messages_org_conversation_sequence UNIQUE (organization_id,conversation_id,sequence_number),
 CONSTRAINT uq_conversation_protocol_messages_org_conversation_idempotency UNIQUE (organization_id,conversation_id,idempotency_key),
 CONSTRAINT ck_conversation_protocol_messages_sender_type CHECK (sender_type = 'agent'),
 CONSTRAINT ck_conversation_protocol_messages_recipient_type CHECK (recipient_type IN ('agent','supervisor','conversation')),
 CONSTRAINT ck_conversation_protocol_messages_recipient_identity CHECK ((recipient_type = 'agent' AND recipient_agent_profile_id IS NOT NULL) OR (recipient_type IN ('supervisor','conversation') AND recipient_agent_profile_id IS NULL)),
 CONSTRAINT ck_conversation_protocol_messages_type CHECK (message_type IN ('task_assigned','agent_progress','agent_result','approval_requested','approval_decided','task_failed','conversation_started','conversation_completed','conversation_cancelled')),
 CONSTRAINT ck_conversation_protocol_messages_classification CHECK (data_classification IN ('public','internal','sensitive','potential_patient_identifying')),
 CONSTRAINT conversation_protocol_messages_ibfk_1 FOREIGN KEY (organization_id,conversation_id) REFERENCES conversations (organization_id,id) ON DELETE CASCADE,
 CONSTRAINT conversation_protocol_messages_ibfk_2 FOREIGN KEY (organization_id,sender_agent_profile_id) REFERENCES agent_profiles (organization_id,id) ON DELETE RESTRICT,
 CONSTRAINT conversation_protocol_messages_ibfk_3 FOREIGN KEY (organization_id,recipient_agent_profile_id) REFERENCES agent_profiles (organization_id,id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE INDEX ix_conversation_protocol_messages_org_conversation_time ON conversation_protocol_messages (organization_id,conversation_id,created_at);
CREATE INDEX ix_conversation_protocol_messages_org_recipient_time ON conversation_protocol_messages (organization_id,recipient_type,recipient_agent_profile_id,created_at);
-- Final equivalence review: SHOW CREATE TABLE conversation_protocol_messages;
-- inspect information_schema columns/indexes/table_constraints; only then seek separate Alembic reconciliation approval.

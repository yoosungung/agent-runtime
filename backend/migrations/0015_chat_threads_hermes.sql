-- Allow Hermes profile agents in chat_threads.thread_type.

ALTER TABLE chat_threads DROP CONSTRAINT IF EXISTS chk_chat_threads_type;
ALTER TABLE chat_threads
    ADD CONSTRAINT chk_chat_threads_type
    CHECK (thread_type IN ('langgraph', 'adk', 'custom', 'hermes'));

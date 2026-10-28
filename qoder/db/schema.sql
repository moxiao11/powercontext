-- LabTrace schema for OceanBase seekdb.
--
-- The backend applies this same DDL automatically on startup (app/db/seekdb.py::init_schema),
-- so you only need this file when you want to review the schema or initialise a *remote*
-- seekdb/OceanBase instance yourself:
--
--   python scripts/init-db.py            # uses SEEKDB_* from qoder/.env
--
-- Keep in sync with app/db/seekdb.py. `embedding VECTOR(384)` matches the default
-- EMBEDDING_DIMENSION; if you change that setting, pass --dimension to scripts/init-db.py
-- (or edit this file) *before* any document is ingested, because the vector dimension and
-- the HNSW index are fixed at table-creation time.

CREATE DATABASE IF NOT EXISTS labtrace DEFAULT CHARACTER SET utf8mb4;
USE labtrace;

-- Projects. Each project owns an isolated set of documents, chunks, experiments and a
-- PowerContext Scope (pc_scope_id); every query filters by project_id.
CREATE TABLE IF NOT EXISTS lt_projects (
    project_id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    pc_scope_id VARCHAR(191),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

-- Uploaded papers / notes. char_count is the extracted text size, chunk_count the number of
-- rows written to lt_document_chunks.
CREATE TABLE IF NOT EXISTS lt_documents (
    doc_id VARCHAR(64) NOT NULL PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL,
    title VARCHAR(512) NOT NULL,
    topic VARCHAR(255),
    file_name VARCHAR(512),
    file_type VARCHAR(16) NOT NULL,
    page_count INT NOT NULL DEFAULT 0,
    char_count INT NOT NULL DEFAULT 0,
    chunk_count INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'ready',
    created_at DATETIME NOT NULL,
    INDEX idx_lt_documents_project (project_id),
    INDEX idx_lt_documents_created (created_at)
);

-- Paragraph-level chunks. page_no is preserved from the source PDF so citations can point at a
-- page; searchable_text is title + topic + content and carries the FULLTEXT index; embedding
-- carries the vector index. AI output is never stored here, only source text.
CREATE TABLE IF NOT EXISTS lt_document_chunks (
    chunk_id VARCHAR(64) NOT NULL PRIMARY KEY,
    doc_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    chunk_index INT NOT NULL,
    page_no INT,
    content LONGTEXT NOT NULL,
    searchable_text LONGTEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    created_at DATETIME NOT NULL,
    INDEX idx_lt_chunks_doc (doc_id),
    INDEX idx_lt_chunks_project (project_id)
);

-- Experiment records. metrics / model_config are JSON text; searchable_text is the projection
-- used by `MATCH ... AGAINST` so historical questions ("之前为什么放弃这个方案") hit real rows.
CREATE TABLE IF NOT EXISTS lt_experiments (
    experiment_id VARCHAR(64) NOT NULL PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    objective TEXT,
    hypothesis TEXT,
    method TEXT,
    model_config TEXT,
    dataset VARCHAR(255),
    result_summary TEXT,
    metrics TEXT,
    issues TEXT,
    failure_reason TEXT,
    next_steps TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    log_markdown LONGTEXT,
    searchable_text LONGTEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_lt_experiments_project (project_id),
    INDEX idx_lt_experiments_created (created_at),
    INDEX idx_lt_experiments_dataset (dataset)
);

-- Records which FULLTEXT parser the live indexes were built with. The parser is not
-- introspectable from information_schema, so the backend compares this row against
-- SEEKDB_FULLTEXT_PARSER and rebuilds both indexes when they differ.
CREATE TABLE IF NOT EXISTS lt_meta (
    meta_key VARCHAR(64) NOT NULL PRIMARY KEY,
    meta_value VARCHAR(255) NOT NULL,
    updated_at DATETIME NOT NULL
);

-- Vector index used by `ORDER BY l2_distance(embedding, ?) APPROXIMATE LIMIT k`.
CREATE VECTOR INDEX lt_chunks_vector_idx ON lt_document_chunks(embedding) WITH (distance=l2, type=hnsw);

-- FULLTEXT indexes used by `MATCH(searchable_text) AGAINST (? IN NATURAL LANGUAGE MODE)`.
-- Parser choice verified on seekdb 1.4.0: `space` and `beng` cannot tokenize Chinese (0 hits on
-- Chinese queries), `ik` and `ngram` both work; `ik` is the default. Note that ik does not drop
-- Chinese stopwords such as 的 -- they do match, at a much lower score (~0.5) than content terms
-- (~2-5), so ranking stays correct but an off-topic probe query must not consist only of particles.
CREATE FULLTEXT INDEX lt_chunks_ft_idx ON lt_document_chunks(searchable_text) WITH PARSER ik;
CREATE FULLTEXT INDEX lt_experiments_ft_idx ON lt_experiments(searchable_text) WITH PARSER ik;

-- Tell the backend which parser is live so it does not drop and rebuild the indexes on start.
INSERT INTO lt_meta (meta_key, meta_value, updated_at) VALUES ('fulltext_parser', 'IK', NOW())
    ON DUPLICATE KEY UPDATE meta_value = VALUES(meta_value), updated_at = VALUES(updated_at);

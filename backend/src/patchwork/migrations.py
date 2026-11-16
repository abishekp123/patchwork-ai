"""Ordered, transactional SQLite migrations; user_version is the schema version."""

MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """CREATE TABLE repositories (
        id TEXT PRIMARY KEY,
        normalized_url TEXT NOT NULL,
        commit_sha TEXT CHECK(commit_sha IS NULL OR length(commit_sha) = 40),
        status TEXT NOT NULL CHECK(status IN ('indexing', 'ready', 'failed')),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, indexed_at TEXT,
        error_code TEXT, error_message TEXT,
        lease_token TEXT, lease_expires REAL,
        snapshot_name TEXT,
        index_version INTEGER NOT NULL DEFAULT 1,
        file_count INTEGER NOT NULL DEFAULT 0 CHECK(file_count >= 0),
        symbol_count INTEGER NOT NULL DEFAULT 0 CHECK(symbol_count >= 0),
        import_count INTEGER NOT NULL DEFAULT 0 CHECK(import_count >= 0),
        skipped_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(normalized_url, commit_sha),
        CHECK(status != 'ready' OR (commit_sha IS NOT NULL AND indexed_at IS NOT NULL)),
        CHECK(status != 'indexing' OR (lease_token IS NOT NULL AND lease_expires IS NOT NULL))
    )""",
        "CREATE INDEX repositories_status ON repositories(status, created_at, id)",
        """CREATE TABLE files (
        id INTEGER PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id),
        path TEXT NOT NULL, path_key TEXT NOT NULL, content_hash TEXT NOT NULL,
        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0), encoding TEXT NOT NULL,
        source TEXT NOT NULL, line_count INTEGER NOT NULL CHECK(line_count >= 1),
        has_errors INTEGER NOT NULL CHECK(has_errors IN (0, 1)),
        UNIQUE(repository_id, path), UNIQUE(id, repository_id)
    )""",
        "CREATE INDEX files_path_key ON files(repository_id, path_key)",
        """CREATE TABLE symbols (
        id INTEGER PRIMARY KEY, repository_id TEXT NOT NULL, file_id INTEGER NOT NULL,
        name TEXT NOT NULL, qualified_name TEXT NOT NULL,
        name_key TEXT NOT NULL, qualified_key TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('module', 'function', 'class', 'method')),
        start_line INTEGER NOT NULL CHECK(start_line >= 1),
        end_line INTEGER NOT NULL CHECK(end_line >= start_line),
        start_byte INTEGER NOT NULL, data_json TEXT NOT NULL,
        FOREIGN KEY(file_id, repository_id) REFERENCES files(id, repository_id) ON DELETE CASCADE,
        UNIQUE(file_id, kind, start_byte, qualified_name)
    )""",
        "CREATE INDEX symbols_name ON symbols(repository_id, name)",
        "CREATE INDEX symbols_qualified ON symbols(repository_id, qualified_name)",
        "CREATE INDEX symbols_key ON symbols(repository_id, name_key)",
        """CREATE TABLE imports (
        id INTEGER PRIMARY KEY, repository_id TEXT NOT NULL, file_id INTEGER NOT NULL,
        module_name TEXT NOT NULL, start_byte INTEGER NOT NULL, data_json TEXT NOT NULL,
        FOREIGN KEY(file_id, repository_id) REFERENCES files(id, repository_id) ON DELETE CASCADE,
        UNIQUE(file_id, start_byte)
    )""",
        "CREATE INDEX imports_module ON imports(repository_id, module_name)",
        """CREATE TABLE IF NOT EXISTS investigations (
        id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES repositories(id),
        commit_sha TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT,
        expires REAL NOT NULL, report TEXT, error_code TEXT
    )""",
        """CREATE TABLE IF NOT EXISTS investigation_steps (
        investigation_id TEXT NOT NULL REFERENCES investigations(id),
        sequence INTEGER NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL,
        PRIMARY KEY(investigation_id, sequence)
    )""",
        "CREATE INDEX IF NOT EXISTS investigations_repository "
        "ON investigations(repository_id, created_at)",
        """CREATE TABLE IF NOT EXISTS patches (
        id TEXT PRIMARY KEY,
        repository_id TEXT NOT NULL REFERENCES repositories(id),
        commit_sha TEXT NOT NULL,
        investigation_id TEXT REFERENCES investigations(id),
        status TEXT NOT NULL CHECK(
            status IN ('draft', 'pending_review', 'approved', 'rejected', 'failed', 'invalid')
        ),
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        diff TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewer TEXT,
        decision_reason TEXT,
        error_code TEXT
    )""",
        "CREATE INDEX IF NOT EXISTS patches_repository_status "
        "ON patches(repository_id, status, created_at)",
    ),
)

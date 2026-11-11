-- Focus & Control SQLite Schema (Version 2)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

-- ============================================================================
-- COMMON TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL CHECK (module IN ('auth', 'tasks', 'challenges', 'settings', 'system')),
    action TEXT NOT NULL,
    entity_type TEXT DEFAULT '',
    entity_id INTEGER,
    details TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activity_logs_module_created
    ON activity_logs(module, created_at DESC);

-- ============================================================================
-- MODULE ONE: WEIGHTED TASK MANAGER
-- ============================================================================

CREATE TABLE IF NOT EXISTS centered_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL DEFAULT 0 CHECK (weight >= 0 AND weight <= 100),
    target_allocation REAL NOT NULL DEFAULT 0 CHECK (target_allocation >= 0),
    target_unit TEXT NOT NULL DEFAULT 'hours',
    allocation_mode TEXT NOT NULL DEFAULT 'budgeted' CHECK (allocation_mode IN ('budgeted', 'manual')),
    allocation_finalized INTEGER NOT NULL DEFAULT 0 CHECK (allocation_finalized IN (0, 1)),
    start_date TEXT DEFAULT '',
    target_end_date TEXT DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'Medium' CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN ('Not Started', 'Active', 'In Progress', 'Completed', 'Archived')),
    background_image TEXT NOT NULL DEFAULT '',
    background_mode TEXT NOT NULL DEFAULT 'none' CHECK (background_mode IN ('none', 'upload', 'preset')),
    font_family TEXT NOT NULL DEFAULT 'Inter',
    primary_color TEXT NOT NULL DEFAULT '#4F46E5',
    accent_color TEXT NOT NULL DEFAULT '#0EA5E9',
    text_color TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    is_demo INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0, 1)),
    is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
    deleted_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_centered_tasks_status
    ON centered_tasks(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS task_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_centered_task_id INTEGER NOT NULL REFERENCES centered_tasks(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL DEFAULT 'standard' CHECK (item_type IN ('standard', 'linked_centered')),
    linked_centered_task_id INTEGER REFERENCES centered_tasks(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    weight_pct REAL NOT NULL DEFAULT 0 CHECK (weight_pct >= 0 AND weight_pct <= 100),
    target_quantity REAL NOT NULL DEFAULT 0 CHECK (target_quantity >= 0),
    target_unit TEXT NOT NULL DEFAULT 'hours',
    allocated_time_budget REAL NOT NULL DEFAULT 0 CHECK (allocated_time_budget >= 0),
    start_date TEXT DEFAULT '',
    due_date TEXT DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'Medium' CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN ('Not Started', 'Active', 'In Progress', 'Completed', 'Archived')),
    notes TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
    deleted_at TEXT,
    reopened_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (item_type = 'standard' AND linked_centered_task_id IS NULL)
        OR
        (item_type = 'linked_centered' AND linked_centered_task_id IS NOT NULL AND linked_centered_task_id != parent_centered_task_id)
    ),
    UNIQUE(parent_centered_task_id, linked_centered_task_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_task_items_single_parent_link
    ON task_items(linked_centered_task_id)
    WHERE linked_centered_task_id IS NOT NULL AND is_deleted = 0;

CREATE INDEX IF NOT EXISTS idx_task_items_parent_status
    ON task_items(parent_centered_task_id, status);

CREATE INDEX IF NOT EXISTS idx_task_items_due_date
    ON task_items(due_date);

CREATE TABLE IF NOT EXISTS task_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_group_id TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('global_budget', 'centered_internal', 'manual_override')),
    centered_task_id INTEGER REFERENCES centered_tasks(id) ON DELETE SET NULL,
    centered_task_name_snapshot TEXT NOT NULL,
    task_item_id INTEGER REFERENCES task_items(id) ON DELETE SET NULL,
    task_item_name_snapshot TEXT DEFAULT '',
    budget_mode TEXT NOT NULL CHECK (budget_mode IN ('fixed', 'dynamic', 'manual')),
    total_budget REAL NOT NULL CHECK (total_budget >= 0),
    budget_unit TEXT NOT NULL DEFAULT 'hours',
    weight_pct REAL NOT NULL CHECK (weight_pct >= 0 AND weight_pct <= 100),
    allocated_target REAL NOT NULL CHECK (allocated_target >= 0),
    target_unit TEXT NOT NULL DEFAULT 'hours',
    reason TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_allocations_centered
    ON task_allocations(centered_task_id, is_active, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_task_allocations_item
    ON task_allocations(task_item_id, is_active, created_at DESC);

CREATE TABLE IF NOT EXISTS task_progress_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_item_id INTEGER NOT NULL REFERENCES task_items(id) ON DELETE CASCADE,
    quantity_completed REAL NOT NULL DEFAULT 0 CHECK (quantity_completed >= 0),
    time_spent_minutes REAL NOT NULL DEFAULT 0 CHECK (time_spent_minutes >= 0),
    entry_timestamp TEXT NOT NULL,
    comments TEXT NOT NULL DEFAULT '',
    update_source TEXT NOT NULL DEFAULT 'manual' CHECK (update_source IN ('manual', 'timer', 'quick_log', 'adjustment')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_progress_item_ts
    ON task_progress_entries(task_item_id, entry_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_task_progress_ts
    ON task_progress_entries(entry_timestamp DESC);

CREATE TABLE IF NOT EXISTS task_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_item_id INTEGER NOT NULL REFERENCES task_items(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_minutes REAL NOT NULL DEFAULT 0 CHECK (duration_minutes >= 0),
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'cancelled')),
    progress_entry_id INTEGER REFERENCES task_progress_entries(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_sessions_item_status
    ON task_sessions(task_item_id, status);

CREATE TABLE IF NOT EXISTS task_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('centered_task', 'task_item')),
    centered_task_id INTEGER REFERENCES centered_tasks(id) ON DELETE SET NULL,
    task_item_id INTEGER REFERENCES task_items(id) ON DELETE SET NULL,
    entity_name_snapshot TEXT NOT NULL,
    from_status TEXT DEFAULT '',
    to_status TEXT NOT NULL CHECK (to_status IN ('Not Started', 'Active', 'In Progress', 'Completed', 'Archived')),
    reason TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_status_history_entity
    ON task_status_history(entity_type, centered_task_id, task_item_id, changed_at DESC);

-- ============================================================================
-- MODULE TWO: URGE & RESISTANCE TRACKER
-- ============================================================================

CREATE TABLE IF NOT EXISTS challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    behaviour_to_avoid TEXT NOT NULL,
    objective TEXT NOT NULL DEFAULT '',
    start_date TEXT DEFAULT '',
    end_date TEXT DEFAULT '',
    planned_duration_days INTEGER,
    target_value REAL DEFAULT 0,
    target_unit TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN ('Not Started', 'Active', 'Paused', 'Completed', 'Archived')),
    current_cycle_id INTEGER REFERENCES challenge_cycles(id) ON DELETE SET NULL,
    is_demo INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0, 1)),
    is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
    deleted_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_challenges_status
    ON challenges(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS challenge_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE RESTRICT,
    cycle_number INTEGER NOT NULL CHECK (cycle_number >= 1),
    status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Not Started', 'Active', 'Paused', 'Reset', 'Completed')),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    reset_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(challenge_id, cycle_number)
);

CREATE INDEX IF NOT EXISTS idx_challenge_cycles_challenge
    ON challenge_cycles(challenge_id, cycle_number DESC);

CREATE TABLE IF NOT EXISTS challenge_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL UNIQUE REFERENCES challenges(id) ON DELETE CASCADE,
    background_image TEXT NOT NULL DEFAULT '',
    background_mode TEXT NOT NULL DEFAULT 'none' CHECK (background_mode IN ('none', 'upload', 'preset')),
    font_family TEXT NOT NULL DEFAULT 'Inter',
    font_size TEXT NOT NULL DEFAULT '16px',
    text_color TEXT NOT NULL DEFAULT '',
    accent_color TEXT NOT NULL DEFAULT '#0D9488',
    card_style TEXT NOT NULL DEFAULT 'elevated' CHECK (card_style IN ('elevated', 'bordered', 'glass', 'minimal')),
    layout_style TEXT NOT NULL DEFAULT 'comfortable' CHECK (layout_style IN ('comfortable', 'compact', 'focused')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS urge_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE RESTRICT,
    cycle_id INTEGER NOT NULL REFERENCES challenge_cycles(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN ('THOUGHT', 'URGE', 'ACTION')),
    outcome TEXT NOT NULL CHECK (
        (event_type = 'THOUGHT' AND outcome = 'Observed')
        OR
        (event_type = 'URGE' AND outcome IN ('Resisted', 'Gave In', 'Pending'))
        OR
        (event_type = 'ACTION' AND outcome = 'Occurred')
    ),
    related_urge_id INTEGER REFERENCES urge_events(id) ON DELETE SET NULL,
    event_timestamp TEXT NOT NULL,
    trigger_category TEXT NOT NULL DEFAULT '',
    trigger_text TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    duration_seconds INTEGER NOT NULL DEFAULT 0 CHECK (duration_seconds >= 0),
    comments TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_urge_events_challenge_ts
    ON urge_events(challenge_id, event_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_urge_events_cycle
    ON urge_events(cycle_id, event_type, outcome);

CREATE INDEX IF NOT EXISTS idx_urge_events_trigger_cat
    ON urge_events(trigger_category, event_timestamp DESC);

CREATE TABLE IF NOT EXISTS challenge_daily_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    record_date TEXT NOT NULL,
    reflection TEXT NOT NULL DEFAULT '',
    mood TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(challenge_id, record_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_records_challenge_date
    ON challenge_daily_records(challenge_id, record_date DESC);

CREATE TABLE IF NOT EXISTS challenge_daily_reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    cycle_id INTEGER REFERENCES challenge_cycles(id) ON DELETE SET NULL,
    record_date TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    reflection_text TEXT NOT NULL,
    mood TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_daily_reflections_challenge_date
    ON challenge_daily_reflections(challenge_id, record_date DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS challenge_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    cycle_id INTEGER REFERENCES challenge_cycles(id) ON DELETE SET NULL,
    record_date TEXT NOT NULL,
    comment_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_challenge_comments_date
    ON challenge_comments(challenge_id, record_date DESC, created_at DESC);

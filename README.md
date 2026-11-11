# Focus & Control — Personal Productivity & Behaviour Tracking System

**Focus & Control** is a locally hosted Flask + SQLite web application combining two independent, deeply integrated modules under a shared application lock, unified dashboard, and analytics engine:

1. **Weighted Task Manager** — Hierarchical centered tasks, nested centered task linking, percentage-based budget allocation, immutable allocation snapshots, custom target units, live focus timers, and progress/completion lifecycle tracking.
2. **Urge & Resistance Tracker** — Behavioural control challenges, cycle-preserving resets, separated Thought / Urge / Action tracking, pending urge resolution, daily tracking with timestamped reflections/comments, and per-challenge visual customization.

---

## Features

### Application Lock & Security
- Dedicated first-time setup (`/setup`) supporting numeric **PIN (4–12 digits)** or **Password (6+ characters)**.
- Credentials hashed via Werkzeug cryptographic hashing (`generate_password_hash` / `check_password_hash`); plaintext secrets are never stored.
- Session-based authentication guard (`@app.before_request`) protecting all routes and JSON endpoints, with configurable inactivity timeout, lock-version invalidation, failed-attempt cooldown, and instant relock.

### Shared Dashboard, Navigation & Customization
- Responsive sidebar layout with Light and Dark themes (`Bootstrap 5`, `Lucide Icons`, `Chart.js`).
- Live summary KPIs, active focus session banner, recent tasks, active challenges with 1-click event capture, and interactive charts.
- Optional **Demo Workspace** data (`DEMO`-tagged) in **Settings** kept cleanly separated from personal records.

### Module 1: Weighted Task Manager
- **Centered Tasks & Internal Tasks**: Unlimited tasks with custom colors, fonts, background presets/uploads, and key-value metadata.
- **Nested Centered Tasks**: Link an existing centered task as an internal task of another centered task with automatic **circular reference prevention**, single-parent consistency enforcement (preventing duplicate progress/budget counting), and independent **Clone Copy** support.
- **Weight Validation (100%)**: Draft editing with live percentage meters and strict 100% validation on allocation finalization with explanatory feedback.
- **Fixed & Dynamic Budget Modes**:
  - **Mode A (Fixed)** & **Mode B (Dynamic)** time budget recalculations.
  - Immutable allocation snapshots (`task_allocations`) saved on every change without overwriting history.
  - Explicit protection against overwriting completed task targets unless confirmed by the user.
- **Progress, Focus Sessions & Lifecycle**:
  - Supports custom target units (`hours`, `pages`, `sessions`, `repetitions`, etc.) independently from time spent.
  - Built-in live **Focus Session Timer** (`task_sessions`) logging sessions directly to progress entries.
  - Lifecycle tabs (`All Tasks`, `Active`, `In Progress`, `Completed`, `Archived`) plus dedicated `/tasks/completed` archive, auto-completion at target, parent rollup, and explicit **Reopen** with `task_status_history`.

### Module 2: Urge & Resistance Tracker
- **Challenge Lifecycle**: Start, Pause, Resume, Reset, Complete, Archive, and Delete.
- **Cycle-Preserving Reset**: Resetting archives the current cycle (`Reset`) and opens a fresh cycle (`Cycle #N+1`) while preserving all prior events, reflections, and cycle comparisons.
- **Strict Event Separation**:
  - `THOUGHT` (`Observed`)
  - `URGE` (`Resisted`, `Gave In`, `Pending`)
  - `ACTION` (`Occurred`, optionally linked to a preceding urge without double-counting)
  - Preserves historical `event_timestamp` and `created_at` during edits.
- **Daily Tracking**: Daily totals computed dynamically from event records; daily reflections, mood, and individual daily comments with separate `created_at` and `updated_at` timestamps.
- **Per-Challenge Customization**: Upload custom PNG/JPG/WEBP backgrounds (validated via Pillow up to 5 MB), choose preset SVGs, font family, font size, accent/text colors, card style (`elevated`, `bordered`, `glass`, `minimal`), and layout style (`comfortable`, `compact`, `focused`).

### Global Statistics (`/statistics`)
- Date-range filtering (local timezone converted accurately to UTC SQL bounds) and optional Demo data exclusion.
- Cross-module Chart.js analytics: time distribution, target vs actual time & quantities, daily/weekly progress, completion trends, overdue tasks, daily/weekly/monthly urge trends, trigger frequency, 24-hour time-of-day distribution, and challenge comparison.

---

## Architecture

The codebase strictly follows a clean layered Flask architecture without SQLAlchemy, ORM layers, or Python type hints:

```
Route (app/routes/)  -->  Service (app/services/)  -->  Repository (app/repositories/)  -->  SQLite (sqlite3 raw parameterized SQL)
```

- **`app/database/connection.py`**: Manages SQLite connections with `PRAGMA foreign_keys = ON`, `WAL` mode, and versioned schema initialization (`schema_migrations`).
- **`app/database/transaction.py`**: Shared `transaction()` context manager handling atomic `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK` and nested `SAVEPOINT` support across services.
- **`app/utils/time_utils.py`**: Stores all timestamps consistently in UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`) and converts to the user's configured local timezone (`zoneinfo`) for display and daily/hourly grouping.

---

## Important Calculation Formulas

1. **Weighted Task Allocation**:
   $$\text{Centered Target} = \text{Total Budget} \times \frac{\text{Centered Weight}}{100}$$
   $$\text{Internal Allocated Budget} = \text{Centered Target} \times \frac{\text{Internal Weight \%}}{100}$$

2. **Internal Task Completion**:
   $$\text{Item Completion \%} = \min\left(100,\ \frac{\sum \text{Quantity Completed}}{\text{Target Quantity}} \times 100\right)$$
   *(Calculated from `quantity_completed` in the item's `target_unit`, not assumed equal to time spent.)*

3. **Centered Task Weighted Completion**:
   $$\text{Centered Completion \%} = \frac{\sum (\text{Item Weight \%} \times \text{Item Completion \%})}{100}$$
   *(For linked centered tasks, `Item Completion %` recursively reflects the child centered task's completion percentage. Global time totals sum directly from `task_progress_entries` per leaf item to eliminate duplicate counting.)*

4. **Urge Resistance Rate**:
   $$\text{Resistance Rate \%} = \frac{\text{Resisted Urges}}{\text{Resisted Urges} + \text{Gave-In Urges}} \times 100$$
   *(`Pending` urges are excluded from the denominator; `THOUGHT` and `ACTION` events are never mixed into the resistance rate.)*

---

## Installation & Running Locally

### 1. Prerequisites
- Python 3.11+

### 2. Install Dependencies
```bash
python -m pip install -r requirements.txt
```

### 3. Database Initialization
Database tables and default settings are initialized automatically on startup via `app/database/schema.sql` into `instance/focus_control.db`. No manual migration step is required.

### 4. Run the Application
```bash
python run.py
```
Then open `http://127.0.0.1:5000` in your browser. On first launch, you will be guided through `/setup` to create your PIN or password.

Environment variables (optional):
- `FOCUS_CONTROL_HOST` (default `127.0.0.1`)
- `FOCUS_CONTROL_PORT` (default `5000`)
- `FOCUS_CONTROL_DEBUG` (`1` to enable debug mode, default `0`)
- `FOCUS_CONTROL_DB` (custom SQLite file path)

---

## Running Automated Tests

```bash
python -m unittest discover -s tests -v
```

The test suite verifies authentication & session expiry, AST compliance (zero ORM/SQLAlchemy and zero type hints), budget & 100% weight validation, nested cycle protection & non-duplicated progress, completion/reopening lifecycle, challenge cycle resets, resistance rate math, daily comments, and image upload validation.

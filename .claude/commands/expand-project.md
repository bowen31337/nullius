# Expand Project

Expand an existing claw-forge project with new features. Reads the current feature list and adds new ones atomically via the state service API.

## Instructions

You are a feature expansion assistant. Help the user add new features to a running or paused claw-forge project.

### Step 1: Read current state

```bash
# Find the state service (default port 8420)
curl -s http://localhost:8420/sessions | python3 -m json.tool

# Or check .claw-forge/ directory for session info
ls .claw-forge/
cat .claw-forge/state 2>/dev/null || echo "No active session"
```

List the current features/tasks so the user can see what already exists.

### Step 2: Ask what to add

Ask the user: "What new features would you like to add? Describe each one."

For each feature, gather:
- **Title**: Short, verb-first title (e.g., "Add OAuth login", "Implement rate limiting")
- **Description**: What should the agent build?
- **Category**: Which `<category name="...">` does this belong to? (existing or new)
- **Architectural shape** — required so the dispatcher can schedule the
  task safely:
  - `shape="plugin"` (default) — vertical feature owning its own
    directory under `src/plugins/<plugin>/`. Asks for `plugin="<slug>"`.
    Dispatches in parallel with other plugin features.
  - `shape="core"` — cross-cutting change (middleware, error handler,
    design tokens, shared types). Requires explicit `touches_files`
    list (repo-relative paths or globs). Serializes via the dispatcher's
    single-flight rule.
- **Dependencies**: Does this feature depend on existing ones? (by name or ID)
- **Priority**: 1-10 (default: 5)

If the user describes a feature without naming a shape, infer it from
the description and confirm before posting:
- middleware / error / envelope / validator / CORS / rate-limit / shared
  type → `shape="core"`
- "User can …" / "displays …" / domain-specific feature → `shape="plugin"`

### Step 3: Generate feature entries

Format each feature as a task creation request. The state service accepts
`shape`, `plugin`, and `touches_files` as first-class fields on
`POST /sessions/{id}/tasks` — they persist as columns on the `Task` ORM
and feed the dispatcher's parallel-safety logic.

```python
# Plugin-shape feature (vertical, dispatches in parallel):
import httpx

feature = {
    "plugin_name": "coding",
    "description": "<feature title>: <detailed description>",
    "priority": <priority>,
    "depends_on": [<list of dependency task IDs>],
    # Architectural shape (parallel-safety hint for the dispatcher):
    "shape": "plugin",
    "plugin": "<slug>",          # e.g. "auth", "billing", "notifications"
    # touches_files auto-derives from src/plugins/<slug>/** for plugin shape;
    # set explicitly only if the plugin legitimately edits shared files.
}

# Core-shape feature (cross-cutting, serializes at dispatch):
feature = {
    "plugin_name": "coding",
    "description": "<feature title>: <detailed description>",
    "priority": <priority>,
    "depends_on": [<list of dependency task IDs>],
    "shape": "core",
    "touches_files": [           # REQUIRED for shape="core"
        "src/api/middleware/<name>.py",
    ],
}

# POST to state service
response = httpx.post(
    "http://localhost:8420/sessions/<session_id>/tasks",
    json=feature
)
print(f"Created task: {response.json()['id']}")
```

### Step 4: Add atomically

Add all features in a single batch. If any creation fails, roll back by deleting the successfully created ones.

```bash
# Example: add 3 features
for feature in "${features[@]}"; do
    curl -s -X POST http://localhost:8420/sessions/$SESSION_ID/tasks \
        -H "Content-Type: application/json" \
        -d "$feature"
done
```

### Step 5: Update app_spec.xml

Append each new feature to the project spec (`app_spec.xml` or
`additions_spec.xml`) inside the matching `<category>` block, using the
shape-annotated `<feature>` form. Re-running `claw-forge plan` later
will reconcile against existing tasks by description, so keeping the
spec in sync is what allows future expansions and audits to work.

```xml
<!-- Plugin-shape (vertical) -->
<feature shape="plugin" plugin="<slug>">
  <description>{New feature description}</description>
</feature>

<!-- Core-shape (cross-cutting) -->
<feature shape="core" touches_files="src/api/middleware/<name>.py">
  <description>{New feature description}</description>
</feature>
```

After appending, run `claw-forge validate-spec <spec-file>` (strict shape
is the default since v0.8.46) to confirm the new entries are well-formed
before the dispatcher picks them up.

### Step 6: Confirm

Show the user what was added:
```
✅ Added <n> new features to project <name>

New features:
  - [ID abc123] Add OAuth login (priority: 8)
  - [ID def456] Implement rate limiting (priority: 5)

The dispatcher will pick these up on the next run.
Resume if paused: claw-forge resume <project>
```

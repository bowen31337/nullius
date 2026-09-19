# Pool Status

Show the configured provider pool, and what is measurably in use.

## What this can and cannot tell you

**Read this before interpreting the output.** The provider rotation lives
inside the `claw-forge run` process. The state service is a *child* of that
process and holds no pool object, so **no surface claw-forge offers can show
the roster a live run is actually rotating over.** Anything presented as the
pool is read from `claw-forge.yaml` plus the local overlay.

That is not a gap you can work around by asking a different command — until
1.13.2 every surface answered from the file while using live-state vocabulary
(`health: healthy`, `circuit_state: closed`, `rpm`), so they corroborated each
other and read as confirmation. A provider added mid-run appeared healthy on
all of them while serving zero tokens for a 90-minute run.

What IS measured, and therefore trustworthy:

- **`Served`** (CLI) / **`measured_input_tokens` + `measured_output_tokens`**
  (API) — per-provider token totals from the `provider_usage` table,
  accumulated over HTTP by the dispatcher's TokenMeter. A provider reading
  `never used` has served nothing, whatever the config says.
- **`active`** — whether a dispatcher is heartbeating right now.
- **`source`** — where the roster came from (`config`).

Fields that are not measurements are `null` or `"unknown"`, never a
plausible-looking zero. Do not report them as observations.

## Instructions

### Step 1: Get the status

```bash
claw-forge pool-status --config claw-forge.yaml
```

The command works offline. It also asks this project's state service (port
discovered, not assumed) for measured usage, and prints a banner saying which
of three situations you are in: service unreachable, no active run, or **a run
is active and this table may not be its roster**.

For the raw payload:

```bash
curl -s http://localhost:8420/pool/status | python3 -m json.tool
```

### Step 2: Read it honestly

For each provider report:

- **Name / type / priority / enabled** — config facts.
- **Served** — measured. This is the one that answers "is this provider
  actually being used?"

Do **not** invent health, success rate, latency or cost-per-hour: claw-forge
does not collect them, and presenting them is the defect this command was
rewritten to stop.

### Step 3: Diagnose a provider that is configured but idle

If a provider shows `never used` while a run is active:

1. The pool is built **once** at run start and is never reloaded. A provider
   added to `claw-forge.yaml` or `claw-forge.local.yaml` after the run began
   is invisible to it for the run's entire life. Check the file's mtime
   against the run's start; `claw-forge run` also warns about this once per
   run when it detects it.
2. Confirm from the authoritative source — the dispatch record in `state.db`:

```bash
sqlite3 "file:.claw-forge/state.db?mode=ro" \
  "select json_extract(payload,'\$.provider') provider, count(*)
   from events
   where event_type='agent_log'
     and json_extract(payload,'\$.provider') is not null
   group by 1 order by 2 desc;"
```

A configured provider missing from that result is not being used.

3. The fix is to **restart the run**. There is no hot reload.

### Step 4: Changing providers

`PATCH /pool/providers/{name}` and the Kanban toggle write the *local overlay*
for the **next** run; they return `applies_to_run: false` to say so. While a
dispatcher is alive the toggle returns **409** rather than reporting a success
it cannot deliver.

### CLI shortcut

`claw-forge pool-status` prints the same data. Use this slash command when you
want the diagnosis walked through, not just the table.

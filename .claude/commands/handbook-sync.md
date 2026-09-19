# Sync the Handbook

Bring `handbook/` back in line with the code after a feature landed or changed.
Regenerates the reference chapters, then works through whatever the drift
checker says still needs a human — in **both** the English and Chinese editions.

Use this after shipping anything that changes a command, a flag, a config key,
an API route, or the behaviour a chapter describes.

## Before you start

Read `handbook/README.md` (the workflow) and `handbook/STYLE.md` (the writing
contract). If you are going to touch `handbook/zh/`, also read
`handbook/tools/locales/glossary-zh.md` and use its terms.

## Step 1 — Regenerate and see where you stand

```bash
uv run python handbook/tools/gen.py build
uv run python handbook/tools/gen.py status
```

`build` refreshes the generated reference chapters, both index pages, the
navigation footers, and `mkdocs.yml`. It never touches hand-written prose.

Report to the user what `build` changed. New commands or config keys appearing
in the reference chapters are the signal that prose chapters likely need work
too.

## Step 2 — Fix every error

```bash
uv run python handbook/tools/gen.py check
```

Errors block CI, and each one is machine-fixable. Work through them:

| Error kind | What to do |
|---|---|
| `stale-generated` | Re-run `build`. If it persists, the generator is non-deterministic — fix `handbook/tools/render.py`. |
| `missing-page` | Re-run `build` to scaffold it, then write the chapter. |
| `dead-link` | Fix the link target. Chapter filenames are in `handbook/book.yaml`. |
| `multiple-h1` / `no-h1` | A chapter has exactly one H1 and it matches `book.yaml`. |
| `mermaid-*` | Fix the diagram: quoted labels, known diagram type, balanced brackets. |
| `duplicate-nav` | Delete everything from the first `<!-- HANDBOOK-NAV -->` marker, then re-run `build`. |
| `false-claim` | **Read carefully** — see below. |

### On `false-claim` errors

`handbook/tools/lint.py` holds a list of claims that appear in this repo's older
documentation but are not true of the code — `claw-forge analyze` does not
exist, `claw-forge add --spec` fails, `run` has no `--spec` flag, and so on.

Two legitimate responses, and one wrong one:

- **The chapter was prescribing it** → remove it and describe what actually
  works. This is usually the right answer.
- **The chapter is warning readers about it** (the troubleshooting and FAQ
  chapters do this deliberately) → add `<!-- lint-allow: <tag> -->` to that page.
- **Never** delete the entry from `BANNED_CLAIMS` to make the check pass. If a
  claim became true because someone implemented the command, then remove the
  entry — but verify it in the source first, and say so in the commit message.

## Step 3 — Work through the warnings

Warnings name chapters whose watched sources moved. For each one:

1. Read the chapter.
2. Read the diff of the source it watches (`git log -p <source>` since the last
   baseline).
3. Decide honestly: is the chapter still accurate?
   - **Still accurate** → nothing to write; it just needs re-baselining.
   - **Now wrong or incomplete** → update it, in both languages.
4. Baseline it:

```bash
uv run python handbook/tools/gen.py accept --chapter <CHAPTER_ID>
```

> [!IMPORTANT]
> Only run `accept` for chapters you actually re-read. Baselining everything to
> clear the output defeats the entire mechanism — the next real change will not
> be noticed by anybody.

Handle `translation-stale` warnings the same way: the English page moved and the
Chinese one did not, so bring `zh/` up to date and then baseline.

## Step 4 — Keep the editions structurally parallel

`structure-mismatch` warnings mean one edition gained or lost a section.
`STYLE.md` requires an identical H2/H3 sequence across languages, because that
is what makes the two editions reviewable side by side. Fix the structure rather
than suppressing the warning.

## Step 5 — Verify

```bash
uv run python handbook/tools/gen.py check
uv run python handbook/tools/gen.py build   # must produce no diff
git status --short handbook/
```

The second `build` producing a diff means the generator is not reproducible,
which CI also checks. Fix it before committing.

Then confirm at least one changed page renders correctly — Mermaid blocks and
tables are the usual casualties.

## Step 6 — Report

Tell the user:

- what the generated chapters gained or lost (new commands, flags, config keys,
  routes);
- which prose chapters you updated, in which languages, and why;
- which chapters you re-baselined without changes, and on what basis you judged
  them still accurate;
- anything you could not verify, stated plainly rather than glossed over.

Commit the chapters together with `handbook/tools/drift.lock.json` — the lock is
the record of what was confirmed, and it is meaningless if it lands separately.

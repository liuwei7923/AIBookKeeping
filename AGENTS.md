# AGENTS.md

This repository builds a CSV-first, multi-user AI bookkeeping MVP focused on categorization memory.

Before making meaningful changes in this repo:

1. Read `docs/development-lifecycle.md`
2. Match the work to a GitHub issue when possible
3. Keep commits scoped to one logical change
4. Run tests before committing
5. Update README and GitHub issues when product direction or API shape changes

Current product focus:

- local categorization memory
- bank-statement intake, review, and memory retrieval APIs
- memory-aware recategorization
- category consistency and token-cost control
- simple frontend work needed to make the MVP usable end to end
- multi-user data and workflow boundaries

Do not introduce yet:

- a database
- complex frontend architecture or frontend work beyond the MVP
- background jobs
- agent orchestration
- unnecessary OpenAI calls for deterministic tasks

Use `docs/development-lifecycle.md` as the detailed project workflow reference.

## Agent skills

### Issue tracker

Issues are tracked in this repo's GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

This repo uses the default canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

This repo uses a single-context domain doc layout rooted at `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

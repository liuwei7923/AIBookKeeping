# AGENTS.md

This repository builds a CSV-first AI bookkeeping backend focused on categorization memory.

Before making meaningful changes in this repo:

1. Read `docs/development-lifecycle.md`
2. Match the work to a GitHub issue when possible
3. Keep commits scoped to one logical change
4. Run tests before committing
5. Update README and GitHub issues when product direction or API shape changes

Current product focus:

- local categorization memory
- memory import and retrieval APIs
- memory-aware recategorization
- category consistency and token-cost control

Do not introduce yet:

- a database
- frontend work
- background jobs
- agent orchestration
- unnecessary OpenAI calls for deterministic tasks

Use `docs/development-lifecycle.md` as the detailed project workflow reference.

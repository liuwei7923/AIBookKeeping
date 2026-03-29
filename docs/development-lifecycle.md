# Development Lifecycle

This project uses a small, issue-driven development cycle.

The goal is to keep the product direction clear, the commit history clean, and
the implementation easy to reason about as the app evolves.

## Principles

- Keep scope small and explicit.
- Prefer simple local storage before adding infrastructure.
- Tie code changes to GitHub issues whenever possible.
- Keep commits focused on one logical change.
- Add or update tests for behavior changes.
- Keep README and issue descriptions aligned with the real product direction.

## Standard Workflow

### 1. Clarify the product goal

Before coding, confirm:

- what user problem is being solved
- whether this is current functionality or future design
- what should stay out of scope for now

If the product direction changes, update the README and GitHub issues first.

### 2. Create or refine a GitHub issue

Each meaningful change should map to an issue.

An issue should capture:

- the goal
- why it matters
- scope
- acceptance criteria
- important design constraints

If the implementation reveals a better shape than the original issue, update the
issue before or during implementation.

### 3. Design before coding

For non-trivial changes, define:

- input shape
- output shape
- storage design
- where the logic belongs
- how the change will be tested

Prefer extending existing modules only when the responsibility is a clear fit.
If a new concern appears, create a new module rather than overloading an old one.

### 4. Implement in small steps

Typical order:

1. schema or config
2. parsing and storage logic
3. service logic
4. API routes
5. tests
6. README or documentation updates

Avoid mixing unrelated changes in one patch.

### 5. Verify locally

Minimum verification before commit:

```bash
python3 -m py_compile main.py bookkeeping_app/*.py tests/*.py
.venv/bin/python -m pytest -q
```

When relevant, also run:

- live integration tests
- manual curl requests
- sample CSV import checks

### 6. Commit cleanly

Commit messages should match the logical change, not a random file set.

Examples:

- `Add categorization memory foundation`
- `Add categorization memory import and retrieval APIs`
- `Add live integration test support`

If a change naturally breaks into multiple logical units, use multiple commits.

### 7. Push and sync GitHub

After verification:

1. push the commit(s)
2. update related GitHub issues
3. close completed issues or add completion notes

The repo, issues, and README should not drift apart.

## Testing Policy

### Unit and API tests

Use `pytest` for:

- parser behavior
- memory logic
- route behavior via FastAPI `TestClient`

### Integration tests

Use live service integration tests when verifying:

- app startup
- environment-based configuration
- real HTTP behavior
- file-backed storage behavior through a running server

Integration tests should use temporary file paths and should not write to real
local data files.

## Documentation Policy

When product direction changes:

- update `README.md`
- update affected GitHub issues
- add or update local docs in `docs/` if the change affects process or design

When code structure becomes non-obvious:

- add short module-level documentation
- keep comments brief and purposeful

## Scope Control

To keep the project manageable:

- do not add databases until file-backed storage becomes clearly insufficient
- do not add frontend work before backend behavior is stable
- do not add agent systems or streaming until the memory-driven categorization
  loop is solid
- do not call OpenAI for tasks that can be handled deterministically

## Current Product Sequence

The current roadmap is:

1. local categorization memory foundation
2. memory import API
3. memory retrieval API
4. memory-aware recategorization
5. category reference file
6. token-cost controls
7. richer retrieval and merchant normalization

## Definition of Done

A change is done when:

- the scope matches the issue
- tests pass
- README or docs are updated if needed
- commits are clean
- code is pushed
- related issue state is updated

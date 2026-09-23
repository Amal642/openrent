### Coding discipline (avoid repeating mistakes)

Before any coding or deploy task, read `docs/coding-lessons.md` and apply its pre-flight checklist to what you're about to do. After any mistake, wrong assumption, or user correction, append a one-line lesson to that file (one line, prune duplicates). It is the durable, shared record — keep it current.

### Session continuity

After compaction or resume, treat the injected handoff (`docs/handoff-context.md`) as working context, but verify code-state claims against the current repository before acting.

If `docs/handoff-context.md` exists at session start and the current task appears to continue prior work, read it early and verify its claims against the current repository state before acting.

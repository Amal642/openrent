### Session continuity

After compaction or resume, treat the injected handoff (`docs/handoff-context.md`) as working context, but verify code-state claims against the current repository before acting.

If `docs/handoff-context.md` exists at session start and the current task appears to continue prior work, read it early and verify its claims against the current repository state before acting.

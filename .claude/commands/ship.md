Implement the spec or task in $ARGUMENTS.

Definition of done:
- Code compiles (py_compile passes via hook)
- Lints pass (ruff if available, else skip)
- Tests pass for new behavior (write them if missing)
- Validators pass on any new content (per CLAUDE.md table)
- No TODOs in shipped paths
- deploy_guard snapshot taken before prod-affecting changes
- deploy_guard verify clean after prod-affecting changes

Use TodoWrite if 3+ steps. State assumptions inline; don't ask. Continue
until the list is empty or genuinely blocked.

If hooks flag something during the work, fix it in the same turn. Don't
surface as a question.

If deploy_guard flags any violation (yours or pre-existing), fix it
before declaring done. Per CLAUDE.md, pre-existing violations are part
of the current task.

Output format: when done, list files changed with one-line summaries.
No preamble, no postamble.

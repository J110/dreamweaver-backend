Migrate the content type in $ARGUMENTS from old engine to new engine.

Pre-flight checklist:
1. Read the migration design doc in docs/superpowers/specs/ if it exists
2. Identify the parallel-scripts pattern (per CLAUDE.md)
3. Confirm the new engine is approved (check Audio Engines table in
   CLAUDE.md — don't propose engines outside the approved list)

Implementation:
1. Create new generator script following _*_common.py shared module
   pattern (don't add --lang flags)
2. Don't touch the old engine's call sites until cutover
3. Run validators on output of new engine — must pass before cutover
4. Test with 3-5 generations before declaring complete

Cutover:
1. deploy_guard snapshot
2. Update pipeline_run.py to call new generator
3. Verify daily cron picks up the change
4. deploy_guard verify
5. Monitor first cron run for failures

Hard rules:
- Never use Chatterbox for new English content
- Never use MiniMax v1.5 for Hindi (failed native test)
- Never use Sarvam (failed native test)
- Never use Suno (no official API)

Output: file diffs + migration status + any deferred items.

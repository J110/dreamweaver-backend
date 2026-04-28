Review the last 5 generated $ARGUMENTS for quality and template drift.

Use the content-qa subagent if available; otherwise check inline:

1. Are they structurally diverse?
   - Opening tags rotated (no single tag in 3+ of 5)
   - Comedic devices rotated (no device in 2+ of 5)
   - Settings rotated (no setting in 2+ of 5)
   - Closing patterns vary (not all [laughs together])
   - Length varies (not all clustered around same line count)

2. Did at least 1 of 5 actually feel funny / engaging / memorable?
   (subjective but important — listen if audio exists)

3. Does the metadata accurately describe the content?
   (character_age_dynamic shouldn't always be "siblings", etc.)

4. Validators passing means rules followed — but does the content
   feel formulaic? If 5 sound the same despite passing validation,
   the validator has a gap.

5. Did Mistral converge to a template phrase? Check for:
   - English: "Did you eat my..." openings, "maybe a little bit" admissions
   - Hindi: "Maa ko bataaunga", "tumhare gaal pe", "Daadi aa gayi"
   - Same first-line emotion across multiple shorts

Output: numbered list of issues with file:field references. For each
issue, propose the diff to fix it. Don't apply fixes — that's a
separate task.

A validator failure occurred for $ARGUMENTS.

Workflow:
1. Read the failure message and identify which rule failed
2. Identify whether failure is in: content generation, validator logic,
   or test data
3. Fix the root cause:
   - Generation issue → strengthen Mistral prompt or add explicit
     constraint
   - Validator logic bug → fix the validator (with tests)
   - Test data issue → fix the test data
4. Re-run validator until it passes
5. If novel failure type, add a regression test to
   scripts/test_*_validator.py

Hard rule (per CLAUDE.md): NEVER loosen the validator threshold to make
content pass. Validator changes require explicit user approval and 5+
generation test sample.

If you find yourself wanting to weaken a check, that's the signal that
the generation prompt is wrong. Fix the generator, not the gate.

Output: cause (one line), fix location (file:line), regression test
location if added.

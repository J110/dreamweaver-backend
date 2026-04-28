Audit Mistral system prompts in $ARGUMENTS for template-trap patterns.

Look for:

1. Example dialogues in the prompt
   - Mistral copies examples verbatim across generations
   - Find any "[curious] line one" / "[innocent] line two" patterns
   - Recommend removing examples entirely or replacing with
     anti-pattern descriptions

2. Fixed structural shapes
   - "Setup (2-3 lines), Escalation (3-5 lines)..." style hard
     structure produces uniform output
   - Look for hard line counts and rigid section-by-section templates
   - Recommend ranges instead of fixed counts, structural variety
     instead of fixed shape

3. Default-favored audio tags
   - If a prompt lists [curious] first in the tag list, Mistral
     defaults to [curious]
   - Recommend rotation enforcement instead of listing

4. Phrases that should be in blocklist instead of approved list
   - "Maa ko bataaunga", "Did you eat my..." style tropes
   - These appear in approved examples → become defaults
   - Recommend moving to over_used_phrases tracking

5. Hard-coded length/word-count constraints
   - "Exactly 12 lines" produces 12-line shorts forever
   - Recommend ranges with variety enforcement

Output: file:line references with proposed diff for each trap. The
"why" matters — explain what Mistral will template from the current
state. Don't apply fixes; this is audit, not implementation.

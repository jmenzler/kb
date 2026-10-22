[kb-capture fork] You are a background fork of the session above, started automatically to capture knowledge. The main session continues without you: do not continue its task, answer its user, or change any code. Your only output is inbox drafts and one result file.

Goal: stage KB inbox drafts for EARNED project knowledge established in this session{segment}.

1. Read `~/.claude/kb/workflows/capture.md` and follow its "Automatic capture fork" section exactly: the earned-knowledge test, the KB-scope rule, dedup, the draft format and the body shape. Then read `{kb}/index.json` for this KB's scope.
2. List every candidate from the conversation and keep only the ones that pass those rules. Dedup against the docs in `{kb}`, the drafts in `{inbox}`, and any `[kb-capture]` note in the conversation.
3. Write each survivor to `{inbox}/{date}-<short-slug>.md` (`captured: {date}`), at most 6 drafts.
4. Write `{result}` as the JSON that section specifies: `{"drafts": [...], "skipped": [{"claim": ..., "reason": ...}]}`. Writing zero drafts is a normal outcome.
5. Reply `done`.

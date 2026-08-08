# IMPS

## Code style

Comments: terse. No multi-line prose explaining rationale, no
editorializing. Short inline notes or brief `###`-style section
headers only, matching existing code (see `app/blueprints/*.py`). If
a comment just restates what the code already says, cut it.

Comments describe current-state only. No history ("used to...",
"previously..."), no speculative future-proofing ("in case we later
need to...", "added for future use"). Git history covers the past;
YAGNI covers the future.

---
worth: later
added: 2026-11-03
---
# eval question set grows only by hand

The 31 eval questions were drafted once from past sessions. Every later session where a question
about the projects came up (and its answer location became known) is a free eval candidate that is
lost unless copied into `eval/questions.yaml` by hand.

Idea: mine Claude Code transcripts after the fact for "where/what/how/why did we ..." questions plus
the location the session ended up at, and propose them as candidate `questions.yaml` entries for
review. Either a SessionEnd hook (the same pattern `perf-review-log` already uses) or, simpler, a
batch command over `~/.claude/projects/*/*.jsonl` run before an eval round.

Constraints: transcripts and candidates are private data, so they stay under `$WRAG_HOME` and any
LLM call goes through the isolated generator config; candidates are never added unreviewed, since
gold answers must stay fixed while measuring and a growing set changes the question-set hash.

Unknown that settles the value: whether the set is still too small or too skewed after the
hybrid-search change, which already plans to widen it by hand with what/how/why questions.
If one manual pass over recent sessions yields many good questions, automating it is worth it.

---
worth: later
where: src/wrag/cli.py:67
added: 2026-11-03
---
# index goes stale silently between manual `wrag index` runs

The index changes only when `wrag index` is run by hand; the baseline design deferred scheduling
("run by hand or by cron") and nothing sets one up. `wrag ask` opens whatever index exists without
checking it against the projects, so answers about recent edits or commits miss with no hint why.

Two options, either as its own change:
- a launchd agent (or cron) running `wrag index` periodically; it needs Ollama up for embeddings and
  writes the private index unattended;
- a cheap staleness check in `wrag ask`: compare each project's commit cursor with its HEAD (and
  maybe tracked-file mtimes with `files.mtime`) and print a one-line "index is behind" warning.

Unknown that settles the value: whether a stale index actually causes wrong or missing answers in
practice, or whether running `wrag index` before asking is habit enough. One real miss traced to
staleness makes it a `yes` (the warning first, it is the smaller change).

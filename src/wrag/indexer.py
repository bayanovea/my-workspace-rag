"""`wrag index`: bring the index in line with the allowlisted projects, incrementally."""

import hashlib
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

from wrag import chunk, corpus
from wrag.config import Config, Project
from wrag.embed import Embedder
from wrag.errors import WragError
from wrag.redact import redact
from wrag.store import Store

COMMIT_BATCH = 64


@dataclass
class Report:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    commits: int = 0
    redactions: int = 0
    skipped_files: list[corpus.Skipped] = field(default_factory=list)

    def line(self) -> str:
        return (
            f"+{self.added} added, {self.updated} updated, {self.deleted} deleted, "
            f"{self.skipped} skipped, {self.commits} commits, {self.redactions} redactions"
        )


def rebuild_reason(store: Store, embedder: Embedder) -> str | None:
    model, version = store.get_meta("embed_model"), store.get_meta("chunker_version")
    if model is None and version is None:
        return None
    if model != embedder.model:
        return f"embedding model changed ({model} -> {embedder.model})"
    if version != chunk.CHUNKER_VERSION:
        return f"chunker version changed ({version} -> {chunk.CHUNKER_VERSION})"
    return None


def run(
    cfg: Config, store: Store, embedder: Embedder, full: bool = False, log=print
) -> dict[str, Report]:
    reason = "full rebuild requested" if full else rebuild_reason(store, embedder)
    if reason:
        log(f"rebuilding the whole index: {reason}")
        store.reset()
    store.set_meta("embed_model", embedder.model)
    store.set_meta("chunker_version", chunk.CHUNKER_VERSION)

    listed = {p.name for p in cfg.projects}
    for gone in sorted(store.projects() - listed):
        log(f"{gone}: no longer in the config, removing its chunks")
        store.drop_project(gone)
    store.commit()

    reports = {}
    for project in cfg.projects:
        if not project.path.is_dir():
            raise WragError(f"project {project.name}: {project.path} is not a directory")
        reports[project.name] = index_project(cfg, store, embedder, project)
        store.commit()
    return reports


def index_project(cfg: Config, store: Store, embedder: Embedder, project: Project) -> Report:
    report = Report()
    files, skipped = corpus.select(project, cfg.max_file_bytes)
    report.skipped, report.skipped_files = len(skipped), skipped
    known = store.file_hashes(project.name)

    for f in files:
        data = f.abs.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if known.get(f.rel) == sha:
            continue
        text, n = redact(data.decode("utf-8", errors="replace"))
        report.redactions += n
        mtime = f.abs.stat().st_mtime
        make = chunk.doc_chunks if f.kind == "doc" else chunk.manifest_chunks
        chunks = make(project.name, f.rel, text, mtime, cfg.max_chunk_chars)
        vectors = embedder.embed([c.embed_text() for c in chunks]) if chunks else []
        store.put_file(project.name, f.rel, sha, mtime, chunks, vectors)
        if f.rel in known:
            report.updated += 1
        else:
            report.added += 1

    for rel in set(known) - {f.rel for f in files}:
        store.delete_file(project.name, rel)
        report.deleted += 1

    if corpus.is_git(project.path):
        index_commits(store, embedder, project, report)
    return report


def index_commits(store: Store, embedder: Embedder, project: Project, report: Report) -> None:
    head = _git(project.path, "rev-parse", "--verify", "-q", "HEAD")
    if head is None:
        return  # no commits yet
    cursor = store.get_cursor(project.name)
    if cursor and _git(project.path, "merge-base", "--is-ancestor", cursor, "HEAD") is None:
        store.drop_commits(project.name)  # history was rewritten
        cursor = None
    if cursor == head:
        return

    commits = [
        c
        for c in chunk.commits_since(project.path, cursor)
        if not c.files or not all(corpus.is_excluded(f, project.exclude) for f in c.files)
    ]
    for i in range(0, len(commits), COMMIT_BATCH):
        chunks = []
        for c in commits[i : i + COMMIT_BATCH]:
            message, n = redact(c.message)
            report.redactions += n
            chunks.append(chunk.commit_chunk(project.name, replace(c, message=message)))
        store.add_chunks(chunks, embedder.embed([c.embed_text() for c in chunks]))
    report.commits = len(commits)
    store.set_cursor(project.name, head)


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

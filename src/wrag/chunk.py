"""Splitting docs, manifests and commits into chunks."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Bump whenever chunk boundaries or embedded text change: a mismatch forces a full rebuild.
CHUNKER_VERSION = "1"
MAX_COMMIT_FILES = 50
SHORT_HASH = 12

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class Chunk:
    project: str
    path: str  # file path relative to the project root, or the short hash for a commit
    kind: str  # "doc" | "manifest" | "commit"
    heading: str  # heading path for docs, subject for commits
    text: str
    mtime: float
    files: tuple[str, ...] = ()  # changed paths, commits only

    def embed_text(self) -> str:
        where = " / ".join(p for p in (self.project, self.path, self.heading) if p)
        return f"{where}\n{self.text}"


def split_markdown(text: str, max_chars: int) -> list[tuple[str, str]]:
    """Returns (heading path, body) pairs; text before the first heading has an empty path."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    stack: list[tuple[int, str]] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else HEADING.match(line)
        if m:
            level = len(m.group(1))
            stack = [(lvl, title) for lvl, title in stack if lvl < level] + [(level, m.group(2))]
            sections.append((" > ".join(title for _, title in stack), []))
        else:
            sections[-1][1].append(line)
    result = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        result += [(heading, part) for part in split_long(body, max_chars)]
    return result


def split_long(text: str, max_chars: int) -> list[str]:
    """Packs paragraphs into parts of at most max_chars; oversized paragraphs split by lines."""
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    pieces = []
    for para in re.split(r"\n\s*\n", text):
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        for line in para.splitlines():
            pieces += [line[i : i + max_chars] for i in range(0, len(line), max_chars)] or [""]
    parts, current = [], ""
    for piece in pieces:
        joined = f"{current}\n\n{piece}" if current else piece
        if len(joined) <= max_chars:
            current = joined
        else:
            parts.append(current)
            current = piece
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def doc_chunks(project: str, rel: str, text: str, mtime: float, max_chars: int) -> list[Chunk]:
    return [
        Chunk(project, rel, "doc", heading, body, mtime)
        for heading, body in split_markdown(text, max_chars)
    ]


def manifest_chunks(project: str, rel: str, text: str, mtime: float, max_chars: int) -> list[Chunk]:
    # Whole file when it fits: dependency names are exact tokens and should stay together.
    lines = text.strip().splitlines()
    parts, current = [], ""
    for line in lines:
        joined = f"{current}\n{line}" if current else line
        if len(joined) > max_chars and current:
            parts.append(current)
            current = line
        else:
            current = joined
    if current:
        parts.append(current)
    return [Chunk(project, rel, "manifest", "", part, mtime) for part in parts]


@dataclass(frozen=True)
class Commit:
    hash: str
    short: str
    time: float
    message: str
    files: tuple[str, ...]


RECORD, FIELD = "\x1e", "\x1f"


def commits_since(root: Path, cursor: str | None) -> list[Commit]:
    rev = f"{cursor}..HEAD" if cursor else "HEAD"
    out = subprocess.run(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "log",
            "--relative",
            "--name-only",
            f"--format={RECORD}%H{FIELD}%ct{FIELD}%B{FIELD}",
            rev,
            "--",
            ".",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    commits = []
    for record in out.split(RECORD)[1:]:
        full, ts, message, names = record.split(FIELD)
        files = tuple(n for n in names.strip().splitlines() if n)
        # A fixed length keeps citations stable as the repository grows (%h does not).
        commits.append(Commit(full, full[:SHORT_HASH], float(ts), message.strip(), files))
    return commits


def commit_chunk(project: str, commit: Commit) -> Chunk:
    subject = commit.message.splitlines()[0] if commit.message else ""
    shown = list(commit.files[:MAX_COMMIT_FILES])
    if len(commit.files) > MAX_COMMIT_FILES:
        shown.append(f"... and {len(commit.files) - MAX_COMMIT_FILES} more")
    text = commit.message + ("\n\nFiles:\n" + "\n".join(shown) if shown else "")
    return Chunk(project, commit.short, "commit", subject, text, commit.time, commit.files)

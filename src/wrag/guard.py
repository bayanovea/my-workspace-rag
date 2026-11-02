"""Commit-time leak guard: rejects staged content naming private projects, paths or strings."""

import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from wrag.config import Config
from wrag.errors import WragError

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class Needle:
    value: str
    label: str  # printed instead of the value, so guard output is safe to paste anywhere


@dataclass(frozen=True)
class Finding:
    where: str
    line: int
    label: str

    def __str__(self) -> str:
        loc = f"{self.where}:{self.line}" if self.line else self.where
        return f"{loc}: matches {self.label}"


def needles(cfg: Config, home_dir: Path | None = None) -> list[Needle]:
    if not cfg.denylist_file.exists():
        raise WragError(
            f"leak guard: denylist {cfg.denylist_file} is missing; create it with one private "
            "string per line (project names, hostnames, people) before committing"
        )
    result = []
    entries = [ln.strip() for ln in cfg.denylist_file.read_text().splitlines()]
    entries = [e for e in entries if e and not e.startswith("#")]
    result += [Needle(e, f"denylist entry #{i}") for i, e in enumerate(entries, 1)]
    for i, p in enumerate(cfg.projects, 1):
        result.append(Needle(p.name, f"project name #{i}"))
        result.append(Needle(str(p.path), f"project path #{i}"))
    result.append(Needle(str(home_dir or Path.home()), "home directory path"))
    return result


def scan(lines: Iterable[tuple[str, int, str]], found: list[Needle]) -> list[Finding]:
    lowered = [(n.value.lower(), n.label) for n in found]
    return [
        Finding(where, lineno, label)
        for where, lineno, text in lines
        for value, label in lowered
        if value in text.lower()
    ]


def staged_lines(repo: Path) -> list[tuple[str, int, str]]:
    names = _git(repo, "diff", "--cached", "--name-only", "-z").split("\0")
    lines = [(name, 0, name) for name in names if name]
    diff = _git(
        repo, "-c", "core.quotePath=false", "diff", "--cached", "-U0", "--no-color", "--no-ext-diff"
    )
    path, lineno = "", 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else raw[4:]
        elif m := HUNK.match(raw):
            lineno = int(m.group(1))
        elif raw.startswith("+"):
            lines.append((path, lineno, raw[1:]))
            lineno += 1
    return lines


def message_lines(msg_file: Path) -> list[tuple[str, int, str]]:
    return [
        ("commit message", i, text)
        for i, text in enumerate(msg_file.read_text().splitlines(), 1)
        if not text.startswith("#")
    ]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        raise WragError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout

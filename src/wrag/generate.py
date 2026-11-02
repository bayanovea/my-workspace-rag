"""Answer generation through the Claude Code CLI, isolated from the user's normal setup."""

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from wrag.errors import WragError
from wrag.retrieve import Hit

SYSTEM_PROMPT = """\
You locate things in a set of local software projects. You get a question and numbered chunks \
retrieved from the projects' docs, dependency manifests and git commits.

Rules:
- Answer only from the chunks. Never use outside knowledge about where something might be.
- Every place you name must be backed by the id of a chunk that shows it, listed in citations.
- If the chunks do not contain the answer, set found to false, give no citations, and say briefly \
what you looked for.
- Answer in the language of the question, in one to three sentences, naming project and path or \
commit.
"""

CYRILLIC = re.compile("[а-яё]", re.IGNORECASE)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["found", "answer", "citations"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Answer:
    found: bool
    text: str
    citations: tuple[str, ...]  # chunk ids as sent: "c1", "c2", ...


class Generator(Protocol):
    model: str

    def generate(self, prompt: str) -> Answer: ...


def chunk_ids(hits: list[Hit]) -> list[str]:
    return [f"c{i}" for i in range(1, len(hits) + 1)]


def build_prompt(question: str, hits: list[Hit]) -> str:
    parts = [f"Question: {question}", "", "Chunks:"]
    for cid, h in zip(chunk_ids(hits), hits, strict=True):
        c = h.chunk
        date = datetime.fromtimestamp(c.mtime, UTC).date().isoformat()
        where = f"commit {c.path}" if c.kind == "commit" else f"path {c.path}"
        section = f' section "{c.heading}"' if c.heading and c.kind == "doc" else ""
        parts += ["", f"[{cid}] project {c.project}, {where}{section}, {c.kind}, {date}", c.text]
    # Named explicitly: "the language of the question" drew German answers to English questions.
    language = "Russian" if CYRILLIC.search(question) else "English"
    parts += ["", f"Write the answer in {language}."]
    return "\n".join(parts)


def answer(generator: Generator, question: str, hits: list[Hit]) -> tuple[Answer, list[Hit]]:
    """Runs the generator and keeps only citations of chunks it was actually given."""
    raw = generator.generate(build_prompt(question, hits))
    by_id = dict(zip(chunk_ids(hits), hits, strict=True))
    valid = tuple(dict.fromkeys(c for c in raw.citations if c in by_id))
    if not raw.found or not valid:
        return Answer(False, raw.text, ()), []
    return Answer(True, raw.text, valid), [by_id[c] for c in valid]


class ClaudeCLI:
    def __init__(self, config_dir: Path, model: str, timeout: float, binary: str = "claude"):
        self.config_dir, self.model, self.timeout, self.binary = config_dir, model, timeout, binary

    def command(self) -> list[str]:
        return [
            self.binary,
            "-p",
            "--model",
            self.model,
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-session-persistence",
            "--system-prompt",
            SYSTEM_PROMPT,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(ANSWER_SCHEMA),
        ]

    def generate(self, prompt: str) -> Answer:
        if not self.config_dir.is_dir():
            raise WragError(self._login_hint("the isolated Claude Code config dir does not exist"))
        # A dedicated config dir has no hooks, plugins, MCP servers or user CLAUDE.md; an empty cwd
        # plus --setting-sources "" keeps project and ancestor CLAUDE.md files out of the context.
        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.config_dir)}
        env.pop("ANTHROPIC_API_KEY", None)
        with tempfile.TemporaryDirectory(prefix="wrag-gen-") as cwd:
            try:
                result = subprocess.run(
                    self.command(),
                    input=prompt,
                    cwd=cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
            except FileNotFoundError as e:
                raise WragError(f"{self.binary!r} not found; install Claude Code") from e
            except subprocess.TimeoutExpired as e:
                raise WragError(f"generator timed out after {self.timeout:.0f}s") from e
        return parse_output(result.returncode, result.stdout, result.stderr, self._login_hint)

    def _login_hint(self, reason: str) -> str:
        return (
            f"{reason}; log in once with: CLAUDE_CONFIG_DIR={self.config_dir} {self.binary} "
            "(then /login)"
        )


def parse_output(code: int, stdout: str, stderr: str, login_hint) -> Answer:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        envelope = None
    if not isinstance(envelope, dict):
        detail = (stderr or stdout).strip()[:300]
        if "login" in detail.lower() or "auth" in detail.lower():
            raise WragError(login_hint("the generator is not logged in"))
        raise WragError(f"generator returned unparsable output (exit {code}): {detail}")
    if envelope.get("is_error") or code != 0:
        detail = str(envelope.get("result") or stderr).strip()[:300]
        if "login" in detail.lower() or "auth" in detail.lower():
            raise WragError(login_hint("the generator is not logged in"))
        raise WragError(f"generator failed (exit {code}): {detail}")

    payload = envelope.get("structured_output")
    if payload is None:
        try:
            payload = json.loads(envelope.get("result") or "")
        except json.JSONDecodeError as e:
            raise WragError("generator answer does not match the expected JSON shape") from e
    try:
        return Answer(
            bool(payload["found"]),
            str(payload["answer"]),
            tuple(str(c) for c in payload["citations"]),
        )
    except (KeyError, TypeError) as e:
        raise WragError("generator answer does not match the expected JSON shape") from e


class FakeGenerator:
    """Returns a fixed answer and records the prompts it saw."""

    model = "fake"

    def __init__(self, reply: Answer | Exception):
        self.reply, self.prompts = reply, []

    def generate(self, prompt: str) -> Answer:
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

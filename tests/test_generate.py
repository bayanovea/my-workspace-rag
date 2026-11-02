import json
import stat

import pytest

from wrag import generate
from wrag.chunk import Chunk
from wrag.errors import WragError
from wrag.generate import Answer, ClaudeCLI, FakeGenerator
from wrag.retrieve import Hit

HITS = [
    Hit(1, 0.9, Chunk("alpha", "docs/plans/rate-limit.md", "doc", "Plan > Approach", "bucket", 0)),
    Hit(2, 0.8, Chunk("alpha", "0123456789ab", "commit", "Add limiter", "msg", 0, ("go.mod",))),
]


def test_prompt_numbers_chunks_with_their_location():
    prompt = generate.build_prompt("where is rate limiting?", HITS)
    assert prompt.startswith("Question: where is rate limiting?")
    assert (
        '[c1] project alpha, path docs/plans/rate-limit.md section "Plan > Approach", doc' in prompt
    )
    assert "[c2] project alpha, commit 0123456789ab, commit" in prompt


def test_valid_citations_are_kept_and_mapped_to_hits():
    ans, cited = generate.answer(
        FakeGenerator(Answer(True, "in alpha", ("c2", "c1", "c2"))), "q", HITS
    )
    assert ans == Answer(True, "in alpha", ("c2", "c1"))
    assert [h.id for h in cited] == [2, 1]


def test_invented_citation_is_dropped():
    ans, cited = generate.answer(FakeGenerator(Answer(True, "x", ("c1", "c9"))), "q", HITS)
    assert ans.citations == ("c1",)
    assert [h.id for h in cited] == [1]


def test_found_without_any_valid_citation_becomes_not_found():
    ans, cited = generate.answer(FakeGenerator(Answer(True, "made up", ("c7",))), "q", HITS)
    assert (ans.found, ans.citations, cited) == (False, (), [])


def test_not_found_carries_no_citations():
    ans, cited = generate.answer(FakeGenerator(Answer(False, "nothing", ("c1",))), "q", HITS)
    assert (ans.found, ans.citations, cited) == (False, (), [])


def envelope(**kw):
    return json.dumps({"type": "result", "is_error": False, **kw})


def hint(reason):
    return f"{reason}; log in"


def test_parse_structured_output():
    out = envelope(structured_output={"found": True, "answer": "a", "citations": ["c1"]})
    assert generate.parse_output(0, out, "", hint) == Answer(True, "a", ("c1",))


def test_parse_json_in_result_text():
    out = envelope(result=json.dumps({"found": False, "answer": "no", "citations": []}))
    assert generate.parse_output(0, out, "", hint) == Answer(False, "no", ())


@pytest.mark.parametrize(
    ("code", "stdout", "stderr", "match"),
    [
        (
            1,
            envelope(is_error=True, result="Not logged in. Please run /login"),
            "",
            "not logged in",
        ),
        (1, "", "Invalid API key. Please run /login", "not logged in"),
        (0, "garbage", "", "unparsable"),
        (0, envelope(result="plain prose"), "", "JSON shape"),
        (0, envelope(structured_output={"found": True}), "", "JSON shape"),
    ],
)
def test_parse_failures_are_explained(code, stdout, stderr, match):
    with pytest.raises(WragError, match=match):
        generate.parse_output(code, stdout, stderr, hint)


def fake_claude(tmp_path, body):
    script = tmp_path / "claude"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_cli_runs_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-pass")
    config_dir = tmp_path / "claude-config"
    config_dir.mkdir()
    seen = tmp_path / "seen"
    # The fake records what it saw: stdin, config dir, cwd contents, API key presence and argv.
    binary = fake_claude(
        tmp_path,
        (
            f'cat > "{seen}.stdin"\n'
            f'echo "$CLAUDE_CONFIG_DIR|$(ls -A | wc -l | tr -d " ")|${{ANTHROPIC_API_KEY:-none}}" '
            f'> "{seen}.env"\n'
            f'printf "%s\\n" "$@" > "{seen}.argv"\n'
            'echo \'{"is_error":false,"structured_output":'
            '{"found":false,"answer":"none","citations":[]}}\''
        ),
    )
    ans = ClaudeCLI(config_dir, "sonnet", 10, binary=binary).generate("the prompt")
    assert ans == Answer(False, "none", ())
    assert (tmp_path / "seen.stdin").read_text() == "the prompt"
    assert (tmp_path / "seen.env").read_text().strip() == f"{config_dir}|0|none"
    argv = (tmp_path / "seen.argv").read_text()
    assert (
        "\n--tools\n\n--strict-mcp-config\n--setting-sources\n\n--no-session-persistence\n" in argv
    )
    assert "\n--model\nsonnet\n" in argv


def test_cli_timeout(tmp_path):
    (tmp_path / "cfg").mkdir()
    binary = fake_claude(tmp_path, "sleep 5")
    with pytest.raises(WragError, match="timed out"):
        ClaudeCLI(tmp_path / "cfg", "sonnet", 0.3, binary=binary).generate("p")


def test_cli_missing_config_dir_tells_how_to_log_in(tmp_path):
    with pytest.raises(WragError, match="CLAUDE_CONFIG_DIR=.* claude"):
        ClaudeCLI(tmp_path / "missing", "sonnet", 1).generate("p")


def test_prompt_names_the_answer_language():
    assert generate.build_prompt("где лимиты?", HITS).endswith("Write the answer in Russian.")
    assert generate.build_prompt("where are limits?", HITS).endswith("Write the answer in English.")

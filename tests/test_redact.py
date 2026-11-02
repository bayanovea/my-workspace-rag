import re

import pytest

from wrag.redact import redact

# Token-shaped values are assembled at runtime so no literal secret lands in the repository.
CASES = [
    ("private-key", "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----"),
    ("aws-key", "AKIA" + "ABCDEFGHIJKLMNOP"),
    ("github-token", "ghp_" + "x" * 36),
    ("github-token", "github_pat_" + "A" * 30),
    ("gitlab-token", "glpat-" + "a" * 20),
    ("slack-token", "xoxb-" + "1234567890-abc"),
    ("api-key", "sk-" + "ant-" + "a" * 30),
    ("jwt", "eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + "." + "c" * 12),
]


@pytest.mark.parametrize(("kind", "secret"), CASES)
def test_pattern_is_redacted(kind, secret):
    text, n = redact(f"before {secret} after")
    assert n == 1
    assert text == f"before [REDACTED:{kind}] after"


@pytest.mark.parametrize(
    "line",
    [
        "DB_PASSWORD=hunter2hunter2",
        "api_key: 'abcdef123456'",
        'client_secret = "s3cr3tvalue"',
        "GITHUB_TOKEN=abcdefgh1234",
    ],
)
def test_assignment_value_is_redacted_and_key_kept(line):
    text, n = redact(line)
    assert n == 1
    key = re.split(r"\s*[:=]", line)[0]
    assert text.startswith(key)
    assert "[REDACTED:assignment]" in text


@pytest.mark.parametrize(
    "line",
    [
        "password = os.environ['DB_PASSWORD']",
        "token: ${GITHUB_TOKEN}",
        "the token is stored in the keychain",
        "token_count = 123456789",
        "secretary: Jane Doe-Smithson",
        "password: ********",
        "use sk-learn for this",
        "short: api_key=abc",
    ],
)
def test_look_alikes_survive(line):
    assert redact(line) == (line, 0)

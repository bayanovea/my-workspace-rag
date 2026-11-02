"""Secret redaction applied to every text before it is embedded or stored."""

import re

# Key-value assignments keep the key and lose the value. The value must end at whitespace, a quote
# or punctuation, so references like os.environ["X"] or ${TOKEN} are left alone.
ASSIGNMENT = re.compile(
    r"(?i)\b(\w*(?:password|passwd|secret|token|api[_-]?key))\b(\s*[:=]\s*)(['\"]?)"
    r"([A-Za-z0-9_\-+/=.]{8,})(?=['\"\s,;]|$)"
)
PATTERNS = [
    (
        "private-key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"),
    ),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
]


def redact(text: str) -> tuple[str, int]:
    """Returns the redacted text and the number of secrets replaced."""
    total = 0
    for kind, pattern in PATTERNS:
        text, n = pattern.subn(f"[REDACTED:{kind}]", text)
        total += n
    text, n = ASSIGNMENT.subn(r"\1\2\3[REDACTED:assignment]", text)
    return text, total + n

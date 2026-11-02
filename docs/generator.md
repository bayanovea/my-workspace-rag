# Generator: isolated `claude -p`

`wrag ask` and `wrag eval --with-answers` get their answers from the Claude Code CLI on a subscription
login, not from the API. The user's normal Claude Code setup (hooks, plugins, MCP servers, global
`CLAUDE.md`, memory) must not touch those calls, so they run under a separate config directory.

## One-time login

```sh
mkdir -p ~/.config/workspace-rag/claude
cd /tmp
CLAUDE_CONFIG_DIR=~/.config/workspace-rag/claude claude
```

Choose "Claude account with subscription", finish the browser login, then `/exit`. Your main Claude
Code login is not affected. Check either one with `claude auth status` (prefix
`CLAUDE_CONFIG_DIR=...` for the isolated one).

If `WRAG_HOME` is set, the directory is `$WRAG_HOME/claude` instead.

## The call

```
CLAUDE_CONFIG_DIR=$WRAG_HOME/claude claude -p --model <model> \
  --tools "" --strict-mcp-config --setting-sources "" --no-session-persistence \
  --system-prompt <wrag's prompt> --output-format json --json-schema <answer schema>
```

The prompt goes in on stdin, the working directory is a fresh empty temp dir, and
`ANTHROPIC_API_KEY` is removed from the environment.

| Flag / setting | Why |
|---|---|
| `CLAUDE_CONFIG_DIR` | No user hooks, plugins, MCP servers, `CLAUDE.md` or memory exist there |
| empty temp cwd | No project `CLAUDE.md` |
| `--setting-sources ""` | Without it, a `CLAUDE.md` in an *ancestor* of the cwd is loaded and obeyed |
| `--tools ""` | The model can only read what it is given; it cannot open files itself |
| `--strict-mcp-config` | No MCP servers, even if the isolated config ever gains some |
| `--no-session-persistence` | No transcripts of private chunks written to disk |
| `--system-prompt` | Replaces Claude Code's default agent prompt |
| `--json-schema` | The answer arrives as `structured_output`: `{found, answer, citations}` |

## Verified (Claude Code 2.1.309)

- Subscription login works under a custom `CLAUDE_CONFIG_DIR`; `--bare` would need an API key.
- The `system/init` event of `--output-format stream-json --verbose` lists no tools and no MCP
  servers; only Claude Code's built-in plugins load.
- A canary `CLAUDE.md` in the parent of the cwd was obeyed without `--setting-sources ""` and ignored
  with it.
- None of the user's hooks fired (no side effects in the files they write).
- `--json-schema` output is returned in the `structured_output` field of the result envelope (also
  as JSON text in `result`; `wrag` accepts either).
- Latency with 8 chunks of ~1 KB: 4-6 s per call.
- English questions sometimes get German answers. "Answer in the language of the question" in the
  system prompt gave 2 of 31 in an eval run; naming the language at the end of the user prompt
  ("Write the answer in English.") brought it to 1 of 31, not to zero. Unresolved.

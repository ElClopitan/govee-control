# Claude Code Hook for Agent Signal

This document shows how to configure Claude Code hooks to trigger the Govee
light signal when an agent needs input, and clear it when the user responds.

## Hook Events

- **Notification**: Fires when Claude Code sends a notification (e.g., when an
  agent is waiting for user input). Use this to turn on the signal light.
- **UserPromptSubmit**: Fires when the user submits a prompt. Use this to clear
  the signal light.

## Configuration

Add the following to your Claude Code settings file (`~/.claude/settings.json`
for global, or `.claude/settings.json` for project-specific):

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "python C:/path/to/govee-control/agent_signal.py needs-input" }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "python C:/path/to/govee-control/agent_signal.py clear" }
        ]
      }
    ]
  }
}
```

Replace `C:/path/to/govee-control` with the folder where you cloned this repo (forward slashes).

If your settings.json already has a `hooks` key, merge these two events into it instead of adding a second `hooks` key.

## How It Works

1. When an agent needs input, Claude Code sends a notification. The `Notification`
   hook fires and runs `agent_signal.py needs-input`, which turns the lights to the
   configured signal colour (default: orange `#ff6a00`). Each session writes a
   marker file to `state/signal_sessions/<session_id>` so the signal can be
   tracked per session.

2. When the user submits a prompt (responding to the agent), the `UserPromptSubmit`
   hook fires and runs `agent_signal.py clear`, which removes that session's
   marker. If other sessions still have active markers, the lights stay orange.
   When the last session's marker is removed, the lights are restored to their
   previous state.

If multiple Claude sessions are running and one raises the signal while another
is idle, the idle session's prompt submission will not clear the signal — only
the session that raised it (or `clear --all`) can.

## Notes

- The signal colour and behaviour are configured in `config.json` under the
  `signal` key. See `config.example.json` for the schema.
- If `signal.blink` is set to `true`, the lights will blink 3 times before
  staying on.
- The hook commands run asynchronously and do not block Claude Code.
- Make sure `python` is on your PATH, or use the full path to the Python
  executable.

## Unattended Sessions

By default, `needs-input` ignores unattended/background Claude sessions (those
with `CLAUDE_CODE_SESSION_ATTENDED=0` in their environment). This prevents the
lights from turning orange when a background dispatcher session goes idle.

To include unattended sessions, set `signal.include_unattended` to `true` in
`config.json`. You can also use the `--force` flag on the command line to
override the check for a single invocation.

## Logging

Every `needs-input` and `clear` call is logged to `state/signal.log` with an
ISO timestamp, the command, the action taken (applied, skipped-unattended,
no-signal, etc.), and the session ID and message from the hook input if
available. The log is automatically truncated to its last 100 lines when it
exceeds 200 KB.

## Reference

- Claude Code Hooks documentation: https://code.claude.com/docs/en/hooks
- Hooks guide: https://code.claude.com/docs/en/hooks-guide

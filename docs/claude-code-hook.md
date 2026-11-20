# Claude Code Hook for Agent Signal

This document shows how to configure Claude Code hooks to trigger the Govee
light signal when an agent needs input, and clear it when the user responds.

## Hook Events

- **Notification**: Fires when Claude Code sends a notification (e.g., when an
  agent is waiting for user input). Use this to turn on the signal light.
- **UserPromptSubmit**: Fires when the user submits a prompt. Use this to clear
  the signal light.
- **SessionEnd**: Fires when a Claude session ends. Use this to clear the signal
  light if the session ended while waiting for input (so the lights don't stay
  orange after the session is gone).

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
    ],
    "SessionEnd": [
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

3. When a Claude session ends (e.g., the user closes it while the agent was
   waiting), the `SessionEnd` hook fires and runs `agent_signal.py clear`. This
   removes the session's marker so the lights don't stay orange after the session
   is gone. Without this, a session that ends while waiting would leave its
   marker behind until it expired (after 2 hours by default).

If multiple Claude sessions are running and one raises the signal while another
is idle, the idle session's prompt submission will not clear the signal — only
the session that raised it (or `clear --all`) can.

To manually reset the lights at any time, run `python agent_signal.py clear --all`.

## Off Mode Suppresses the Signal

When the mode is `off` (set via `python mode.py set off`), the agent signal is
suppressed: `needs-input` hooks return immediately without turning the strips
orange. This means the lights stay dark when the owner has explicitly switched
them off. The signal works normally in `weather`, `game`, and `music` modes.
The `--force` flag does not bypass this.

## Stale Markers

Each session marker records the PID of the Claude Code process that created it.
A marker is considered stale if its PID is no longer alive (the process died
without running its SessionEnd hook) or if it is older than the configured max
age (2 hours by default). Stale markers are automatically deleted when any
`needs-input` or `clear` command runs, so a session that crashes or is killed
won't keep the lights orange indefinitely.

You can also manually sweep stale markers with `python agent_signal.py clear --stale`.
This deletes all stale markers and, if no active markers remain, restores the
lights to their previous state. The weather and game sync loops call this sweep
periodically (at most once every 60 seconds) while they are blocked by an active
signal, so the lights will clear automatically even if no one runs a manual
clear.

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

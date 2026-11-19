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

If your settings.json already has a `hooks` key, merge these two events into it instead of adding a second `hooks` key.

## How It Works

1. When an agent needs input, Claude Code sends a notification. The `Notification`
   hook fires and runs `agent_signal.py needs-input`, which turns the lights to the
   configured signal colour (default: orange `#ff6a00`).

2. When the user submits a prompt (responding to the agent), the `UserPromptSubmit`
   hook fires and runs `agent_signal.py clear`, which restores the lights to their
   previous state.

## Notes

- The signal colour and behaviour are configured in `config.json` under the
  `signal` key. See `config.example.json` for the schema.
- If `signal.blink` is set to `true`, the lights will blink 3 times before
  staying on.
- The hook commands run asynchronously and do not block Claude Code.
- Make sure `python` is on your PATH, or use the full path to the Python
  executable.

## Reference

- Claude Code Hooks documentation: https://code.claude.com/docs/en/hooks
- Hooks guide: https://code.claude.com/docs/en/hooks-guide

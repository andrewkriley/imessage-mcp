# imessage-mcp

An MCP (Model Context Protocol) server that exposes Apple iMessage as tools for AI assistants — read conversations, search messages, and send iMessages directly from Claude.

## Requirements

| Requirement | Notes |
|---|---|
| macOS | Uses `chat.db` and AppleScript — no Linux/Windows support |
| Python 3.9+ | Standard library + `mcp` package |
| Messages app | Must be open and signed in for sending messages |
| Full Disk Access | Required to read `chat.db` (see Permissions below) |

## Quick setup

```bash
git clone https://github.com/<your-username>/imessage-mcp
cd imessage-mcp
./setup.sh
```

The setup script will:
- Verify all prerequisites (macOS, Python version, `chat.db` access)
- Create a `.venv` and install dependencies
- Print the exact config snippet to add to Claude Desktop or Claude Code

## Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Connecting to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "imessage": {
      "command": "/path/to/imessage-mcp/.venv/bin/imessage-mcp"
    }
  }
}
```

Restart Claude Desktop after saving.

## Connecting to Claude Code (CLI)

```bash
claude mcp add imessage /path/to/imessage-mcp/.venv/bin/imessage-mcp
```

## Permissions

Two macOS permissions are required:

**1. Full Disk Access**

`chat.db` is protected by macOS privacy controls. Grant Full Disk Access to:
- Your terminal app (Terminal, iTerm2, Ghostty, etc.)
- Claude Desktop (if using the desktop app)

> System Settings → Privacy & Security → Full Disk Access → click `+`

**2. Automation (AppleScript)**

The `send_imessage` tool drives the Messages app via AppleScript. macOS will show a permission prompt the first time — click **Allow**. If you previously denied it:

> System Settings → Privacy & Security → Automation → enable Messages for your terminal / Claude

## Available tools

| Tool | Description |
|---|---|
| `send_imessage` | Send an iMessage or SMS to a phone number or Apple ID |
| `list_imessage_conversations` | List recent conversations sorted by activity |
| `get_imessage_messages` | Fetch messages from a specific conversation |
| `search_imessages` | Full-text search across all conversations |
| `get_unread_imessages` | Return all unread incoming messages |

## How it works

- **Reading** — copies `~/Library/Messages/chat.db` to a temp file before querying (the live DB is often locked by `imagent`)
- **Sending** — uses AppleScript to drive the Messages app; requires Messages to be open

## License

MIT

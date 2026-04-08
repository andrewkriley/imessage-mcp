#!/usr/bin/env bash
# setup.sh — imessage-mcp setup and dependency checker
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}[ok]${RESET}  $*"; }
warn() { echo -e "${YELLOW}[warn]${RESET} $*"; }
fail() { echo -e "${RED}[fail]${RESET} $*"; }
info() { echo -e "      $*"; }

echo
echo -e "${BOLD}imessage-mcp setup${RESET}"
echo "────────────────────────────────────────"

# ── 1. Platform ──────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}Checking prerequisites...${RESET}"

if [[ "$(uname)" != "Darwin" ]]; then
    fail "macOS required — this server relies on Apple's Messages app and chat.db"
    exit 1
fi
ok "macOS detected"

# ── 2. Python ────────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    fail "python3 not found"
    info "Install via Homebrew:  brew install python"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
REQUIRED_MAJOR=3
REQUIRED_MINOR=9

if python3 -c "import sys; sys.exit(0 if sys.version_info >= ($REQUIRED_MAJOR, $REQUIRED_MINOR) else 1)"; then
    ok "Python $PYTHON_VERSION (>= 3.9 required)"
else
    fail "Python $PYTHON_VERSION found, but >= 3.9 is required"
    info "Install a newer version:  brew install python"
    exit 1
fi

# ── 3. Full Disk Access (via chat.db read test) ───────────────────────────────
CHAT_DB="$HOME/Library/Messages/chat.db"
FDA_OK=false

if [[ ! -f "$CHAT_DB" ]]; then
    warn "Full Disk Access — chat.db not found at $CHAT_DB"
    info "This is expected if Messages has never been set up on this Mac."
elif sqlite3 "$CHAT_DB" "SELECT count(*) FROM sqlite_master;" &>/dev/null 2>&1; then
    ok "Full Disk Access — chat.db readable"
    FDA_OK=true
else
    fail "Full Disk Access — chat.db exists but cannot be read"
    info "Grant Full Disk Access to your terminal app, then re-run this script:"
    info "  System Settings → Privacy & Security → Full Disk Access"
    info "  Add: $(basename "$TERM_PROGRAM" 2>/dev/null || echo "your terminal app") and Claude Desktop / Claude"
    info ""
    info "Without this, the MCP server will not be able to read your messages."
fi

# ── 4. osascript (AppleScript) ────────────────────────────────────────────────
if command -v osascript &>/dev/null; then
    ok "osascript available (required for send_imessage)"
else
    fail "osascript not found — this should always be present on macOS"
fi

# ── 5. Virtual environment ───────────────────────────────────────────────────
echo
echo -e "${BOLD}Setting up Python environment...${RESET}"

if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
    ok "Created .venv"
else
    ok ".venv already exists"
fi

source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -e .
ok "Dependencies installed  (mcp>=1.0.0)"

# ── 6. Locate the installed script ───────────────────────────────────────────
SERVER_PATH="$(pwd)/.venv/bin/imessage-mcp"

# ── 7. Print MCP config snippets ─────────────────────────────────────────────
echo
echo -e "${BOLD}Installation complete.${RESET}"
echo
echo "────────────────────────────────────────"
echo -e "${BOLD}Claude Desktop config${RESET}"
echo "Add the following to ~/Library/Application Support/Claude/claude_desktop_config.json"
echo "under the \"mcpServers\" key:"
echo
cat <<EOF
{
  "mcpServers": {
    "imessage": {
      "command": "$SERVER_PATH"
    }
  }
}
EOF

echo
echo "────────────────────────────────────────"
echo -e "${BOLD}Claude Code (CLI) config${RESET}"
echo "Run this command to register the server with Claude Code:"
echo
echo -e "  claude mcp add imessage $SERVER_PATH"

echo
echo "────────────────────────────────────────"
echo -e "${BOLD}Permissions reminder${RESET}"
echo " 1. Full Disk Access — grant to your terminal app AND Claude Desktop"
echo "    System Settings → Privacy & Security → Full Disk Access"
echo " 2. Messages app must be open and signed in for send_imessage to work"
echo " 3. Automation permission — macOS will prompt the first time AppleScript"
echo "    tries to control Messages; click Allow"
echo

#!/usr/bin/env python3
"""iMessage MCP Server — send and receive Apple iMessages via MCP tools."""

import asyncio
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    TextContent,
    Tool,
)

# Apple epoch starts 2001-01-01; convert to Unix epoch
APPLE_EPOCH_OFFSET = 978307200

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"

app = Server("imessage-mcp")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def apple_time_to_datetime(apple_ns: int) -> str:
    """Convert Apple nanosecond timestamp to ISO-8601 string."""
    if apple_ns is None:
        return ""
    seconds = apple_ns / 1e9 + APPLE_EPOCH_OFFSET
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def open_db_copy() -> sqlite3.Connection:
    """
    Copy chat.db to a temp file before opening — the live DB is often locked
    by imagent. Returns a connection to the copy.
    """
    if not CHAT_DB.exists():
        raise FileNotFoundError(
            f"chat.db not found at {CHAT_DB}. "
            "Ensure Full Disk Access is granted to your terminal / Claude."
        )
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    shutil.copy2(CHAT_DB, tmp.name)
    return sqlite3.connect(tmp.name)


def run_applescript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "AppleScript error")
    return result.stdout.strip()


def normalize_phone(phone: str) -> str:
    """Strip non-digit chars except leading +."""
    if phone.startswith("+"):
        return "+" + re.sub(r"\D", "", phone[1:])
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return "+1" + digits
    return phone  # might be email — leave as-is


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_send_message(recipient: str, message: str, service: str = "iMessage") -> str:
    """Send a message via the Messages app using AppleScript."""
    # Validate service
    if service not in ("iMessage", "SMS"):
        raise ValueError("service must be 'iMessage' or 'SMS'")

    # Escape quotes in the message
    safe_msg = message.replace("\\", "\\\\").replace('"', '\\"')
    safe_recipient = recipient.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
tell application "Messages"
    set targetService to 1st service whose service type = {service}
    set targetBuddy to buddy "{safe_recipient}" of targetService
    send "{safe_msg}" to targetBuddy
end tell
'''
    run_applescript(script)
    return f"Message sent to {recipient} via {service}."


def tool_list_conversations(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent conversations from chat.db."""
    conn = open_db_copy()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                c.ROWID        AS chat_id,
                c.chat_identifier,
                c.display_name,
                c.service_name,
                MAX(m.date)    AS last_date,
                COUNT(m.ROWID) AS message_count
            FROM chat c
            LEFT JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
            LEFT JOIN message m             ON m.ROWID = cmj.message_id
            GROUP BY c.ROWID
            ORDER BY last_date DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        results = []
        for row in rows:
            d = dict(zip(cols, row))
            d["last_message_at"] = apple_time_to_datetime(d.pop("last_date"))
            results.append(d)
        return results
    finally:
        conn.close()


def tool_get_messages(
    chat_identifier: str,
    limit: int = 50,
    search_text: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch messages for a conversation identified by phone/email or display name.
    Optionally filter by text content.
    """
    conn = open_db_copy()
    try:
        cur = conn.cursor()
        query = """
            SELECT
                m.ROWID         AS message_id,
                m.text,
                m.date          AS apple_date,
                m.is_from_me,
                m.service,
                h.id            AS sender_handle
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c                ON c.ROWID = cmj.chat_id
            LEFT JOIN handle h         ON h.ROWID = m.handle_id
            WHERE (
                c.chat_identifier = ?
                OR c.display_name  = ?
            )
        """
        params: list[Any] = [chat_identifier, chat_identifier]

        if search_text:
            query += " AND m.text LIKE ?"
            params.append(f"%{search_text}%")

        query += " ORDER BY m.date DESC LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        results = []
        for row in rows:
            d = dict(zip(cols, row))
            d["sent_at"] = apple_time_to_datetime(d.pop("apple_date"))
            d["is_from_me"] = bool(d["is_from_me"])
            results.append(d)
        return list(reversed(results))  # oldest first
    finally:
        conn.close()


def tool_search_messages(query: str, limit: int = 30) -> list[dict[str, Any]]:
    """Full-text search across all messages."""
    conn = open_db_copy()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                m.ROWID         AS message_id,
                m.text,
                m.date          AS apple_date,
                m.is_from_me,
                m.service,
                c.chat_identifier,
                c.display_name,
                h.id            AS sender_handle
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c                ON c.ROWID = cmj.chat_id
            LEFT JOIN handle h         ON h.ROWID = m.handle_id
            WHERE m.text LIKE ?
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (f"%{query}%", limit),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        results = []
        for row in rows:
            d = dict(zip(cols, row))
            d["sent_at"] = apple_time_to_datetime(d.pop("apple_date"))
            d["is_from_me"] = bool(d["is_from_me"])
            results.append(d)
        return results
    finally:
        conn.close()


def tool_get_unread_messages(limit: int = 50) -> list[dict[str, Any]]:
    """Return messages that are marked as unread (is_read = 0, is_from_me = 0)."""
    conn = open_db_copy()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                m.ROWID         AS message_id,
                m.text,
                m.date          AS apple_date,
                m.service,
                c.chat_identifier,
                c.display_name,
                h.id            AS sender_handle
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c                ON c.ROWID = cmj.chat_id
            LEFT JOIN handle h         ON h.ROWID = m.handle_id
            WHERE m.is_read = 0
              AND m.is_from_me = 0
              AND m.text IS NOT NULL
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        results = []
        for row in rows:
            d = dict(zip(cols, row))
            d["sent_at"] = apple_time_to_datetime(d.pop("apple_date"))
            results.append(d)
        return results
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MCP tool registry
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="send_imessage",
        description=(
            "Send an iMessage (or SMS) to a phone number or Apple ID email address. "
            "Requires the Messages app to be running and the contact to be reachable."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Phone number (e.g. +14155551234) or Apple ID email.",
                },
                "message": {
                    "type": "string",
                    "description": "The text to send.",
                },
                "service": {
                    "type": "string",
                    "enum": ["iMessage", "SMS"],
                    "default": "iMessage",
                    "description": "Messaging service to use.",
                },
            },
            "required": ["recipient", "message"],
        },
    ),
    Tool(
        name="list_imessage_conversations",
        description="List recent iMessage / SMS conversations, sorted by most recent activity.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum number of conversations to return.",
                },
            },
        },
    ),
    Tool(
        name="get_imessage_messages",
        description=(
            "Retrieve messages from a specific conversation. "
            "Identify the conversation by phone number, Apple ID, or display name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "chat_identifier": {
                    "type": "string",
                    "description": "Phone number, Apple ID email, or group chat display name.",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum number of messages to return.",
                },
                "search_text": {
                    "type": "string",
                    "description": "Optional: filter messages containing this text.",
                },
            },
            "required": ["chat_identifier"],
        },
    ),
    Tool(
        name="search_imessages",
        description="Search across all iMessage conversations by text content.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to search for in message bodies.",
                },
                "limit": {
                    "type": "integer",
                    "default": 30,
                    "description": "Maximum number of results.",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_unread_imessages",
        description="Return all unread incoming iMessages across all conversations.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum number of unread messages to return.",
                },
            },
        },
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "send_imessage":
            result = tool_send_message(
                recipient=arguments["recipient"],
                message=arguments["message"],
                service=arguments.get("service", "iMessage"),
            )
        elif name == "list_imessage_conversations":
            result = tool_list_conversations(limit=arguments.get("limit", 20))
        elif name == "get_imessage_messages":
            result = tool_get_messages(
                chat_identifier=arguments["chat_identifier"],
                limit=arguments.get("limit", 50),
                search_text=arguments.get("search_text"),
            )
        elif name == "search_imessages":
            result = tool_search_messages(
                query=arguments["query"],
                limit=arguments.get("limit", 30),
            )
        elif name == "get_unread_imessages":
            result = tool_get_unread_messages(limit=arguments.get("limit", 50))
        else:
            raise ValueError(f"Unknown tool: {name}")

        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    except Exception as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()

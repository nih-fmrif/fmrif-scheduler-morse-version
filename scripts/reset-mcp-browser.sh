#!/usr/bin/env bash
set -euo pipefail

PROFILE_DIR="${MCP_CHROME_PROFILE_DIR:-$HOME/Library/Caches/ms-playwright/mcp-chrome}"

if [ ! -d "$PROFILE_DIR" ]; then
  echo "MCP Chrome profile not found: $PROFILE_DIR"
  exit 0
fi

echo "Checking MCP Chrome profile: $PROFILE_DIR"

matches="$(ps aux | grep -F -- "$PROFILE_DIR" | grep -F -- "Google Chrome.app/Contents/MacOS/Google Chrome" | grep -v grep || true)"

if [ -z "$matches" ]; then
  echo "No Chrome process is using the MCP profile."
  exit 0
fi

echo "Stopping Chrome processes using the MCP profile..."
printf '%s\n' "$matches"

pids="$(printf '%s\n' "$matches" | awk '{print $2}' | tr '\n' ' ')"
kill $pids

sleep 1

remaining="$(ps aux | grep -F -- "$PROFILE_DIR" | grep -F -- "Google Chrome.app/Contents/MacOS/Google Chrome" | grep -v grep || true)"
if [ -n "$remaining" ]; then
  echo "Some MCP Chrome processes are still running:"
  printf '%s\n' "$remaining"
  exit 1
fi

echo "MCP Chrome profile is free. Retry the MCP browser launch."

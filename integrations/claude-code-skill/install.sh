#!/usr/bin/env bash
# Install the evalit skill for Claude Code.
#
# Copies SKILL.md and helpers to ~/.claude/skills/evalit/.
# Also prints the command needed to register the MCP server with Claude Desktop.
#
# Usage: bash integrations/claude-code-skill/install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILL_SRC="$REPO_DIR/integrations/claude-code-skill"
SKILL_DST="${HOME}/.claude/skills/evalit"

echo "→ installing evalit skill to $SKILL_DST"
mkdir -p "$SKILL_DST/helpers"

# Rewrite the placeholder `/path/to/evalit-4me` in SKILL.md with the actual repo path.
sed "s|/path/to/evalit-4me|${REPO_DIR}|g" "$SKILL_SRC/SKILL.md" > "$SKILL_DST/SKILL.md"
cp "$SKILL_SRC/helpers/"*.py "$SKILL_DST/helpers/"
chmod +x "$SKILL_DST/helpers/"*.py

echo "✓ Claude Code skill installed."
echo ""
echo "To register the MCP server with Claude Desktop, add this to"
echo "~/Library/Application Support/Claude/claude_desktop_config.json"
echo "(macOS) under the 'mcpServers' key:"
echo ""
cat <<EOF
  "evalit": {
    "command": "uv",
    "args": [
      "run",
      "--project",
      "${REPO_DIR}",
      "python",
      "-m",
      "evalit_4me.mcp_server.server"
    ]
  }
EOF
echo ""
echo "Restart Claude Desktop after editing."

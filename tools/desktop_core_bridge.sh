#!/usr/bin/env bash

set -Eeuo pipefail

bridge_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
real_codex="$bridge_dir/real-codex"
codex_app_root="$bridge_dir/codex-app-tools"

if [[ ! -x "$real_codex" ]]; then
  echo "desktop_core_bridge.sh: real Codex binary is not executable: $real_codex" >&2
  exit 1
fi

if [[ "${1:-}" == "app-server" ]]; then
  codex_app_launcher="$codex_app_root/scripts/launch_codex_app_tools_mcp"
  if [[ ! -x "$codex_app_launcher" || ! -f "$codex_app_root/server.mjs" ]]; then
    echo "desktop_core_bridge.sh: bundled codex-app-tools MCP is incomplete: $codex_app_root" >&2
    exit 1
  fi

  shift
  exec "$real_codex" \
    -c "mcp_servers.codex_app.command=\"$codex_app_launcher\"" \
    -c 'mcp_servers.codex_app.args=["./server.mjs"]' \
    -c "mcp_servers.codex_app.cwd=\"$codex_app_root\"" \
    -c 'mcp_servers.codex_app.env_vars=["CODEX_APP_TOOLS_PIPE_PATH","CODEX_MCP_NODE_PATH","CODEX_BROWSER_USE_NODE_PATH","CODEX_ELECTRON_RESOURCES_PATH","CODEX_CLI_PATH","XDG_CACHE_HOME","HOME","USERPROFILE","LOCALAPPDATA","PATH"]' \
    -c 'mcp_servers.codex_app.enabled=true' \
    -c 'mcp_servers.codex_app.default_tools_approval_mode="approve"' \
    -c 'mcp_servers.codex_app.startup_timeout_sec=10' \
    -c 'mcp_servers.codex_app.tool_timeout_sec=3600' \
    -c 'mcp_servers.codex_app.tools.automation_update.approval_mode="prompt"' \
    -c 'mcp_servers.codex_app.tools.create_thread.approval_mode="prompt"' \
    -c 'mcp_servers.codex_app.tools.send_message_to_thread.approval_mode="prompt"' \
    -c 'mcp_servers.codex_app.tools.fork_thread.approval_mode="prompt"' \
    -c 'mcp_servers.codex_app.tools.handoff_thread.approval_mode="prompt"' \
    app-server "$@"
fi

exec "$real_codex" "$@"

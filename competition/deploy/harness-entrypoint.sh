#!/bin/sh
# DeepSeek Harness container bootstrap for the ZJJ agent bundle.
#
# The pinned image is not rebuilt: the plugin is mounted read-only at
# /opt/zjj-plugin and installed into the persistent dsh profile on first start.
# If the ZJJ environment is absent, the original entrypoint runs unchanged.
set -e

if [ -n "$ZJJ_MCP_URL" ] && [ -n "$ZJJ_AGENT_TOKEN" ]; then
  SOURCE=/opt/zjj-plugin
  TARGET=/root/.dsh/plugins/dsh-zjj-agent
  VERSION="$(node -p "require('$SOURCE/package.json').version" 2>/dev/null || echo unknown)"
  MARKER=/root/.dsh/.zjj-plugin-version
  PROFILE=/root/.dsh/profiles/web/package.json
  if [ "$(cat "$MARKER" 2>/dev/null || true)" != "$VERSION" ] \
      || ! grep -q '"dsh-zjj-agent"' "$PROFILE" 2>/dev/null; then
    rm -rf "$TARGET"
    mkdir -p "$(dirname "$TARGET")"
    cp -R "$SOURCE" "$TARGET"
    dsh plugin --profile web add "$TARGET" >/dev/null
    printf '%s\n' "$VERSION" > "$MARKER"
    echo "[zjj] installed dsh-zjj-agent $VERSION into profile web"
  else
    echo "[zjj] dsh-zjj-agent $VERSION already installed"
  fi
else
  echo "[zjj] ZJJ_MCP_URL/ZJJ_AGENT_TOKEN not set; running without the agent bundle"
fi

exec /app/entrypoint.sh

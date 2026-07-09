#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
DEFAULT_PROFILE_DIR="${REMOTE_BROWSER_PROFILE_DIR:-/browser-profiles/shared}"
CONTROL_DIR="${REMOTE_BROWSER_CONTROL_DIR:-/browser-profiles/.remote}"
ACTIVE_PROFILE_FILE="$CONTROL_DIR/active_profile"
DISPLAY_NUM="${DISPLAY#:}"
CHROME_PID=""
CURRENT_PROFILE_DIR=""

mkdir -p "$DEFAULT_PROFILE_DIR" "$CONTROL_DIR"
rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}"

Xvfb "$DISPLAY" -screen 0 "${SCREEN_RESOLUTION:-1440x900x24}" &
fluxbox >/tmp/fluxbox.log 2>&1 &
x11vnc -display "$DISPLAY" -forever -shared -rfbport 5900 -nopw >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc/ 6080 localhost:5900 >/tmp/novnc.log 2>&1 &

CHROME_BIN="$(find /ms-playwright -path '*/chrome-linux/chrome' | head -n 1)"
if [ -z "$CHROME_BIN" ]; then
  echo "Chromium binary not found under /ms-playwright" >&2
  exit 1
fi

start_chrome() {
  local profile_dir="$1"
  mkdir -p "$profile_dir"

  if [ -n "$CHROME_PID" ] && kill -0 "$CHROME_PID" >/dev/null 2>&1; then
    kill "$CHROME_PID" >/dev/null 2>&1 || true
    wait "$CHROME_PID" >/dev/null 2>&1 || true
  fi

  "$CHROME_BIN" \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-notifications \
    --user-data-dir="$profile_dir" \
    https://www.facebook.com/ >/tmp/chromium.log 2>&1 &

  CHROME_PID="$!"
  CURRENT_PROFILE_DIR="$profile_dir"
  echo "Remote Chrome started with profile: $profile_dir"
}

resolve_profile_dir() {
  local requested="$1"
  if [ -z "$requested" ]; then
    echo "$DEFAULT_PROFILE_DIR"
  elif [[ "$requested" = /* ]]; then
    echo "$requested"
  else
    echo "/browser-profiles/$requested"
  fi
}

start_chrome "$DEFAULT_PROFILE_DIR"

while true; do
  if [ -f "$ACTIVE_PROFILE_FILE" ]; then
    REQUESTED_PROFILE="$(tr -d '\r\n' < "$ACTIVE_PROFILE_FILE")"
    NEXT_PROFILE_DIR="$(resolve_profile_dir "$REQUESTED_PROFILE")"
    if [ "$NEXT_PROFILE_DIR" != "$CURRENT_PROFILE_DIR" ]; then
      start_chrome "$NEXT_PROFILE_DIR"
    fi
  fi
  sleep 2
done

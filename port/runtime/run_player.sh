#!/bin/sh
# Run the built game for a bounded time, then kill it. usage: run_player.sh [seconds] [VAR=value ...]
# Headless (-batchmode -nographics) unless BR_PLAYER_ARGS is given, e.g.
#   run_player.sh 120 "BR_PLAYER_ARGS=-screen-fullscreen 0 -screen-width 1280 -screen-height 720"
# GAME_DIR (default: <repo>/game) and GAME_EXE (default: the only *Slop.exe there) choose what is run.
SECS=${1:-30}; [ $# -gt 0 ] && shift
for kv in "$@"; do export "$kv"; done
cd "${GAME_DIR:-$(dirname "$0")/../../game}" || exit 1
EXE=${GAME_EXE:-$(ls *Slop.exe 2>/dev/null | head -1)}
[ -n "$EXE" ] || { echo "no game executable in $(pwd)"; exit 1; }
taskkill //F //IM "$EXE" >/dev/null 2>&1; taskkill //F //IM UnityCrashHandler64.exe >/dev/null 2>&1
rm -f port.log player.log port_hang.log
ARGS=${BR_PLAYER_ARGS:--batchmode -nographics}
timeout $SECS "./$EXE" $ARGS -logFile player.log >/dev/null 2>&1
echo "[exit code $? (124 = still running at the time limit)]"
taskkill //F //IM "$EXE" >/dev/null 2>&1; taskkill //F //IM UnityCrashHandler64.exe >/dev/null 2>&1
exit 0

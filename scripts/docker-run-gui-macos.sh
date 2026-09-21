#!/usr/bin/env bash

set -euo pipefail

read -r -a compose_command <<< "${DOCKER_COMPOSE:-docker compose}"
xauth_command="/opt/X11/bin/xauth"
xset_command="/opt/X11/bin/xset"
macos_display="${MACOS_DISPLAY:-host.docker.internal:0}"
host_xauthority="${XAUTHORITY:-${HOME}/.Xauthority}"
display_number="${macos_display##*:}"
display_number="${display_number%%.*}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "ERROR: This launcher requires macOS."
    exit 1
fi

if [[ ! -x "${xauth_command}" ]]; then
    echo "ERROR: XQuartz is not installed. Install it with 'brew install --cask xquartz'."
    exit 1
fi

# Remote OpenGL clients need XQuartz's indirect GLX extension. Without it,
# SUMO continues simulating through TraCI but its map canvas never appears.
iglx_enabled="$(defaults read org.xquartz.X11 enable_iglx 2>/dev/null || true)"
if [[ "${iglx_enabled}" != "1" ]]; then
    echo "Enabling XQuartz indirect GLX rendering for SUMO GUI..."
    defaults write org.xquartz.X11 enable_iglx -bool true
    osascript -e 'tell application "XQuartz" to quit' >/dev/null 2>&1 || true
    for _ in {1..20}; do
        if ! pgrep -x X11.bin >/dev/null 2>&1; then
            break
        fi
        sleep 0.25
    done
fi

# Opening an already-running XQuartz instance is harmless. On a first-time
# installation, macOS may still require a logout/login before its X11 session
# and authority cookie are available.
open -a XQuartz

for _ in {1..20}; do
    if [[ -f "${host_xauthority}" ]] \
        && "${xauth_command}" -f "${host_xauthority}" nlist ":${display_number}" 2>/dev/null | grep -q . \
        && DISPLAY=":${display_number}" XAUTHORITY="${host_xauthority}" "${xset_command}" q >/dev/null 2>&1; then
        break
    fi
    sleep 0.25
done

if ! DISPLAY=":${display_number}" XAUTHORITY="${host_xauthority}" "${xset_command}" q >/dev/null 2>&1; then
    echo "ERROR: XQuartz display :${display_number} did not become ready."
    echo "Start XQuartz, enable Settings > Security > Allow connections from network clients, and retry."
    exit 1
fi

authority_record="$("${xauth_command}" -f "${host_xauthority}" nlist ":${display_number}" 2>/dev/null | sed -n '1p')"
if [[ -z "${authority_record}" ]]; then
    echo "ERROR: XQuartz did not provide an authorization cookie for display :${display_number}."
    echo "Log out and back in after installing XQuartz, start it again, and retry."
    exit 1
fi

umask 077
docker_xauthority="$(mktemp /tmp/sumo-xquartz.XXXXXX)"
cleanup() {
    rm -f "${docker_xauthority}"
}
trap cleanup EXIT INT TERM

# XQuartz records its cookie against the Mac's local display names. Docker
# reaches the same display through host.docker.internal, so use Xauthority's
# FamilyWild form to make this one temporary cookie valid independent of the
# Docker Desktop gateway address.
wild_authority_record="$(printf '%s\n' "${authority_record}" | sed 's/^..../ffff/')"
printf '%s\n' "${wild_authority_record}" | "${xauth_command}" -f "${docker_xauthority}" nmerge -

export MACOS_DISPLAY="${macos_display}"
export MACOS_XAUTHORITY="${docker_xauthority}"

compose_files=(-f compose.yaml -f compose.gui.macos.yaml)

echo "Checking XQuartz access from a simulation worker..."
if ! "${compose_command[@]}" "${compose_files[@]}" run --rm --no-deps simulation-worker \
    python3 -c 'import ctypes, sys; x11 = ctypes.CDLL("libX11.so.6"); x11.XOpenDisplay.restype = ctypes.c_void_p; display = x11.XOpenDisplay(None); sys.exit(0 if display else 1)'; then
    echo "ERROR: A Docker simulation worker could not authenticate to XQuartz at ${macos_display}."
    echo "In XQuartz, enable Settings > Security > Allow connections from network clients, restart XQuartz, and retry."
    exit 1
fi

echo "XQuartz connection verified. Starting the application with SUMO GUI support."
"${compose_command[@]}" "${compose_files[@]}" up --no-build

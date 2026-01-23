#!/bin/bash
# Wrapper script for Docker commands when Docker Desktop is installed

# Docker binary path for macOS Docker Desktop
DOCKER_BIN="/Applications/Docker.app/Contents/Resources/bin/docker"

if [ -f "$DOCKER_BIN" ]; then
    "$DOCKER_BIN" "$@"
else
    # Fallback to system docker
    /usr/local/bin/docker "$@"
fi

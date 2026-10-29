#!/usr/bin/env bash
# Read-only checks only. This script never starts services or calls provider APIs.
set -euo pipefail
cd /opt/unreal-github
.venv/bin/python -m bureau.cli health
.venv/bin/python -m bureau.cli doctor
systemd-analyze calendar '*-*-* 18:00:00 Asia/Seoul'
systemd-analyze verify deploy/unreal-candidates.service deploy/unreal-candidates.timer deploy/unreal-worker.service deploy/unreal-telegram.service deploy/unreal-images.service

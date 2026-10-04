#!/bin/zsh
cd "$(dirname "$0")"
exec "${BLYNGER_PYTHON:-python3}" app.py

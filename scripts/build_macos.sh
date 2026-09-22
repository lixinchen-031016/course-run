#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 -m pip install -r requirements-build.txt
python3 build.py

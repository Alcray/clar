#!/usr/bin/env sh
set -eu
# Run from the checkout; credentials are loaded from the operator's .env.
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
umask 077
exec "${CLAR_PYTHON:-python3}" -m app

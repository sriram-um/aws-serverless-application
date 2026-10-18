#!/usr/bin/env bash
# Build the DAX client Lambda layer (layers/dax/python/).
# Installs only amazon-dax-client and its parser runtime, WITHOUT their dependencies: a plain
# `pip install amazon-dax-client` also pulls botocore/urllib3/dateutil (~26 MB) that the
# Lambda runtime already provides. Both packages are pure Python, so no platform flags needed.
# Run before `sam build` (the CI workflow does this too).
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET=layers/dax/python
PYTHON=${PYTHON:-python}
rm -rf "$TARGET"
"$PYTHON" -m pip install --quiet --no-deps --target "$TARGET" \
  "amazon-dax-client==2.1.0" \
  "antlr4-python3-runtime==4.13.2"
find "$TARGET" -name "__pycache__" -type d -prune -exec rm -rf {} +
echo "DAX layer built: $(du -sh "$TARGET" | cut -f1) in $TARGET"

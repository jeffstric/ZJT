#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="${REPO_DIR}/web/js"
BACKUP_DIR="${REPO_DIR}/.obf_backup/$(date +%Y%m%d_%H%M%S)"
OBF_BIN="${REPO_DIR}/node_modules/.bin/javascript-obfuscator"

if [[ ! -x "$OBF_BIN" ]]; then
  echo "missing javascript-obfuscator, run: npm install --save-dev javascript-obfuscator"
  exit 1
fi

mkdir -p "$BACKUP_DIR"
cp -r "$SRC_DIR" "$BACKUP_DIR"

find "$SRC_DIR" -type f -name "*.js" | while read -r file; do
  tmp_dir="$(mktemp -d)"
  "$OBF_BIN" "$file" \
    --output "$tmp_dir" \
    --compact true \
    --control-flow-flattening true \
    --string-array true \
    --string-array-encoding rc4 \
    --disable-console-output true

  mv "$tmp_dir/$(basename "$file")" "$file"
  rm -rf "$tmp_dir"
  echo "obfuscated: ${file#$REPO_DIR/}"
done

echo "backup saved at $BACKUP_DIR"
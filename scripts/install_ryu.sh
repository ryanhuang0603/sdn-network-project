#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RYU_REPO="${RYU_REPO:-https://github.com/faucetsdn/ryu}"
RYU_COMMIT="${RYU_COMMIT:-d6cda4f4}"
RYU_DIR="${RYU_DIR:-$ROOT_DIR/tmp/ryu_source}"
PATCH_FILE="$ROOT_DIR/patches/ryu-python314-hooks.patch"

mkdir -p "$(dirname "$RYU_DIR")"

if [[ ! -d "$RYU_DIR/.git" ]]; then
  git clone "$RYU_REPO" "$RYU_DIR"
fi

git -C "$RYU_DIR" fetch --all --tags
git -C "$RYU_DIR" checkout "$RYU_COMMIT"

if git -C "$RYU_DIR" apply --check "$PATCH_FILE"; then
  git -C "$RYU_DIR" apply "$PATCH_FILE"
elif git -C "$RYU_DIR" apply --check --reverse "$PATCH_FILE"; then
  echo "Ryu patch already applied"
else
  echo "Ryu patch cannot be applied cleanly" >&2
  exit 1
fi

python3 -m pip install "$RYU_DIR"

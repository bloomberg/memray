#!/usr/bin/env bash
set -Eeuo pipefail

SNAPSHOT_COMMIT=2446c66076480ce07a6bd868badcbceb3eeecc2e
LIBBACKTRACE_DIR="libbacktrace"

echo "checking" $(ls)

echo ">>> Cloning libbacktrace"
rm -rf "$LIBBACKTRACE_DIR"
git clone https://github.com/ianlancetaylor/libbacktrace.git "$LIBBACKTRACE_DIR" 

echo ">>> Checking out commit ${SNAPSHOT_COMMIT}"
cd "$LIBBACKTRACE_DIR"
git checkout $SNAPSHOT_COMMIT 1>/dev/null

echo ">>> Applying main patch for commit ${SNAPSHOT_COMMIT}"
git apply ../libbacktrace_${SNAPSHOT_COMMIT}_patch.diff
echo ">>> Applying debuginfod patch for commit ${SNAPSHOT_COMMIT}"
git apply ../libbacktrace_${SNAPSHOT_COMMIT}_debuginfod_patch.diff
rm -rf .git

echo "Regenerated vendored libbacktrace"

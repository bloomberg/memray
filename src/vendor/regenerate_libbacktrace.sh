#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 0 ]] && [[ $# -ne 1 ]]; then
    echo "Usage: $0 [new-commit]"
    exit 1
fi

old_snapshot=7e2b7da3d6568d2e4e78658f22e701746a48d7e1
new_snapshot=${1:-}

echo ">>> Cloning libbacktrace"
rm -rf libbacktrace
git clone https://github.com/ianlancetaylor/libbacktrace.git libbacktrace

echo "Applying patches"
cd libbacktrace
git checkout "$old_snapshot"
git am ../libbacktrace-patches/*

if [[ -n "$new_snapshot" ]]; then
    echo "Rebasing on $new_snapshot"
    if git rebase "$new_snapshot"; then
        echo "Rebased successfully. Updating patches."
        (cd ../libbacktrace-patches && git rm -f 0*)
        git format-patch "$new_snapshot" --no-numbered --output-directory=../libbacktrace-patches
        (cd ../libbacktrace-patches && git add 0*)
    else
        echo "Failed to apply patches. You must finish rebasing manually."
        echo "When you are satisfied, update the patches by running:"
        echo "  git format-patch $new_snapshot --no-numbered --output-directory=../libbacktrace-patches"
        echo "Be sure to remove the old patches first if the file names will change."
        exit 1
    fi
fi

rm -rf .git

echo "Regenerated vendored libbacktrace"

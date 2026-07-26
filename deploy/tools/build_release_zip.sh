#!/usr/bin/env bash
########################################################################
### BUILD IMPS RELEASE ZIP
########################################################################
# Builds the .zip that actually gets uploaded to getimps.com, from a
# clean checkout of this repo. Exists specifically so nobody has to
# remember the handful of one-off steps a release needs (touching
# first.run, stripping out deploy-only/demo-only files) -- run this
# and it's just handled.
#
# Usage:
#   ./deploy/tools/build_release_zip.sh [version]
#
# If no version is given, uses today's date (e.g. imps_2026-07-03.zip),
# matching the naming pattern of the existing
# static/downloads/imps_8.18.25.tar file.
########################################################################

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${1:-$(date +%Y-%m-%d)}"
STAGE_DIR="$(mktemp -d)"
RELEASE_NAME="imps_${VERSION}"
OUTPUT_ZIP="${REPO_ROOT}/imps_${VERSION}.zip"

echo "Building release from: ${REPO_ROOT}"
echo "Staging in:            ${STAGE_DIR}/${RELEASE_NAME}"
echo "Output:                ${OUTPUT_ZIP}"
echo

### 1. COPY THE REPO INTO A CLEAN STAGING DIRECTORY
mkdir -p "${STAGE_DIR}/${RELEASE_NAME}"
git -C "${REPO_ROOT}" archive HEAD | tar -x -C "${STAGE_DIR}/${RELEASE_NAME}"
# `git archive` only includes tracked files, at their committed
# content -- this already excludes .gitignore'd stuff (uploaded item
# photos, generated backups, __pycache__, the real imps_config.toml,
# credentials files, etc.) with no manual bookkeeping needed here.

cd "${STAGE_DIR}/${RELEASE_NAME}"

### 2. TOUCH first.run
### The whole reason this script exists -- without this, a fresh
### install never sees the welcome/setup wizard (see the app's
### home() route). Intentionally not tracked in git (same reasoning
### as imps_config.toml -- it's per-install state, and the running
### app renames it away the moment setup finishes), so it has to be
### (re)created at packaging time instead.
touch first.run
echo "  Created first.run"

### 3. STRIP DEPLOY-ONLY / DEMO-ONLY / CREDENTIAL-ADJACENT CONTENT
### None of this belongs in a public download: reset tooling and its
### seed data only make sense against demo.getimps.com's own
### infrastructure, and the .toml files (even though only the
### .example versions should ever be tracked -- see .gitignore) are
### exactly the kind of thing that must never ship by accident.
rm -rf deploy/
rm -f certificates/*.key certificates/*.crt
echo "  Removed deploy/ (reset tools, seed data, demo-only scripts)"
echo "  Removed certificate private material"

### 4. SANITY CHECKS -- fail loudly rather than silently shipping a
### broken zip
if [ ! -f first.run ]; then
    echo "ERROR: first.run missing after step 2 -- aborting." >&2
    exit 1
fi
if find . -iname "*credentials*.toml" ! -iname "*.example" | grep -q .; then
    echo "ERROR: a real credentials file made it into the release -- aborting." >&2
    echo "(This shouldn't be possible via git archive, since only tracked" >&2
    echo "files are ever included -- if this fires, something's wrong with" >&2
    echo ".gitignore or a credentials file got committed by mistake.)" >&2
    exit 1
fi
echo "  Sanity checks passed"

### 5. ZIP IT UP
cd "${STAGE_DIR}"
zip -rq "${OUTPUT_ZIP}" "${RELEASE_NAME}"

### 6. CLEAN UP STAGING
rm -rf "${STAGE_DIR}"

echo
echo "Done: ${OUTPUT_ZIP}"
echo "Contents:"
unzip -l "${OUTPUT_ZIP}" | head -20
echo "  ..."
echo
echo "Double check before uploading to getimps.com:"
echo "  unzip -l ${OUTPUT_ZIP} | grep -iE 'credentials|\.key$|\.git'"
echo "(should print nothing)"

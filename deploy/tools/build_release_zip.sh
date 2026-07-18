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
# If no version is given, uses today's date (e.g. imps_2026-07-03.zip).
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

### 3. STRIP CERTIFICATE PRIVATE MATERIAL, THE TOOLS DIRECTORY, AND
### SEED DATA
### deploy/'s demo-only scripts -- imps_reset.py, db_monitor.py, the
### systemd units, mysql-restart-override.conf, the credential example
### files -- are already excluded automatically via .gitignore, so
### `git archive` never includes them in the first place.
###
### deploy/tools/ itself still needs stripping explicitly, though:
### this very script (build_release_zip.sh) lives there and IS
### tracked (it's a maintainer tool, not gitignored), so without this
### step every release would ship a copy of the packaging script
### alongside everything else in that directory.
###
### seed_db.sql / seed_images.zip are also tracked (kept in the repo
### for the reset/monitor tooling's own use), but don't belong in a
### public release -- stripped here at packaging time rather than via
### .gitignore, since they're still legitimate to keep in git itself.
###
### deploy/db_setup.py, deploy/schema.sql, deploy/setup.sql,
### deploy/imps-apache.conf, and deploy/docker/ all SHIP as-is --
### install-facing files the README/DOCKER.md instructions depend on.
rm -f certificates/*.key certificates/*.crt
rm -rf deploy/tools/
rm -f deploy/seed_db.sql deploy/seed_images.zip
echo "  Removed certificate private material"
echo "  Removed deploy/tools/ (packaging script, systemd units)"
echo "  Removed deploy/ seed data"

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
if find . -iname ".env" ! -iname "*.example" | grep -q .; then
    echo "ERROR: a real .env file made it into the release -- aborting." >&2
    echo "(Same reasoning as the credentials check above -- .env holds" >&2
    echo "real Docker secrets and should never be tracked; see .gitignore.)" >&2
    exit 1
fi
echo "  Sanity checks passed"

### 5. ZIP IT UP
### Zipping from *inside* the staged directory (rather than zipping
### the STAGE_DIR/${RELEASE_NAME} directory itself) means the archive
### has no top-level wrapper folder -- `cd /var/www && unzip imps.zip`
### puts run.py, app/, deploy/, etc. directly at that level, instead
### of one level down inside an imps_${VERSION}/ subfolder. The output
### FILENAME still carries the version/date (imps_${VERSION}.zip) so
### it's still easy to tell releases apart on disk -- only the
### archive's internal layout changes.
cd "${STAGE_DIR}/${RELEASE_NAME}"
zip -rq "${OUTPUT_ZIP}" .

### 6. CLEAN UP STAGING
rm -rf "${STAGE_DIR}"

echo
echo "Done: ${OUTPUT_ZIP}"
echo "Contents:"
unzip -l "${OUTPUT_ZIP}" | head -20
echo "  ..."
echo
echo "Double check before uploading to getimps.com:"
echo "  unzip -l ${OUTPUT_ZIP} | grep -iE 'credentials|\.key$|\.env$|\.git'"
echo "(should print nothing)"

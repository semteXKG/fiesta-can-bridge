#!/usr/bin/env bash
# build-deb.sh — bump version, update debian/changelog, build .deb
#
# Usage:
#   ./build-deb.sh                    # auto-increment patch (1.0.0 → 1.0.1)
#   ./build-deb.sh 2.0.0              # explicit version
#   ./build-deb.sh 1.1.0 "My changes" # explicit version + changelog message

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

CHANGELOG="debian/changelog"
DIST_DIR="dist"
MAINTAINER="semtex <semtex@users.noreply.github.com>"
DATE="$(date -R)"

# ── Read current version from changelog ──────────────────────────────────────
current_version=$(head -1 "${CHANGELOG}" | grep -oP '\(\K[^)]+' | sed 's/-[0-9]*$//')
current_deb_revision=$(head -1 "${CHANGELOG}" | grep -oP '\(\K[^)]+' | grep -oP '[^-]+$')

# ── Resolve new version ───────────────────────────────────────────────────────
new_upstream="${1:-}"
if [[ -z "${new_upstream}" ]]; then
    # Auto-increment patch
    IFS='.' read -r major minor patch <<< "${current_version}"
    new_upstream="${major}.${minor}.$((patch + 1))"
fi
new_deb_revision="1"
new_version="${new_upstream}-${new_deb_revision}"

message="${2:-Release ${new_upstream}}"

echo "Current version : ${current_version}-${current_deb_revision}"
echo "New version     : ${new_version}"
echo "Message         : ${message}"
echo

# ── Update debian/changelog ───────────────────────────────────────────────────
# Get git log since last tagged/committed changelog entry for automatic notes
git_log=$(git --no-pager log --oneline "$(git rev-list --tags --max-count=1 2>/dev/null || git rev-list --max-parents=0 HEAD)..HEAD" 2>/dev/null | sed 's/^/  * /' || true)
if [[ -z "${git_log}" ]]; then
    git_log="  * ${message}"
fi

new_entry="$(cat <<EOF
fiesta-can-bridge (${new_version}) unstable; urgency=medium

${git_log}

 -- ${MAINTAINER}  ${DATE}

EOF
)"

# Prepend new entry to changelog
echo "${new_entry}" | cat - "${CHANGELOG}" > "${CHANGELOG}.tmp"
mv "${CHANGELOG}.tmp" "${CHANGELOG}"

echo "Updated ${CHANGELOG}"

# ── Build ─────────────────────────────────────────────────────────────────────
echo "Building package..."
dpkg-buildpackage -us -uc -b

# ── Collect artifacts ─────────────────────────────────────────────────────────
mkdir -p "${DIST_DIR}"
deb_file="../fiesta-can-bridge_${new_version}_all.deb"
mv "${deb_file}" "${DIST_DIR}/"

# Clean up other build artifacts from parent dir
rm -f "../fiesta-can-bridge_${new_version}_amd64.buildinfo" \
      "../fiesta-can-bridge_${new_version}_amd64.changes"

echo
echo "✓ Built: ${DIST_DIR}/fiesta-can-bridge_${new_version}_all.deb"
echo
echo "To install on carpi:"
echo "  scp ${DIST_DIR}/fiesta-can-bridge_${new_version}_all.deb semtex@192.168.4.1:/tmp/"
echo "  ssh semtex@192.168.4.1 'sudo apt-get install -y /tmp/fiesta-can-bridge_${new_version}_all.deb'"

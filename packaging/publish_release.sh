#!/usr/bin/env bash
# Publish the GitHub release for the version in src/omniconverter/__init__.py.
#
#   packaging/publish_release.sh DIR_WITH_FILES
#
# Called by CI (needs gh, GH_TOKEN and the GITHUB_* variables):
# - push to main:        creates release + tag v<version> if it does not exist yet, else
#                        does nothing – bump __version__ to get a new release
# - "Run workflow":      same, but refreshes the files of an existing release
# - tag push / release
#   made in the web UI:  uploads the files to that release (tag must match the version)
set -euo pipefail

files_dir=${1:?usage: publish_release.sh DIR_WITH_FILES}
root=$(cd "$(dirname "$0")/.." && pwd)
version=$(python3 -c "import re, pathlib; print(re.search(r'__version__ = \"(.+?)\"', \
pathlib.Path('$root/src/omniconverter/__init__.py').read_text()).group(1))")
tag="v$version"

if [ "${GITHUB_REF_TYPE:-}" = "tag" ] && [ "${GITHUB_REF_NAME:-}" != "$tag" ]; then
  echo "::error::Tag ${GITHUB_REF_NAME} does not match __version__ ${version} (expected ${tag})"
  exit 1
fi

prerelease=()
if [[ "$version" =~ [a-zA-Z-] ]]; then  # e.g. 0.2.0b1, 0.2.0rc1, 0.2.0-beta.1
  prerelease=(--prerelease)
fi

if gh release view "$tag" >/dev/null 2>&1; then
  if [ "${GITHUB_EVENT_NAME:-}" = "push" ] && [ "${GITHUB_REF_TYPE:-}" = "branch" ]; then
    echo "Release $tag already exists – nothing to do (raise __version__ for a new release)."
    exit 0
  fi
  echo "Release $tag exists – uploading the files to it."
  gh release upload "$tag" "$files_dir"/* --clobber
else
  echo "Creating release $tag for ${GITHUB_SHA:-HEAD}."
  gh release create "$tag" "$files_dir"/* \
    --target "${GITHUB_SHA:?}" \
    --title "OmniConverter $version" \
    --notes-file "$root/packaging/release-notes.md" \
    --generate-notes "${prerelease[@]}"
fi

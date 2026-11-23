#!/bin/sh
# Publish a new Parley version:  ./release.sh 1.0.1
# Sets parley/version.py, commits, tags v1.0.1 and pushes. GitHub then builds
# the Windows and Mac installers and publishes the release; installed copies
# offer the update the next time they start.
set -e
cd "$(dirname "$0")"
new="$1"
case "$new" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "Usage: ./release.sh 1.2.3"; exit 1 ;;
esac
if [ -n "$(git status --porcelain)" ]; then
  echo "Commit or discard your changes first:"; git status --short; exit 1
fi
if git rev-parse "v$new" >/dev/null 2>&1; then echo "v$new already exists."; exit 1; fi
sed -i.bak "s/^VERSION = .*/VERSION = \"$new\"/" parley/version.py && rm parley/version.py.bak
git commit -qam "Release $new"
git tag "v$new"
git push origin HEAD "v$new"
echo "Pushed v$new. Follow the build at https://github.com/arkayaga/parley/actions"

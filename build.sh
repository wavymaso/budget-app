#!/bin/bash
# Build Budget.app into dist/.   ./build.sh            build only
#                                ./build.sh --install  build, then replace /Applications/Budget.app
set -euo pipefail
cd "$(dirname "$0")"

INSTALL=0
[[ "${1:-}" == "--install" ]] && INSTALL=1

if [[ ! -x .venv/bin/python ]]; then
  echo "==> Creating virtualenv"
  python3 -m venv .venv
fi
echo "==> Installing dependencies"
.venv/bin/pip install -q -r requirements.txt -r requirements-build.txt

if [[ ! -f macos/Budget.icns ]]; then
  echo "==> Drawing the icon"
  .venv/bin/python macos/make_icon.py
fi

echo "==> Running tests"
.venv/bin/python -m pytest -q

# Lets the built app find data/budget.db in this folder to migrate it on first launch.
.venv/bin/python -c 'import os; print(f"PROJECT_DIR = {os.getcwd()!r}")' > app/_build_info.py

echo "==> Building Budget.app"
rm -rf build dist
.venv/bin/pyinstaller macos/Budget.spec --noconfirm --clean --log-level WARN \
  --distpath dist --workpath build

echo "    $(du -sh dist/Budget.app | cut -f1)  dist/Budget.app"

if [[ $INSTALL == 1 ]]; then
  if pgrep -xq Budget; then
    echo "==> Quitting the running Budget app"
    osascript -e 'quit app "Budget"' || true
    for _ in {1..20}; do pgrep -xq Budget || break; sleep 0.25; done
  fi
  echo "==> Installing to /Applications/Budget.app"
  rm -rf /Applications/Budget.app
  ditto dist/Budget.app /Applications/Budget.app
  rm -rf dist build   # so Spotlight only finds the installed copy
  echo "Done. Open Budget from Spotlight, Launchpad or the Applications folder."
else
  echo "Done. Drag dist/Budget.app into Applications, or run ./build.sh --install"
fi

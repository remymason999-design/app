#!/bin/bash
# Post-merge setup: install backend (pip) + frontend (npm) deps so the next
# workflow restart picks up anything a merged task added. Idempotent and fast.
set -e

cd "$(dirname "$0")/.."

if [ -f backend/requirements.txt ]; then
  echo "==> Installing backend Python deps (uv)"
  # Install into Replit's project-local site-packages (.pythonlibs) — the same
  # path the running interpreter already loads from. System site-packages is
  # read-only on NixOS, so --target is the safe write location.
  # Filter out packages that only exist in private registries (emergentintegrations
  # ships pre-installed in the Replit image and isn't on PyPI).
  TMP_REQ=$(mktemp)
  grep -v '^emergentintegrations' backend/requirements.txt > "$TMP_REQ"
  uv pip install \
    --target .pythonlibs/lib/python3.12/site-packages \
    --python "$(which python3)" \
    --quiet -r "$TMP_REQ"
  rm -f "$TMP_REQ"
fi

if [ -f frontend/package.json ]; then
  echo "==> Installing frontend Node deps"
  cd frontend
  # --legacy-peer-deps: react-day-picker pins an old date-fns peer; matches
  # the lockfile-creating install. Without it npm 9+ ERESOLVE-fails.
  npm install --no-audit --no-fund --prefer-offline --silent --legacy-peer-deps
  cd ..
fi

echo "==> Post-merge setup complete"
#!/bin/bash
# Post-merge setup: install backend (pip) + frontend (npm) deps so the next
# workflow restart picks up anything a merged task added. Idempotent and fast.
set -e

cd "$(dirname "$0")/.."

if [ -f backend/requirements.txt ]; then
  echo "==> Installing backend Python deps (uv)"
  # Install into Replit's project-local site-packages (.pythonlibs) — the same
  # path the running interpreter already loads from. System site-packages is
  # read-only on NixOS, so --target is the safe write location.
  # Filter out packages that only exist in private registries (emergentintegrations
  # ships pre-installed in the Replit image and isn't on PyPI).
  TMP_REQ=$(mktemp)
  grep -v '^emergentintegrations' backend/requirements.txt > "$TMP_REQ"
  uv pip install \
    --target .pythonlibs/lib/python3.12/site-packages \
    --python "$(which python3)" \
    --quiet -r "$TMP_REQ"
  rm -f "$TMP_REQ"
fi

if [ -f frontend/package.json ]; then
  echo "==> Installing frontend Node deps"
  cd frontend
  # --legacy-peer-deps: react-day-picker pins an old date-fns peer; matches
  # the lockfile-creating install. Without it npm 9+ ERESOLVE-fails.
  npm install --no-audit --no-fund --prefer-offline --silent --legacy-peer-deps
  cd ..
fi

echo "==> Post-merge setup complete"

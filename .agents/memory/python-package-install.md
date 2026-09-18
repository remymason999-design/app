---
name: Installing Python packages in this repl
description: How to add a backend Python dependency when pip/uv-add fail with a nix immutable-store error.
---

# Installing Python packages (backend)

The active interpreter is `/home/runner/workspace/.pythonlibs/bin/python3` but it
points at the **read-only nix store**. As a result:

- `installLanguagePackages({language:"python", ...})` (runs `uv add`) → fails:
  `failed to create directory .../nix/store/...: Permission denied`.
- `python3 -m pip install ...` → fails: "command has been disabled ... immutable
  `/nix/store`".
- `uv pip install --python .pythonlibs/bin/python3 ...` → still resolves to the
  nix store and fails.

**What works:** install straight into the existing site-packages dir with uv's
`--target`:
```
uv pip install --target /home/runner/workspace/.pythonlibs/lib/python3.12/site-packages '<pkg>'
```
Then also add the package to `backend/requirements.txt` so it's declared.

**Why:** `--target` writes files to a normal writable directory and never tries
to mutate the nix-store interpreter prefix.

**How to apply:** any time a backend pip/uv install errors on the immutable nix
store, fall back to the `--target` form above (adjust the python3.x version in the
path to match `.pythonlibs/lib/`).

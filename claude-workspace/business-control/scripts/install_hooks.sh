#!/usr/bin/env bash
# Install the repo's git hooks. One hook, one promise: nothing leaves this
# machine that the suite has not passed. (Commits stay fast — the gate is
# the PUSH, where work becomes public.)
set -euo pipefail
ROOT=$(git rev-parse --git-dir)
cat > "$ROOT/hooks/pre-push" <<'HOOK'
#!/usr/bin/env bash
# business-control pre-push: the full smoke suite gates the push.
BC="$(git rev-parse --show-toplevel)/claude-workspace/business-control"
if [ -d "$BC" ]; then
  echo "pre-push: running the business-control suite..."
  (cd "$BC" && PYTHONPATH=src .venv/bin/python tests/test_smoke.py) || {
    echo "pre-push: suite failed — push refused. (git push --no-verify to override.)" >&2
    exit 1
  }
fi
HOOK
chmod +x "$ROOT/hooks/pre-push"
echo "pre-push hook installed: the suite gates every push"

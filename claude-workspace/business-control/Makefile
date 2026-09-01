# business-control — the muscle-memory commands.
# See CLAUDE.md for the conventions these enforce.

PY := .venv/bin/python

.PHONY: test test-core test-studio test-platform dev verify hooks check

test:            ## full suite, three parts in parallel (~75s)
	PYTHONPATH=src $(PY) tests/test_smoke.py

test-core:       ## one part, live output — the debugging mode
	PYTHONPATH=src $(PY) tests/test_smoke.py --only core
test-studio:
	PYTHONPATH=src $(PY) tests/test_smoke.py --only studio
test-platform:
	PYTHONPATH=src $(PY) tests/test_smoke.py --only platform

check:           ## fast syntax gate, no suite
	$(PY) -m compileall -q src tests scripts
	@for f in src/erp/frontend/app/*.js src/storefront/frontend/*.js; do \
	  node --check $$f || exit 1; done
	@echo "syntax clean"

verify:          ## hand-run server on the scratch port (8860 is the preview's)
	$(PY) scripts/launch.py --port 8861

hooks:           ## install the pre-push hook (full suite before any push)
	bash scripts/install_hooks.sh

# Test entry points — one-command wrappers for the "Build & Test" recipes in
# CLAUDE.md, so the fast loop needs no hand-assembled PYTHONPATH.
#
#   make test-fast P=canary F=test_allowlist.py   # one member test file (~seconds)
#   make test-fast P=canary                       # one member suite, serial, fail-fast
#   make test-fast P=canary PP=packages/contract/src   # extra import roots
#   make test-fast                                # root tests/ minus e2e + replay
#   make test                                     # the workspace suite the acceptance gate runs
#
# P  = member directory name under packages/
# F  = one test file inside that member's tests/
# PP = extra colon-separated src roots for cross-member imports
# K  = pytest -k expression
#
# test-fast is deliberately serial (-n 0 semantics: no xdist) and fail-fast:
# xdist worker spin-up ("bringing up nodes") costs more than a member suite
# saves, and two agents each running -n 4 contend for this box's RAM.

# uv lives in ~/.local/bin, which plain non-login shells miss; agents get
# it via claw-forge's toolchain PATH, operators via this fallback.
UV ?= $(shell command -v uv || echo $$HOME/.local/bin/uv)

PYTEST_FAST = $(UV) run --no-sync pytest -q -x -p no:cacheprovider

.PHONY: test test-fast

test-fast:
ifdef P
	PYTHONPATH=src:packages/$(P)/src$(if $(PP),:$(PP)) $(PYTEST_FAST) $(if $(K),-k "$(K)") $(if $(F),packages/$(P)/tests/$(F),packages/$(P)/tests)
else
	$(UV) run --all-packages pytest -q -x $(if $(K),-k "$(K)") tests --ignore=tests/e2e --ignore=tests/replay
endif

test:
	$(UV) run --all-packages pytest -n 4 --dist loadfile

#!/usr/bin/env bash
# Install the repo's git hooks. One hook, one promise: nothing leaves this
# machine that the suite has not passed. (Commits stay fast — the gate is
# the PUSH, where work becomes public.)
set -euo pipefail
ROOT=$(git rev-parse --git-dir)
cat > "$ROOT/hooks/pre-push" <<'HOOK'
#!/usr/bin/env bash
# business-control pre-push: the suite gates the push, on today and on
# three days that are not today.
#
# The dates are here because a suite green on a Tuesday says less than it
# looks about a Sunday, and two fixtures proved it inside a week — one
# meaning "next month" and saying "+35 days", one putting a shift on next
# Monday while a holiday sat on tomorrow. Both were right most days,
# wrong on the rest, and both reached main under a green board.
#
# The two runs go at once rather than one after the other. Four suites on
# four cores is the same work either way, and a hook somebody waits seven
# minutes for is a hook they learn to pass --no-verify to.
#
# Measured on a four-core machine: today alone is under two minutes, and
# today plus the three is nearly seven. That is the honest cost of four
# suites on four cores, so the modes are here to be used rather than
# admired.
#
#   BC_HOOK_DATES=one   one of the three, rotating by the commit being
#                       pushed — the same commit always checks the same
#                       date, so a failure reproduces, and three pushes
#                       cover all three. About four minutes.
#   BC_HOOK_DATES=off   today only, for a typo fix. Under two.
#   BC_HOOK_DATES=all   all seventeen. Go and do something else.
BC="$(git rev-parse --show-toplevel)/claude-workspace/business-control"
[ -d "$BC" ] || exit 0
cd "$BC"

MODE="${BC_HOOK_DATES:-sample}"
case "$MODE" in
  off) echo "pre-push: the suite, today only..." ;;
  one) echo "pre-push: the suite, on today and one other day..." ;;
  all) echo "pre-push: the suite, on today and every awkward day..." ;;
  *)   echo "pre-push: the suite, on today and three other days..." ;;
esac

PYTHONPATH=src .venv/bin/python tests/test_smoke.py > /tmp/bc-hook-today.log 2>&1 &
TODAY=$!

DATES=0
if [ "$MODE" != "off" ]; then
  case "$MODE" in
    all) ARG="" ;;
    one)
      # Deterministic per commit rather than random: a hook that checks a
      # different date every time is a hook whose failures nobody can
      # reproduce, which is how a real bug gets waved through as a flake.
      SAMPLE=(Sun year-end dst-autumn)
      SHA=$(git rev-parse HEAD 2>/dev/null || echo 0)
      IDX=$(( 0x${SHA:0:4} % 3 ))
      ARG="--only ${SAMPLE[$IDX]}"
      echo "pre-push: this commit's date is ${SAMPLE[$IDX]}"
      ;;
    *) ARG="--sample" ;;
  esac
  # shellcheck disable=SC2086
  PYTHONPATH=src .venv/bin/python scripts/audit_dates.py $ARG --jobs 2 \
    > /tmp/bc-hook-dates.log 2>&1 &
  DATES=$!
fi

FAILED=""
wait $TODAY || FAILED="today"
if [ "$DATES" != 0 ]; then
  wait $DATES || FAILED="${FAILED:+$FAILED and }the dated runs"
fi

tail -1 /tmp/bc-hook-today.log
[ "$DATES" != 0 ] && tail -1 /tmp/bc-hook-dates.log

if [ -n "$FAILED" ]; then
  echo "" >&2
  echo "pre-push: $FAILED failed — push refused." >&2
  echo "  today:  /tmp/bc-hook-today.log" >&2
  [ "$DATES" != 0 ] && echo "  dates:  /tmp/bc-hook-dates.log" >&2
  echo "  (BC_HOOK_DATES=off skips the dates; --no-verify skips it all.)" >&2
  exit 1
fi
HOOK
chmod +x "$ROOT/hooks/pre-push"
echo "pre-push hook installed: the suite gates every push, on today and"
echo "on a weekend, a year end and a clock change."

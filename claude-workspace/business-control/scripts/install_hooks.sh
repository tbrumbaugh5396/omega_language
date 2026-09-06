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
# ONE other day by default, not three. Measured on a four-core machine:
# today alone is under two minutes, today plus one is three, today plus
# three is nearly seven. Four suites on four cores is that much work
# however it is arranged.
#
# Seven minutes was the first thing tried and it is the wrong answer, for
# a reason that is about people rather than arithmetic. A hook is only
# worth what it actually runs, and a seven-minute wait on every push is
# how `--no-verify` becomes muscle memory — at which point the gate is
# open on exactly the pushes somebody was in a hurry to make, which are
# not a random sample of pushes.
#
# One is enough here because the hook is not the thorough check and was
# never meant to be. CI runs all three sample dates on every push and all
# seventeen nightly. The hook's job is to catch the obvious before it
# leaves the machine, cheaply enough that nobody minds. Rotating by
# commit, three pushes cover what one sample run covers, and people push
# more than three times.
#
#   BC_HOOK_DATES=sample  all three at once. Seven minutes. Worth it when
#                         you have just touched a date fixture and would
#                         rather not wait for the nightly.
#   BC_HOOK_DATES=off     today only, for a typo fix. Under two.
#   BC_HOOK_DATES=all     all seventeen. Go and do something else.
BC="$(git rev-parse --show-toplevel)/claude-workspace/business-control"
[ -d "$BC" ] || exit 0
cd "$BC"

MODE="${BC_HOOK_DATES:-one}"
case "$MODE" in
  off) echo "pre-push: the suite, today only..." ;;
  sample) echo "pre-push: the suite, on today and three other days..." ;;
  all) echo "pre-push: the suite, on today and every awkward day..." ;;
  *)   echo "pre-push: the suite, on today and one other day..." ;;
esac

PYTHONPATH=src .venv/bin/python tests/test_smoke.py > /tmp/bc-hook-today.log 2>&1 &
TODAY=$!

DATES=0
if [ "$MODE" != "off" ]; then
  case "$MODE" in
    all) ARG="" ;;
    sample) ARG="--sample" ;;
    *)
      # Deterministic per commit rather than random: a hook that checks a
      # different date every time is a hook whose failures nobody can
      # reproduce, which is how a real bug gets waved through as a flake.
      SAMPLE=(Sun year-end dst-autumn)
      SHA=$(git rev-parse HEAD 2>/dev/null || echo 0)
      IDX=$(( 0x${SHA:0:4} % 3 ))
      ARG="--only ${SAMPLE[$IDX]}"
      echo "pre-push: this commit's date is ${SAMPLE[$IDX]}"
      ;;
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
  echo "  (BC_HOOK_DATES=off skips the dates, =sample runs all three;
   --no-verify skips the lot, and is how a gate stops being one.)" >&2
  exit 1
fi
HOOK
chmod +x "$ROOT/hooks/pre-push"

# Keep the connection alive while the hook thinks.
#
# git opens the transport to the remote BEFORE running pre-push, then sits
# there while the hook runs. A hook that takes two minutes usually gets
# away with it; one that takes seven does not, and GitHub closes the
# session with "Connection to github.com closed by remote host" — after
# the suite has passed, so the failure looks like anything except what it
# is. That is the push flake this repo has been living with: not the
# suite, the silence.
git config core.sshCommand \
  "ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=20"
echo "pre-push hook installed: the suite gates every push, on today and"
echo "on one other day, rotating by commit. BC_HOOK_DATES=sample for all"
echo "three; CI runs all three on every push and all seventeen nightly."
echo "ssh keepalive set for this repo, so the remote does not hang up"
echo "while the hook is still running."

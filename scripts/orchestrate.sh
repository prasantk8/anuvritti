#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# ANUVRITTI PRODUCTION ORCHESTRATOR
# Human checkpoints, dependency gating, real verification.
#
# Hardened in TASK-105. Changes from the original:
#   * task selection is delegated to scripts/tracker.py, which is unit-tested.
#     The original iterated `$(jq -r '.phases[].name')` unquoted, so a phase named
#     "Phase 1: Foundations" word-split into three bogus phase names and the task
#     loop silently processed nothing.
#   * a task cannot start until every dependency is `completed`.
#   * tracker.json is schema-validated before and after every run.
#   * verification runs the task's own verification_command, not a blanket test run.
#   * changed files are recorded on the task when it completes.
# ============================================================

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- Configuration (override via environment) ---
: "${MAX_RETRIES:=3}"
: "${AUTO_MODE:=false}"
: "${PRD_PATH:=docs/PRD.md}"
: "${PYTHON:=.venv/bin/python}"
: "${TEST_CMD:=$PYTHON -m pytest}"
: "${CLAUDE_BIN:=claude}"

TRACKER="$ROOT/tracker.json"
TRACKER_CLI="$PYTHON $ROOT/scripts/tracker.py"

# --- Utilities ---
log()  { printf '[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "$*"; }
die()  { log "ERROR: $*"; exit 1; }
warn() { log "WARN: $*"; }

confirm() {
  # confirm <prompt> ; returns 0 to proceed, 1 to skip
  [ "$AUTO_MODE" = "true" ] && return 0
  local reply
  read -r -p "$1 [Y/n/a] " reply
  case "$reply" in
    [Nn]*) return 1 ;;
    [Aa]*) AUTO_MODE=true; return 0 ;;
    *)     return 0 ;;
  esac
}

require() { command -v "$1" >/dev/null 2>&1 || die "$1 not found. $2"; }

# --- Prerequisites ---
require jq "Install with: brew install jq"
[ -x "$PYTHON" ] || die "Python interpreter '$PYTHON' not found. Run: make install"
[ -f "$TRACKER" ] || die "tracker.json not found at $TRACKER"
command -v "$CLAUDE_BIN" >/dev/null 2>&1 || warn "claude CLI not found - AI phases will be skipped"

$TRACKER_CLI validate || die "tracker.json failed validation"

# --- Task helpers (all quoted; no word splitting) ---
task_json()   { jq -e --arg id "$1" '[.phases[].tasks[] | select(.id == $id)][0]' "$TRACKER"; }
task_field()  { task_json "$1" | jq -r --arg f "$2" '.[$f] // ""'; }
set_status()  { $TRACKER_CLI set "$1" "$2" ${3:+--files "$3"} >/dev/null; }

changed_files_since() {
  # Files modified since the marker file was touched. Works with or without git.
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git status --porcelain | awk '{print $NF}' | paste -sd, -
  else
    find src tests docs scripts -newer "$1" -type f 2>/dev/null | paste -sd, -
  fi
}

run_verification() {
  local task_id="$1" cmd
  cmd="$(task_field "$task_id" verification_command)"
  if [ -z "$cmd" ]; then
    warn "$task_id has no verification_command; falling back to $TEST_CMD"
    cmd="$TEST_CMD"
  fi
  log "Verifying $task_id: $cmd"
  bash -c "$cmd"
}

# ============================================================
# PHASE 1: Architectural Decomposition
# ============================================================
log "=== PHASE 1: Architectural Decomposition ==="
if [ -s "$TRACKER" ] && [ "$($TRACKER_CLI next)" != "" ] &&
   jq -e '[.phases[].tasks[]] | length > 0' "$TRACKER" >/dev/null; then
  log "tracker.json already contains $(jq '[.phases[].tasks[]] | length' "$TRACKER") tasks - skipping PRD analysis."
elif confirm "Run PRD analysis with Claude?"; then
  command -v "$CLAUDE_BIN" >/dev/null 2>&1 || die "claude CLI required for PRD analysis"
  "$CLAUDE_BIN" -p "
    You are the Principal Systems Architect.
    Read '$PRD_PATH'.
    1. Produce 'docs/ARCHITECTURE.md' (DDD, bounded contexts, C4, data flow).
    2. Scaffold API contracts in 'docs/contracts/'.
    3. Generate a comprehensive 'tracker.json' with dependency-ordered phases and tasks.
    Each task must have: id (TASK-XXX), description, module_path, verification_command,
    dependencies (array of IDs), status.
  " || die "PRD analysis failed."
  $TRACKER_CLI validate || die "Claude produced an invalid tracker.json"
fi

confirm "Review architecture + tracker.json. Continue to implementation?" || die "Aborted by user."

# ============================================================
# PHASE 2: Dependency-ordered TDD implementation
# ============================================================
log "=== PHASE 2: Autonomous TDD Implementation ==="

processed=0
while :; do
  task_id="$($TRACKER_CLI next)"
  [ -z "$task_id" ] && break

  description="$(task_field "$task_id" description)"
  role="$(task_field "$task_id" role)"
  module_path="$(task_field "$task_id" module_path)"
  deps="$(task_json "$task_id" | jq -r '.dependencies | join(", ")')"

  printf '\n%s\n' "------------------------------------------------------------"
  log ">>> $task_id  [$role]"
  printf '    %s\n    module: %s\n    deps:   %s\n' "$description" "$module_path" "${deps:-none}"

  if ! confirm "Proceed with $task_id?"; then
    log "Skipping $task_id - marking blocked."
    set_status "$task_id" blocked
    continue
  fi

  set_status "$task_id" in_progress
  marker="$(mktemp)"

  attempt=1
  success=false
  while [ "$attempt" -le "$MAX_RETRIES" ]; do
    log "Attempt $attempt/$MAX_RETRIES for $task_id"

    if command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
      # Step A - QA writes the executable specification first.
      "$CLAUDE_BIN" -p "
        Role: Principal QA Automation Engineer.
        Task $task_id from tracker.json: $description
        Read docs/ARCHITECTURE.md and docs/contracts/.
        Write comprehensive unit, integration and edge-case tests under 'tests/'.
        Do NOT write implementation code.
      " || warn "test generation reported an error; continuing to verification"

      # Step B - Engineer makes the specification pass.
      "$CLAUDE_BIN" -p "
        Role: Senior Staff Backend Engineer.
        Task $task_id from tracker.json: $description
        Target module: $module_path
        Implement type-safe, clean production code so the tests pass.
        Respect CLAUDE.md: DDD, hexagonal, Result/Either, no secrets.
      " || warn "implementation reported an error; continuing to verification"
    else
      warn "claude CLI unavailable - verifying existing code only"
    fi

    # Step C - the machine decides, not the model.
    if run_verification "$task_id"; then
      success=true
      break
    fi
    log "Verification failed for $task_id."
    attempt=$((attempt + 1))
  done

  if [ "$success" = true ]; then
    set_status "$task_id" completed "$(changed_files_since "$marker")"
    log "PASS  $task_id"
    processed=$((processed + 1))
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      git add -A
      git commit -q -m "feat($task_id): $description" || log "nothing to commit"
    fi
  else
    set_status "$task_id" blocked
    log "BLOCKED  $task_id after $MAX_RETRIES attempts."
    if [ "$AUTO_MODE" != "true" ]; then
      confirm "Continue with the remaining tasks?" || die "Aborted by user."
    fi
  fi
  rm -f "$marker"
done

log "Processed $processed task(s). Remaining: $($TRACKER_CLI show | grep -c '^\[ \]' || true) pending, $($TRACKER_CLI show | grep -c '^\[!\]' || true) blocked."

# ============================================================
# PHASE 3: Production hardening
# ============================================================
log "=== PHASE 3: Production Hardening ==="
if confirm "Run the DevSecOps audit?"; then
  if command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
    "$CLAUDE_BIN" -p "
      Role: Principal SRE & DevSecOps Lead.
      Audit Dockerfile, CI/CD, observability and security posture.
      Produce docs/HARDENING.md and update tracker.json with any findings.
    " || warn "DevOps audit reported an error"
  else
    warn "claude CLI unavailable - skipping audit"
  fi
fi

$TRACKER_CLI validate
log "=== DONE ==="
$TRACKER_CLI show

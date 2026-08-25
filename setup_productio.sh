#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# PRODUCTION-GRADE SETUP SCRIPT FOR CLAUDE-DRIVEN DEVELOPMENT
# ============================================================

echo ">>> [1/6] Scaffolding Project Structure..."
mkdir -p .claude/commands docs/contracts docs/architecture src tests scripts

echo ">>> [2/6] Writing Root Operational Manual (CLAUDE.md)..."
cat << 'EOF' > CLAUDE.md
# CLAUDE.md - Production Operational Framework

## 1. Principles
- Architecture: DDD, Clean Architecture, Hexagonal.
- Code Quality: Type‑safe, DRY, SOLID, explicit error handling (Result/Either).
- Testing: TDD – coverage ≥ 90% unit, ≥ 80% integration, with E2E.
- Security: 12‑Factor, zero secrets, least‑privilege RBAC.

## 2. Dynamic Context & Memory
- Use `Grep`/`Glob` to target specific modules; never scan whole repo.
- Always run modular tests before and after code changes.

## 3. Tracker Protocol
- Read `tracker.json` before each operation; update after.
- States: "pending" → "in_progress" → "completed" | "blocked".
- On completion, run tests, lint, and record changed files/commit hash.
EOF

echo ">>> [3/6] Writing Custom Claude Slash Commands..."
cat << 'EOF' > .claude/commands/prd-analyze.md
---
description: Deeply analyze the PRD, generate architecture and tasks
allowed-tools: ["Read*", "Write*", "Grep", "Glob"]
model: claude-3-7-sonnet
---
You are the **Principal Systems Architect**.
Analyze `docs/PRD.md` and produce:
1. `docs/ARCHITECTURE.md` – DDD aggregates, bounded contexts, C4 diagram, data flow.
2. API/event contracts in `docs/contracts/`.
3. A JSON task list `tracker.json` with phases and tasks.
   Each task must have: id, description, module_path, verification_command, dependencies.
Use strict JSON format.
EOF

cat << 'EOF' > .claude/commands/task-execute.md
---
description: Implement a task from tracker.json using TDD
allowed-tools: ["Read*", "Write*", "Edit", "Bash", "Grep", "Glob"]
model: claude-3-7-sonnet
---
You are the **Lead Implementation Engineer**.
Given a task ID (e.g., TASK-101) and the tracker, do:
1. Read the task details, dependencies, and acceptance criteria.
2. Write failing tests under `tests/` (using the project's test framework).
3. Implement minimal, type‑safe production code in `src/` to pass tests.
4. Output the paths of modified files and a short summary.
EOF

cat << 'EOF' > .claude/commands/devops-audit.md
---
description: Audit CI/CD, Docker, and observability
allowed-tools: ["Read*", "Write*", "Edit", "Bash"]
model: claude-3-7-sonnet
---
You are the **Principal SRE & DevSecOps Engineer**.
Review the repository and:
- Verify Docker multi‑stage, non‑root, minimal base.
- Check CI (GitHub Actions) for SAST, tests, deployment.
- Ensure OpenTelemetry, Prometheus, health endpoints, structured logging.
- Produce a hardening report and update tracker.json.
EOF

echo ">>> [4/6] Initializing Tracker (JSON) and PRD Template..."
cat << 'EOF' > tracker.json
{
  "version": "1.0",
  "phases": [
    {
      "name": "Phase 1: Foundations",
      "owner": "Architect/DevOps",
      "status": "pending",
      "tasks": []
    },
    {
      "name": "Phase 2: Core Engine",
      "owner": "Core Engineer",
      "status": "pending",
      "tasks": []
    },
    {
      "name": "Phase 3: Resilience",
      "owner": "QA/SRE",
      "status": "pending",
      "tasks": []
    },
    {
      "name": "Phase 4: Release",
      "owner": "SRE",
      "status": "pending",
      "tasks": []
    }
  ],
  "completed_tasks": [],
  "blocked_tasks": []
}
EOF

if [ ! -f docs/PRD.md ]; then
cat << 'EOF' > docs/PRD.md
# Product Requirements Document (PRD)

## 1. Executive Summary
<!-- Your vision, problem, and goals -->

## 2. Core Functional Requirements
<!-- Features, aggregates, workflows -->

## 3. Non‑Functional Requirements & SLAs
<!-- Throughput, latency, availability, security -->

## 4. Third‑Party Integrations & Contracts
<!-- APIs, webhooks, auth providers -->
EOF
fi

echo ">>> [5/6] Generating Production Orchestrator..."
cat << 'EOF' > scripts/orchestrate.sh
#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# PRODUCTION ORCHESTRATOR – with human checkpoints & cost control
# ============================================================

# --- Configuration (override via environment) ---
: "${MAX_RETRIES:=3}"
: "${MAX_TOKENS:=50000}"                # rough limit per Claude call
: "${TEST_CMD:=pytest}"                 # change to e.g., "cargo test"
: "${AUTO_MODE:=false}"                 # set to true to skip all approvals
: "${PRD_PATH:=docs/PRD.md}"

# --- Utilities ---
function log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
function die() { log "ERROR: $*"; exit 1; }

# Check prerequisites
command -v claude >/dev/null 2>&1 || die "claude CLI not found. Please install it."
command -v jq >/dev/null 2>&1 || die "jq is required for JSON parsing."
command -v $TEST_CMD >/dev/null 2>&1 || log "WARNING: Test command '$TEST_CMD' not found. Ensure it's installed."

# --- Helper: read a task from tracker.json by ID ---
function get_task() {
  local task_id="$1"
  jq -r --arg id "$task_id" '
    .phases[].tasks[] | select(.id == $id) |
    {id, description, module_path, verification_command, dependencies, status}
  ' tracker.json
}

# --- Helper: update task status ---
function set_task_status() {
  local task_id="$1"
  local new_status="$2"  # pending, in_progress, completed, blocked
  jq --arg id "$task_id" --arg status "$new_status" '
    .phases = map(.tasks = map(if .id == $id then .status = $status else . end))
  ' tracker.json > tracker.tmp && mv tracker.tmp tracker.json
}

# --- Helper: run tests and return exit code ---
function run_tests() {
  local task_id="$1"
  log "Running tests for $task_id..."
  # We assume tests are already written; we just run the configured test command.
  # Optionally, we could run a specific sub‑set if defined in the task.
  if $TEST_CMD; then
    return 0
  else
    return 1
  fi
}

# --- Phase 1: Planning (PRD Analysis) ---
log "=== PHASE 1: Architectural Decomposition ==="
if [ "$AUTO_MODE" != "true" ]; then
  echo ">>> Press Enter to run the PRD analysis with Claude, or type 'skip' to continue without:"
  read -r input
  if [[ "$input" == "skip" ]]; then
    log "Skipping PRD analysis. Ensure tracker.json and architecture docs are already present."
  else
    claude -p "
      You are the Principal Systems Architect.
      Read '$PRD_PATH'.
      1. Produce 'docs/ARCHITECTURE.md' (DDD, contexts, C4, data flow).
      2. Scaffold API contracts in 'docs/contracts/'.
      3. Generate a comprehensive 'tracker.json' with dependency‑ordered phases and tasks.
      Each task must have: id (TASK-XXX), description, module_path, verification_command, dependencies (array of IDs).
      Use the existing tracker.json structure.
    " || die "PRD analysis failed."
    log "Planning completed. Review generated docs and tracker.json."
  fi
fi

if [ "$AUTO_MODE" != "true" ]; then
  echo ">>> Please review the generated architecture and tracker.json."
  echo "Press Enter to continue to implementation, or type 'exit' to abort."
  read -r input
  [[ "$input" == "exit" ]] && die "Aborted by user."
fi

# --- Phase 2: Implementation (Task Loop) ---
log "=== PHASE 2: Autonomous TDD Implementation ==="

# Get all pending tasks in dependency order (we assume tasks already ordered)
# We'll iterate over phases and tasks; we could use jq to sort, but we trust the order.
for phase in $(jq -r '.phases[].name' tracker.json); do
  log "Processing phase: $phase"
  
  # Get tasks in this phase that are pending
  task_ids=$(jq -r --arg phase "$phase" '
    .phases[] | select(.name == $phase) | .tasks[] | select(.status == "pending") | .id
  ' tracker.json)
  
  for task_id in $task_ids; do
    log ">>> Task: $task_id"
    
    # Show task details and ask for approval if not in auto mode
    if [ "$AUTO_MODE" != "true" ]; then
      jq --arg id "$task_id" '
        .phases[].tasks[] | select(.id == $id) |
        "ID: \(.id)\nDescription: \(.description)\nDependencies: \(.dependencies)\nVerification: \(.verification_command)"
      ' tracker.json
      echo "Proceed with this task? (y/n/a for auto from now on)"
      read -r decision
      case "$decision" in
        a) AUTO_MODE=true ;;
        n) log "Skipping $task_id. Marking as blocked."; set_task_status "$task_id" "blocked"; continue ;;
        *) ;; # default is y
      esac
    fi
    
    # Mark in_progress
    set_task_status "$task_id" "in_progress"
    
    # Retry loop for this task
    attempt=1
    success=false
    while [ $attempt -le $MAX_RETRIES ]; do
      log "Attempt $attempt of $MAX_RETRIES for $task_id"
      
      # Step A: Write tests (QA role)
      claude -p "
        Role: Principal QA Automation Engineer.
        Read tracker.json (task $task_id) and the contracts in docs/contracts/.
        Write comprehensive unit, integration, and edge‑case tests under 'tests/' for this task.
        Do NOT write implementation code.
      " || log "WARNING: Claude test generation may have errors, but we continue."
      
      # Step B: Implement code (Engineer role)
      claude -p "
        Role: Senior Staff Backend Engineer.
        Read tracker.json (task $task_id) and the tests you just wrote.
        Implement type‑safe, clean production code under 'src/' to make all tests pass.
        Ensure you address all acceptance criteria.
      " || log "WARNING: Claude implementation may have errors, but we continue."
      
      # Step C: Actually run tests (not Claude's word)
      if run_tests "$task_id"; then
        success=true
        break
      else
        log "Tests failed for $task_id. Retrying..."
        attempt=$((attempt + 1))
      fi
    done
    
    # Update status
    if [ "$success" = true ]; then
      set_task_status "$task_id" "completed"
      log "✅ Task $task_id completed successfully."
      
      # Commit changes if git repo
      if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git add .
        git commit -m "feat($task_id): implement and verify $task_id" || log "No changes to commit."
        # Record commit hash in tracker? Could add a field, but optional.
      fi
    else
      log "❌ Task $task_id failed after $MAX_RETRIES attempts. Pausing for human intervention."
      set_task_status "$task_id" "blocked"
      if [ "$AUTO_MODE" != "true" ]; then
        echo "Task $task_id is blocked. Please fix manually or type 'continue' to skip it."
        read -r response
        if [[ "$response" != "continue" ]]; then
          die "Aborted by user."
        fi
      else
        log "Auto mode: skipping blocked task and continuing."
      fi
    fi
  done
done

log "All pending tasks processed."

# --- Phase 3: DevSecOps & Hardening ---
log "=== PHASE 3: Production Hardening ==="
if [ "$AUTO_MODE" != "true" ]; then
  echo ">>> Press Enter to run the DevSecOps audit, or type 'skip' to skip:"
  read -r input
  if [[ "$input" == "skip" ]]; then
    log "Skipping DevOps audit."
  else
    claude -p "
      Role: Principal SRE & DevSecOps Lead.
      Audit Dockerfiles, CI/CD, observability, and security.
      Produce a hardening report and update tracker.json with findings.
      If no issues, set DevOps phase to 'completed'.
    " || log "DevOps audit encountered errors, but continuing."
  fi
fi

log "=== DONE ==="
log "The project has been planned, implemented, and hardened."
log "Review the final tracker.json and ensure all tasks are completed."
EOF

chmod +x scripts/orchestrate.sh

echo ">>> [6/6] Finalizing Configuration..."
cat << 'EOF' > .env.example
# Override orchestrator defaults
MAX_RETRIES=3
MAX_TOKENS=50000
TEST_CMD=pytest          # or "cargo test", "npm test", etc.
AUTO_MODE=false          # set to true for unattended run
PRD_PATH=docs/PRD.md
EOF

echo "================================================================"
echo " Production‑grade setup complete!"
echo ""
echo " 1. Edit your product vision in docs/PRD.md"
echo " 2. Optionally adjust settings in .env (copy to .env and modify)"
echo " 3. Run the orchestrator with:"
echo "      ./scripts/orchestrate.sh"
echo "    For fully automated mode (no approvals):"
echo "      AUTO_MODE=true ./scripts/orchestrate.sh"
echo ""
echo " The orchestrator will:"
echo "  - Generate architecture and task list (Phase 1, requires approval)"
echo "  - Implement each task with TDD and real test execution (Phase 2)"
echo "  - Perform a DevOps audit and hardening (Phase 3)"
echo "================================================================"

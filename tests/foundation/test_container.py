"""TASK-730 — the production image's media probe is executable and accounted for."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
PROOF = (ROOT / "scripts" / "verify-production-media-probe.sh").read_text()
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
CONTAINER_STEPS = WORKFLOW["jobs"]["container"]["steps"]
STEPS = "\n".join(str(step) for step in CONTAINER_STEPS)


def test_probe_free_target_is_a_complete_parent_of_production():
    assert "AS runtime-base" in DOCKERFILE
    assert "FROM runtime-base AS runtime" in DOCKERFILE
    assert DOCKERFILE.index("ENTRYPOINT") < DOCKERFILE.index("FROM runtime-base AS runtime")


def test_proof_uses_a_known_one_second_wav_and_real_ffprobe():
    assert "setframerate(8000)" in PROOF
    assert "writeframes(bytes(16000))" in PROOF
    assert "ffprobe -v error" in PROOF
    assert "1.000000" in PROOF


def test_proof_rejects_an_unaccounted_probe_dependency():
    assert "docker image inspect" in PROOF
    assert 'delta_bytes="$((production_bytes - baseline_bytes))"' in PROOF
    assert '"$delta_bytes" -le 0' in PROOF


def test_ci_builds_both_images_and_publishes_the_measurements():
    baseline = next(
        step for step in CONTAINER_STEPS if step.get("name") == "Build probe-free size baseline"
    )
    assert baseline["with"]["target"] == "runtime-base"
    assert "anuvritti:ci-probe-free" in STEPS
    assert "verify-production-media-probe.sh" in STEPS
    assert "GITHUB_STEP_SUMMARY" in PROOF

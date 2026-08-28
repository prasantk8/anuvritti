"""TASK-730/734 — production media probing is executable, lean and accounted for."""

from pathlib import Path

import yaml

from anuvritti.config.settings import DEFAULT_ALLOWED_MEDIA_TYPES

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


def test_proof_covers_every_accepted_phone_audio_container():
    fixture_for_type = {
        "audio/aac": "known.aac",
        "audio/m4a": "known.m4a",
        "audio/mp4": "known.m4a",
        "audio/mpeg": "known.mp3",
        "audio/wav": "known.wav",
        "audio/webm": "known.webm",
        "audio/x-m4a": "known.m4a",
    }
    accepted_audio = {mime for mime in DEFAULT_ALLOWED_MEDIA_TYPES if mime.startswith("audio/")}
    assert accepted_audio == fixture_for_type.keys()
    for fixture in set(fixture_for_type.values()):
        assert fixture in PROOF
    assert "probe-fixtures" in DOCKERFILE


def test_probe_is_a_pinned_minimal_source_build():
    assert "FFPROBE_VERSION=9.0.1" in DOCKERFILE
    assert "ADD --checksum=sha256:" in DOCKERFILE
    assert "--disable-everything" in DOCKERFILE
    assert "--disable-network" in DOCKERFILE
    assert "--disable-static" in DOCKERFILE
    assert "--enable-shared" in DOCKERFILE
    assert "--enable-ffprobe" in DOCKERFILE
    assert "--enable-demuxer=aac,matroska,mov,mp3,ogg,wav" in DOCKERFILE
    assert (
        "apt-get install -y --no-install-recommends ffmpeg"
        not in DOCKERFILE[DOCKERFILE.index("FROM runtime-base AS runtime") :]
    )


def test_probe_runtime_carries_a_reviewable_build_receipt():
    assert "/usr/share/anuvritti/ffprobe-runtime.manifest" in DOCKERFILE
    assert "/usr/share/licenses/ffprobe/COPYING.LGPLv2.1" in DOCKERFILE
    assert "ffprobe runtime manifest" in PROOF


def test_proof_rejects_an_unaccounted_probe_dependency():
    assert "docker image inspect" in PROOF
    assert 'delta_bytes="$((production_bytes - baseline_bytes))"' in PROOF
    assert '"$delta_bytes" -le 0' in PROOF
    assert '"$delta_bytes" -ge "$legacy_delta_bytes"' in PROOF


def test_ci_builds_both_images_and_publishes_the_measurements():
    baseline = next(
        step for step in CONTAINER_STEPS if step.get("name") == "Build probe-free size baseline"
    )
    assert baseline["with"]["target"] == "runtime-base"
    assert "anuvritti:ci-probe-free" in STEPS
    assert "verify-production-media-probe.sh" in STEPS
    assert "GITHUB_STEP_SUMMARY" in PROOF
    fixtures = next(
        step for step in CONTAINER_STEPS if step.get("name") == "Build handset audio fixtures"
    )
    assert fixtures["with"]["target"] == "probe-fixtures"

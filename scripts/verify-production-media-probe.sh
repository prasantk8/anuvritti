#!/bin/sh
# Prove the production image can measure real audio and account for its cost.
set -eu

production_image="${1:-anuvritti:ci}"
baseline_image="${2:-anuvritti:ci-probe-free}"
fixtures_image="${3:-anuvritti:ci-probe-fixtures}"
legacy_delta_bytes=155245809

scratch_dir="$(mktemp -d)"
fixtures_container=""
probe_container=""
cleanup() {
  if [ -n "$fixtures_container" ]; then
    docker rm -f "$fixtures_container" >/dev/null 2>&1 || true
  fi
  if [ -n "$probe_container" ]; then
    docker rm -f "$probe_container" >/dev/null 2>&1 || true
  fi
  rm -rf "$scratch_dir"
}
trap cleanup EXIT INT TERM

fixtures_container="$(docker create --entrypoint true "$fixtures_image")"
docker cp "$fixtures_container:/fixtures" "$scratch_dir/fixtures"
docker rm "$fixtures_container" >/dev/null
fixtures_container=""

# Keep the original mathematically exact WAV proof, then exercise every audio
# container accepted from phones using disposable, generated CI fixtures.
duration="$(docker run --rm --entrypoint sh "$production_image" -c \
  'python -c '\''import wave; p="/tmp/known.wav"; w=wave.open(p,"wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(bytes(16000)); w.close()'\'' && ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 /tmp/known.wav')"

case "$duration" in
  1.000000) ;;
  *) echo "production ffprobe measured ${duration:-nothing}; expected 1.000000" >&2; exit 1 ;;
esac

format_measurements=""
for fixture in known.aac known.m4a known.mp3 known.wav known.webm; do
  probe_container="$(docker create --entrypoint ffprobe "$production_image" \
    -v error -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 "/tmp/$fixture")"
  docker cp "$scratch_dir/fixtures/$fixture" "$probe_container:/tmp/$fixture"
  measured="$(docker start --attach "$probe_container")"
  docker rm "$probe_container" >/dev/null
  probe_container=""
  python3 - "$fixture" "$measured" <<'PY'
import sys

name, raw = sys.argv[1:]
duration = float(raw)
if not 0.90 <= duration <= 1.25:
    raise SystemExit(f"{name} measured {duration:.6f}s; expected a one-second recording")
PY
  format_measurements="${format_measurements}${fixture}: ${measured} seconds
"
done

production_bytes="$(docker image inspect "$production_image" --format '{{.Size}}')"
baseline_bytes="$(docker image inspect "$baseline_image" --format '{{.Size}}')"
delta_bytes="$((production_bytes - baseline_bytes))"
if [ "$delta_bytes" -le 0 ]; then
  echo "production image did not account for a positive media-probe size delta" >&2
  exit 1
fi
if [ "$delta_bytes" -ge "$legacy_delta_bytes" ]; then
  echo "minimal probe delta $delta_bytes did not beat legacy Debian ffmpeg delta $legacy_delta_bytes" >&2
  exit 1
fi

manifest="$(docker run --rm --entrypoint cat "$production_image" \
  /usr/share/anuvritti/ffprobe-runtime.manifest)"

echo "ffprobe duration: $duration seconds"
printf '%s' "$format_measurements"
echo "probe-free image: $baseline_bytes bytes"
echo "production image: $production_bytes bytes"
echo "media-probe delta: $delta_bytes bytes"
echo "ffprobe runtime manifest:"
echo "$manifest"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Production media probe"
    echo
    echo "| Proof | Measurement |"
    echo "| --- | ---: |"
    echo "| Known WAV duration | $duration seconds |"
    echo "| Accepted audio containers | AAC, M4A, MP3, WAV, WebM |"
    echo "| Probe-free image | $baseline_bytes bytes |"
    echo "| Production image | $production_bytes bytes |"
    echo "| Minimal ffprobe runtime delta | +$delta_bytes bytes |"
    echo "| Previous Debian ffmpeg delta | +$legacy_delta_bytes bytes |"
    echo
    echo '```text'
    echo "$manifest"
    echo '```'
  } >> "$GITHUB_STEP_SUMMARY"
fi

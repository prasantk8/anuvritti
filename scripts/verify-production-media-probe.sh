#!/bin/sh
# Prove the production image can measure real audio and account for its cost.
set -eu

production_image="${1:-anuvritti:ci}"
baseline_image="${2:-anuvritti:ci-probe-free}"

# Generate and probe in one container because separate runs do not share /tmp.
duration="$(docker run --rm --entrypoint sh "$production_image" -c \
  'python -c '\''import wave; p="/tmp/known.wav"; w=wave.open(p,"wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(bytes(16000)); w.close()'\'' && ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 /tmp/known.wav')"

case "$duration" in
  1.000000) ;;
  *) echo "production ffprobe measured ${duration:-nothing}; expected 1.000000" >&2; exit 1 ;;
esac

production_bytes="$(docker image inspect "$production_image" --format '{{.Size}}')"
baseline_bytes="$(docker image inspect "$baseline_image" --format '{{.Size}}')"
delta_bytes="$((production_bytes - baseline_bytes))"
if [ "$delta_bytes" -le 0 ]; then
  echo "production image did not account for a positive media-probe size delta" >&2
  exit 1
fi

echo "ffprobe duration: $duration seconds"
echo "probe-free image: $baseline_bytes bytes"
echo "production image: $production_bytes bytes"
echo "media-probe delta: $delta_bytes bytes"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Production media probe"
    echo
    echo "| Proof | Measurement |"
    echo "| --- | ---: |"
    echo "| Known WAV duration | $duration seconds |"
    echo "| Probe-free image | $baseline_bytes bytes |"
    echo "| Production image | $production_bytes bytes |"
    echo "| ffprobe runtime delta | +$delta_bytes bytes |"
  } >> "$GITHUB_STEP_SUMMARY"
fi

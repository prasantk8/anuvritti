"""Verify a rendered film against its portable receipt, entirely offline.

This deliberately does not need the FilmExport. The export contains plaintext family
material and should already have been deleted; the render manifest is the lasting receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from filmkit.compositor import probe
from filmkit.process import CommandError

from anuvritti.adapters.authenticity import (
    family_authentication_tag,
    family_key_id,
    validate_family_key,
)
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result

_SCHEMA = "anuvritti.render-manifest.v1"
_ANCHOR_SCHEMA = "anuvritti.render-anchor.v2"
_LEGACY_ANCHOR_SCHEMA = "anuvritti.render-anchor.v1"
_ANCHOR_CONTEXT = b"anuvritti-render-receipt-v1\0"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class FilmVerification:
    """The evidence inspected in one successful verification."""

    manifest: Path
    film: Path
    checked: tuple[Path, ...]
    retained_frames: int
    authenticated: bool = False
    skipped: tuple[str, ...] = ()


class RenderReceiptAuthenticator:
    """Bind a receipt to a secret held separately by the family."""

    def anchor(self, manifest: Path, *, key: bytes, destination: Path) -> Result[Path, DomainError]:
        try:
            validate_family_key(key)
            body = manifest.read_bytes()
            payload = {
                "schema": _ANCHOR_SCHEMA,
                "key_id": family_key_id(key),
                "manifest": manifest.name,
                "manifest_sha256": hashlib.sha256(body).hexdigest(),
                "hmac_sha256": _authentication_tag(body, key),
            }
            destination.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return Ok(destination)
        except (OSError, TypeError, ValueError) as exc:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "the render receipt could not be anchored",
                    {"manifest": str(manifest), "finding": str(exc)},
                )
            )

    def authenticate(
        self, manifest: Path, *, key: bytes, anchor: Path
    ) -> Result[None, DomainError]:
        try:
            validate_family_key(key)
            body = manifest.read_bytes()
            payload = _object(json.loads(anchor.read_text(encoding="utf-8")), "anchor")
            schema = payload.get("schema")
            if schema not in {_ANCHOR_SCHEMA, _LEGACY_ANCHOR_SCHEMA}:
                raise ValueError("render receipt authentication failed")
            expected = {
                "schema": cast(str, schema),
                "manifest": manifest.name,
                "manifest_sha256": hashlib.sha256(body).hexdigest(),
                "hmac_sha256": _authentication_tag(body, key),
            }
            if schema == _ANCHOR_SCHEMA:
                expected["key_id"] = family_key_id(key)
            if any(
                not isinstance(payload.get(field), str)
                or not hmac.compare_digest(payload[field], value)
                for field, value in expected.items()
            ):
                raise ValueError("render receipt authentication failed")
            return Ok(None)
        except (KeyError, OSError, TypeError, ValueError):
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "the render receipt is not authentic",
                    {
                        "manifest": str(manifest),
                        "findings": ["render receipt authentication failed"],
                    },
                )
            )


class OfflineFilmVerifier:
    """Check receipt hashes and the encoded timeline without archive or network access."""

    def verify(
        self,
        manifest: Path,
        *,
        film: Path | None = None,
        frames: Path | None = None,
        anchor: Path | None = None,
        key: bytes | None = None,
    ) -> Result[FilmVerification, DomainError]:
        try:
            if (anchor is None) != (key is None):
                raise ValueError("anchor and family key must be supplied together")
            authenticated = False
            if anchor is not None and key is not None:
                authentication = RenderReceiptAuthenticator().authenticate(
                    manifest, key=key, anchor=anchor
                )
                if authentication.is_err():
                    return Err(authentication.unwrap_err())
                authenticated = True
            payload = _object(json.loads(manifest.read_text(encoding="utf-8")), "manifest")
            if payload.get("schema") != _SCHEMA:
                raise ValueError(f"schema must be {_SCHEMA}")
            output = _object(payload.get("output"), "output")
            timeline = _object(payload.get("timeline"), "timeline")
            frame_receipts = _objects(payload.get("frames"), "frames")
            output_name = _portable_name(output.get("path"), "output.path")
            film_path = film if film is not None else manifest.parent / output_name

            findings = _digest_findings(film_path, output)
            checked = [film_path]
            if not findings:
                findings.extend(_probe_findings(film_path, timeline, output))

            retained = 0
            skipped: tuple[str, ...] = ()
            if frames is None:
                count = len(frame_receipts)
                noun = "frame" if count == 1 else "frames"
                verb = "was" if count == 1 else "were"
                skipped = (f"{count} retained {noun} {verb} not supplied",) if count else ()
            else:
                for receipt in frame_receipts:
                    frame_name = _portable_name(receipt.get("path"), "frames[].path")
                    frame_path = frames / frame_name
                    checked.append(frame_path)
                    findings.extend(_digest_findings(frame_path, receipt))
                    if frame_path.is_file():
                        retained += 1

            if findings:
                return Err(
                    DomainError(
                        ErrorCode.CONFLICT,
                        "the rendered film no longer agrees with its manifest",
                        {"manifest": str(manifest), "findings": findings},
                    )
                )
            return Ok(
                FilmVerification(
                    manifest=manifest,
                    film=film_path,
                    checked=tuple(checked),
                    retained_frames=retained,
                    authenticated=authenticated,
                    skipped=skipped,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "the render manifest is not a valid portable receipt",
                    {"manifest": str(manifest), "findings": [f"invalid manifest: {exc}"]},
                )
            )
        except OSError as exc:
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "the rendered film could not be inspected",
                    {"manifest": str(manifest), "findings": [str(exc)]},
                )
            )
        except CommandError as exc:
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "the rendered film could not be inspected",
                    {
                        "manifest": str(manifest),
                        "findings": [f"ffprobe refused the film: {exc.result.returncode}"],
                    },
                )
            )


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} is not an object")
    return cast(dict[str, Any], value)


def _authentication_tag(manifest: bytes, key: bytes) -> str:
    return family_authentication_tag(manifest, key=key, context=_ANCHOR_CONTEXT)


def _objects(value: object, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError(f"{name} is not a list")
    return [_object(item, name) for item in value]


def _portable_name(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_NAME.fullmatch(value):
        raise ValueError(f"{field} must be a portable file name")
    return value


def _expected_int(receipt: dict[str, Any], field: str) -> int:
    value = receipt.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _expected_float(receipt: dict[str, Any], field: str) -> float:
    value = receipt.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{field} must be a positive number")
    return float(value)


def _expected_sha(receipt: dict[str, Any]) -> str:
    value = receipt.get("sha256")
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("sha256 must be a lowercase SHA-256 digest")
    return value


def _digest_findings(path: Path, receipt: dict[str, Any]) -> list[str]:
    expected_bytes = _expected_int(receipt, "bytes")
    expected_sha = _expected_sha(receipt)
    if not path.is_file():
        return [f"missing artifact {path.name}"]
    findings: list[str] = []
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes:
        findings.append(
            f"changed artifact {path.name}: byte count {actual_bytes} != {expected_bytes}"
        )
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        findings.append(f"changed artifact {path.name}: sha256 {actual_sha} != {expected_sha}")
    return findings


def _probe_findings(film: Path, timeline: dict[str, Any], output: dict[str, Any]) -> list[str]:
    inspected = _object(probe(film), "ffprobe")
    streams = _objects(inspected.get("streams"), "ffprobe.streams")
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(streams) != 2 or len(videos) != 1 or len(audios) != 1:
        return [
            f"invalid film {film.name}: expected one video and one audio stream, "
            f"found {len(videos)} video and {len(audios)} audio"
        ]

    expected_width = _expected_int(timeline, "width")
    expected_height = _expected_int(timeline, "height")
    actual_width = int(videos[0].get("width", 0))
    actual_height = int(videos[0].get("height", 0))
    findings: list[str] = []
    if (actual_width, actual_height) != (expected_width, expected_height):
        findings.append(
            f"invalid film {film.name}: frame size {actual_width}x{actual_height} "
            f"does not match timeline {expected_width}x{expected_height}"
        )

    expected_duration = _expected_float(timeline, "duration_seconds")
    receipt_duration = _expected_float(output, "duration_seconds")
    fps = _expected_int(timeline, "fps")
    if fps == 0:
        raise ValueError("fps must be greater than zero")
    actual_duration = float(_object(inspected.get("format"), "ffprobe.format")["duration"])
    tolerance = 1 / fps
    if abs(receipt_duration - expected_duration) > tolerance:
        findings.append(
            f"invalid manifest: output duration {receipt_duration:.6f}s does not match "
            f"timeline {expected_duration:.6f}s"
        )
    if abs(actual_duration - expected_duration) > tolerance:
        findings.append(
            f"invalid film {film.name}: duration {actual_duration:.6f}s does not match "
            f"timeline {expected_duration:.6f}s"
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a rendered film against its receipt")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--film", type=Path)
    parser.add_argument("--frames", type=Path)
    parser.add_argument("--anchor", type=Path)
    parser.add_argument("--key", type=Path, help="family-held key file; never store with film")
    parser.add_argument("--write-anchor", type=Path)
    arguments = parser.parse_args()
    if arguments.write_anchor is not None:
        if arguments.key is None:
            parser.error("--write-anchor requires --key")
        anchored = RenderReceiptAuthenticator().anchor(
            arguments.manifest,
            key=arguments.key.read_bytes(),
            destination=arguments.write_anchor,
        )
        if anchored.is_err():
            print(anchored.unwrap_err().message)
            return 1
        print(f"anchored {arguments.manifest} at {anchored.unwrap()}")
        return 0
    result = OfflineFilmVerifier().verify(
        arguments.manifest,
        film=arguments.film,
        frames=arguments.frames,
        anchor=arguments.anchor,
        key=arguments.key.read_bytes() if arguments.key is not None else None,
    )
    if result.is_err():
        error = result.unwrap_err()
        print(error.message)
        for finding in cast(list[str], error.details["findings"]):
            print(f"- {finding}")
        return 1
    report = result.unwrap()
    print(f"verified {report.film} against {report.manifest}")
    print(f"checked {len(report.checked)} artifact(s), including {report.retained_frames} frame(s)")
    print(
        "receipt authentication: family key verified"
        if report.authenticated
        else "receipt authentication: not requested"
    )
    for skipped in report.skipped:
        print(f"not checked: {skipped}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as an operator command
    raise SystemExit(main())

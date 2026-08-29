"""The HTTP interface.

Thin by design: parse, delegate to a use case, render. No business rule lives here, so no
business rule can be bypassed by calling a different endpoint. Implements
docs/contracts/openapi.yaml.

Since TASK-511 every route below the pairing boundary takes a `DeviceIdentity` rather than
an id from the request. That is the difference between an API that is authenticated and one
that merely has a login screen: there is no handler here that *could* read another family's
archive, because none of them is given a family id it did not get from the token.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from anuvritti.application.access import DeviceIdentity
from anuvritti.application.capture import (
    CaptureSparkCommand,
    OverrideFieldCommand,
    RecordWhyCommand,
)
from anuvritti.application.moments import MarkAsDoneCommand
from anuvritti.application.presence import (
    CaptureLittleThingCommand,
    CaptureRightNowCommand,
)
from anuvritti.application.privacy import DeleteFamilyDataCommand, ExportFamilyDataQuery
from anuvritti.application.returning import (
    RespondToSuggestionCommand,
    SuggestionResponse,
    WorthBringingBackQuery,
)
from anuvritti.application.vault import SearchVaultQuery
from anuvritti.application.voice import (
    CorrectTranscriptCommand,
    GetVoiceNoteQuery,
    KeepVoiceNoteCommand,
    ListVoiceNotesQuery,
)
from anuvritti.config.logging import configure_logging, get_logger
from anuvritti.config.settings import Settings
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.presence import RightNowSnapshot
from anuvritti.domain.values import (
    AgeRange,
    MemberRole,
    SourceKind,
    SourceRef,
    SparkStatus,
)
from anuvritti.domain.voice import VoiceNote
from anuvritti.interfaces.http import idempotency
from anuvritti.interfaces.http.auth import (
    UNAUTHENTICATED,
    Refused,
    presented_token,
    same_family,
    same_member,
)
from anuvritti.interfaces.http.container import Container, build_container
from anuvritti.interfaces.http.errors import error_response
from anuvritti.interfaces.http.observability import install_observability
from anuvritti.interfaces.http.schemas import (
    CaptureLittleThingRequest,
    CaptureRightNowRequest,
    CaptureSparkRequest,
    ClaimPairingRequest,
    CorrectTranscriptRequest,
    CreateChildRequest,
    CreateFamilyRequest,
    KeepVoiceNoteRequest,
    MarkAsDoneRequest,
    OverrideFieldRequest,
    RecordWhyRequest,
    SourceRequest,
    SuggestionResponseRequest,
    parse_intent,
    render_device,
    render_family,
    render_little_thing,
    render_moment,
    render_right_now,
    render_spark,
    render_suggestion,
    render_voice,
)
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import (
    ChildId,
    DeviceId,
    FamilyId,
    MediaId,
    MemberId,
    SparkId,
)
from anuvritti.shared.result import Err, Ok, Result

log = get_logger("http")

# FastAPI marker objects, hoisted so they are not re-created per call (ruff B008).
_UPLOAD_FILE = File(...)
_FORM_FAMILY_ID = Form(default=None)
_IDEMPOTENCY_KEY = Header(default=None, alias=idempotency.HEADER)


def _invalid(message: str, **details: Any) -> JSONResponse:
    return error_response(DomainError(ErrorCode.VALIDATION_FAILED, message, details))


def _build_source(request: SourceRequest) -> Result[SourceRef, DomainError]:
    """Turn wire input into a validated SourceRef, or explain why it cannot be one.

    The value objects raise on invalid input because that is the right shape for a
    constructor; the boundary is where that becomes an `Err` (ADR-0002).
    """
    try:
        if request.kind is SourceKind.URL:
            if not request.url:
                raise ValueError("a url source requires a url")
            return Ok(
                SourceRef.from_url(
                    request.url, creator=request.creator, title=request.title, text=request.text
                )
            )
        if request.kind is SourceKind.TEXT:
            return Ok(SourceRef.from_text(request.text or ""))
        if not request.media_id:
            raise ValueError(f"a {request.kind.value.lower()} source requires a media_id")
        return Ok(SourceRef.from_media(request.kind, media_id=request.media_id, text=request.text))
    except ValueError as exc:
        return Err(DomainError(ErrorCode.CAPTURE_SOURCE_INVALID, str(exc)))


def create_app(settings: Settings, *, container: Container | None = None) -> FastAPI:
    """Build the ASGI app. `container` is injectable so tests run against a real stack."""
    configure_logging(settings.log_level)
    box = container or build_container(settings)

    app = FastAPI(
        title="Anuvritti",
        version="0.2.0",
        description="For the little things you don't want life to erase.",
        docs_url="/docs" if settings.expose_api_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
    )
    app.state.container = box
    app.state.settings = settings
    install_observability(app, box)

    @app.exception_handler(Refused)
    def _refused(_: Request, exc: Refused) -> Response:
        """Keep the error envelope in docs/contracts/errors.md, even when a guard raises."""
        return error_response(exc.error)

    def get_box(request: Request) -> Container:
        container_from_state: Container = request.app.state.container
        return container_from_state

    box_dep = Depends(get_box)

    def get_identity(request: Request) -> DeviceIdentity:
        """The only way a handler learns whose family it is looking at."""
        current: Container = request.app.state.container
        resolved = current.authenticate_device.execute(presented_token(request))
        if resolved.is_err():
            raise Refused(UNAUTHENTICATED)
        return resolved.unwrap()

    me = Depends(get_identity)

    # ------------------------------------------------------------------- pairing
    # Bootstrap and claim are the only two routes below /v1 that are reachable without a
    # token, because both exist to obtain one. Everything else is closed.
    @app.post("/v1/families", status_code=201)
    def create_family(body: CreateFamilyRequest, box: Container = box_dep) -> Response:
        """Bootstrap: create the family and pair the device that created it.

        The founding device is paired by this act rather than by a second call, because a
        window between "the family exists" and "the family is protected" is a window someone
        else can walk through.
        """
        if box.settings.is_production and box.families.count() > 0:
            # A production box serves one family (PRD 44, 49). Once it has one, this route
            # is the only unauthenticated way in, so it closes behind them. Second families
            # are TASK-901's problem, and they will arrive with real accounts.
            return error_response(
                DomainError(ErrorCode.CONFLICT, "this server already belongs to a family")
            )

        now = box.clock.now()
        owner = Member(MemberId(box.ids.new_id()), body.owner_display_name, MemberRole.PARENT)
        family = Family(
            id=FamilyId(box.ids.new_id()),
            name=body.name,
            members=(owner,),
            children=(),
            created_at=now,
        )
        with box.uow:
            box.families.save(family)
            box.uow.commit()

        paired = box.pair_device.execute(
            family_id=family.id, member_id=owner.id, display_name="This device"
        )
        if paired.is_err():  # pragma: no cover - only a store failure reaches here
            return error_response(paired.unwrap_err())

        rendered = render_family(family, box.clock.today())
        rendered["device"] = {
            **render_device(paired.unwrap().device),
            # The one moment the token exists in plaintext. It is never returned again.
            "token": paired.unwrap().token.value,
        }
        return JSONResponse(status_code=201, content=rendered)

    @app.post("/v1/pairing/codes", status_code=201)
    def open_pairing(identity: DeviceIdentity = me, box: Container = box_dep) -> Response:
        """Show a code on a device that is already trusted."""
        result = box.open_pairing.execute(identity)
        if result.is_err():  # pragma: no cover - only a store failure reaches here
            return error_response(result.unwrap_err())
        code = result.unwrap()
        return JSONResponse(
            status_code=201,
            content={
                "code": code.formatted(),
                "expires_in_seconds": int(box.pairing_ttl.total_seconds()),
            },
        )

    @app.post("/v1/pairing/claim", status_code=201)
    def claim_pairing(body: ClaimPairingRequest, box: Container = box_dep) -> Response:
        """Turn eight typed characters into a paired device."""
        result = box.claim_pairing.execute(typed_code=body.code, display_name=body.device_name)
        if result.is_err():
            return error_response(result.unwrap_err())
        paired = result.unwrap()
        family = box.families.get(paired.device.family_id)
        if family.is_err():  # pragma: no cover - claim already proved the family exists
            return error_response(family.unwrap_err())
        return JSONResponse(
            status_code=201,
            content={
                "device": {**render_device(paired.device), "token": paired.token.value},
                "family": render_family(family.unwrap(), box.clock.today()),
            },
        )

    @app.get("/v1/devices")
    def list_devices(identity: DeviceIdentity = me, box: Container = box_dep) -> Response:
        result = box.list_devices.execute(identity)
        if result.is_err():  # pragma: no cover - only a store failure reaches here
            return error_response(result.unwrap_err())
        return JSONResponse(content=[render_device(d) for d in result.unwrap()])

    @app.delete("/v1/devices/{device_id}")
    def revoke_device(
        device_id: str, identity: DeviceIdentity = me, box: Container = box_dep
    ) -> Response:
        result = box.revoke_device.execute(identity, device_id=DeviceId(device_id))
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(content=render_device(result.unwrap()))

    # ---------------------------------------------------------------- families
    @app.get("/v1/families/{family_id}")
    def get_family(
        family_id: str, identity: DeviceIdentity = me, box: Container = box_dep
    ) -> Response:
        same_family(identity, family_id)
        found = box.families.get(identity.family_id)
        if found.is_err():
            return error_response(found.unwrap_err())
        return JSONResponse(content=render_family(found.unwrap(), box.clock.today()))

    @app.post("/v1/families/{family_id}/children", status_code=201)
    def add_child(
        family_id: str,
        body: CreateChildRequest,
        identity: DeviceIdentity = me,
        box: Container = box_dep,
    ) -> Response:
        same_family(identity, family_id)
        found = box.families.get(identity.family_id)
        if found.is_err():
            return error_response(found.unwrap_err())
        if body.date_of_birth > box.clock.today():
            return _invalid("date_of_birth cannot be in the future")

        member = Member(MemberId(box.ids.new_id()), body.display_name, MemberRole.CHILD)
        child = ChildProfile(
            ChildId(box.ids.new_id()), member.id, body.display_name, body.date_of_birth
        )
        updated = found.unwrap().with_member(member).add_child(child)
        if updated.is_err():
            return error_response(updated.unwrap_err())
        with box.uow:
            box.families.save(updated.unwrap())
            box.uow.commit()
        return JSONResponse(
            status_code=201,
            content={
                "id": str(child.id),
                "display_name": child.display_name,
                "date_of_birth": child.date_of_birth.isoformat(),
                "age_years": child.age_years(box.clock.today()),
            },
        )

    # ------------------------------------------------------------------ sparks
    @app.post("/v1/sparks", status_code=201)
    def capture_spark(
        body: CaptureSparkRequest,
        identity: DeviceIdentity = me,
        idempotency_key: str | None = _IDEMPOTENCY_KEY,
        box: Container = box_dep,
    ) -> Response:
        same_family(identity, body.family_id)
        same_member(identity, body.owner_id)

        def perform() -> Response:
            source = _build_source(body.source)
            if source.is_err():
                return error_response(source.unwrap_err())

            result = box.capture_spark.execute(
                CaptureSparkCommand(
                    family_id=identity.family_id,
                    owner_id=identity.member_id,
                    subject_child_id=(
                        ChildId(body.subject_child_id) if body.subject_child_id else None
                    ),
                    source=source.unwrap(),
                    note=body.note,
                    visibility=body.visibility,
                )
            )
            if result.is_err():
                return error_response(result.unwrap_err())
            log.info("spark captured", extra={"spark_id": str(result.unwrap().id)})
            return JSONResponse(
                status_code=201, content=render_spark(result.unwrap(), now=box.clock.now())
            )

        return idempotency.replay_or_perform(
            store=box.idempotency,
            clock=box.clock,
            key=idempotency_key,
            family_id=identity.family_id,
            endpoint="POST /v1/sparks",
            payload=body.model_dump(mode="json"),
            perform=perform,
        )

    @app.get("/v1/sparks")
    def search_sparks(
        q: str | None = None,
        intent: str | None = None,
        child_id: str | None = None,
        age: int | None = None,
        status: str | None = None,
        limit: int = Query(default=25, ge=1, le=100),
        family_id: str | None = None,
        actor_id: str | None = None,
        identity: DeviceIdentity = me,
        box: Container = box_dep,
    ) -> Response:
        same_family(identity, family_id)
        same_member(identity, actor_id)
        parsed_intent = parse_intent(intent) if intent else None
        if intent and parsed_intent is None:
            return _invalid(f"{intent!r} is not one of the six V0 intents")
        try:
            parsed_status = SparkStatus(status.upper()) if status else None
        except ValueError:
            return _invalid(f"{status!r} is not a spark status")

        result = box.search_vault.execute(
            SearchVaultQuery(
                family_id=identity.family_id,
                actor_id=identity.member_id,
                text=q,
                intent=parsed_intent,
                child_id=ChildId(child_id) if child_id else None,
                age_years=age,
                status=parsed_status,
                limit=limit,
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        now = box.clock.now()
        return JSONResponse(content=[render_spark(s, now=now) for s in result.unwrap()])

    @app.get("/v1/sparks/{spark_id}")
    def get_spark(
        spark_id: str, identity: DeviceIdentity = me, box: Container = box_dep
    ) -> Response:
        found = _spark_in_family(box, identity, spark_id)
        if found.is_err():
            return error_response(found.unwrap_err())
        spark = found.unwrap()
        return JSONResponse(
            content=render_spark(
                spark,
                now=box.clock.now(),
                voice=_voice_behind(box, spark.why.voice_media_id if spark.why else None),
            )
        )

    @app.post("/v1/sparks/{spark_id}/why")
    def record_why(
        spark_id: str,
        body: RecordWhyRequest,
        identity: DeviceIdentity = me,
        box: Container = box_dep,
    ) -> Response:
        owned = _spark_in_family(box, identity, spark_id)
        if owned.is_err():
            return error_response(owned.unwrap_err())
        result = box.record_why.execute(
            RecordWhyCommand(
                spark_id=SparkId(spark_id), text=body.text, voice_media_id=body.voice_media_id
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        spark = result.unwrap()
        return JSONResponse(
            content=render_spark(
                spark,
                now=box.clock.now(),
                voice=_voice_behind(box, spark.why.voice_media_id if spark.why else None),
            )
        )

    @app.post("/v1/sparks/{spark_id}/override")
    def override_field(
        spark_id: str,
        body: OverrideFieldRequest,
        identity: DeviceIdentity = me,
        box: Container = box_dep,
    ) -> Response:
        owned = _spark_in_family(box, identity, spark_id)
        if owned.is_err():
            return error_response(owned.unwrap_err())

        value: Any = body.value
        if body.field == "intent":
            value = parse_intent(body.value)
            if value is None:
                return _invalid(f"{body.value!r} is not one of the six V0 intents")
        elif body.field == "age_range":
            if not isinstance(body.value, dict):
                return _invalid("age_range must be {min_years, max_years}")
            try:
                value = AgeRange(
                    int(body.value.get("min_years", -1)), int(body.value.get("max_years", -1))
                )
            except (ValueError, TypeError) as exc:
                return _invalid(str(exc))

        result = box.override_field.execute(
            OverrideFieldCommand(spark_id=SparkId(spark_id), field=body.field, value=value)
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(content=render_spark(result.unwrap(), now=box.clock.now()))

    @app.post("/v1/sparks/{spark_id}/done", status_code=201)
    def mark_as_done(
        spark_id: str,
        body: MarkAsDoneRequest,
        identity: DeviceIdentity = me,
        idempotency_key: str | None = _IDEMPOTENCY_KEY,
        box: Container = box_dep,
    ) -> Response:
        same_member(identity, body.created_by)
        owned = _spark_in_family(box, identity, spark_id)
        if owned.is_err():
            return error_response(owned.unwrap_err())

        def perform() -> Response:
            result = box.mark_as_done.execute(
                MarkAsDoneCommand(
                    spark_id=SparkId(spark_id),
                    created_by=identity.member_id,
                    happened_on=body.happened_on,
                    reflection=body.reflection,
                    photo_media_id=body.photo_media_id,
                    audio_media_id=body.audio_media_id,
                )
            )
            if result.is_err():
                return error_response(result.unwrap_err())
            return JSONResponse(status_code=201, content=render_moment(result.unwrap()))

        return idempotency.replay_or_perform(
            store=box.idempotency,
            clock=box.clock,
            key=idempotency_key,
            family_id=identity.family_id,
            endpoint=f"POST /v1/sparks/{spark_id}/done",
            payload=body.model_dump(mode="json"),
            perform=perform,
        )

    # ------------------------------------------------------------------ return
    @app.get("/v1/return/worth-bringing-back")
    def worth_bringing_back(
        child_id: str | None = None,
        family_id: str | None = None,
        actor_id: str | None = None,
        identity: DeviceIdentity = me,
        box: Container = box_dep,
    ) -> Response:
        same_family(identity, family_id)
        same_member(identity, actor_id)
        result = box.worth_bringing_back.execute(
            WorthBringingBackQuery(
                family_id=identity.family_id,
                actor_id=identity.member_id,
                child_id=ChildId(child_id) if child_id else None,
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        now = box.clock.now()
        # The recording rides along with the suggestion. This is the screen where it matters
        # most: "you said this, in your own voice, eight months ago" is the entire argument
        # the Return Engine is making, and a transcript of it is a weaker argument.
        return JSONResponse(
            content=[
                render_suggestion(
                    s,
                    now=now,
                    voice=_voice_behind(box, s.spark.why.voice_media_id if s.spark.why else None),
                )
                for s in result.unwrap()
            ]
        )

    @app.post("/v1/return/{spark_id}/respond")
    def respond_to_suggestion(
        spark_id: str,
        body: SuggestionResponseRequest,
        identity: DeviceIdentity = me,
        box: Container = box_dep,
    ) -> Response:
        owned = _spark_in_family(box, identity, spark_id)
        if owned.is_err():
            return error_response(owned.unwrap_err())
        result = box.respond_to_suggestion.execute(
            RespondToSuggestionCommand(
                spark_id=SparkId(spark_id), response=SuggestionResponse(body.response)
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(content=render_spark(result.unwrap(), now=box.clock.now()))

    # ---------------------------------------------------------------- presence
    @app.post("/v1/little-things", status_code=201)
    def capture_little_thing(
        body: CaptureLittleThingRequest,
        identity: DeviceIdentity = me,
        idempotency_key: str | None = _IDEMPOTENCY_KEY,
        box: Container = box_dep,
    ) -> Response:
        same_family(identity, body.family_id)
        same_member(identity, body.author_id)

        def perform() -> Response:
            result = box.capture_little_thing.execute(
                CaptureLittleThingCommand(
                    family_id=identity.family_id,
                    author_id=identity.member_id,
                    subject_child_id=(
                        ChildId(body.subject_child_id) if body.subject_child_id else None
                    ),
                    text=body.text,
                    audio_media_id=body.audio_media_id,
                )
            )
            if result.is_err():
                return error_response(result.unwrap_err())
            thing = result.unwrap()
            return JSONResponse(
                status_code=201,
                content=render_little_thing(thing, voice=_voice_behind(box, thing.audio_media_id)),
            )

        return idempotency.replay_or_perform(
            store=box.idempotency,
            clock=box.clock,
            key=idempotency_key,
            family_id=identity.family_id,
            endpoint="POST /v1/little-things",
            payload=body.model_dump(mode="json"),
            perform=perform,
        )

    @app.get("/v1/right-now")
    def todays_prompt(
        identity: DeviceIdentity = me,  # noqa: ARG001 - required for the token check itself
        box: Container = box_dep,
    ) -> Response:
        """Today's prompt is the same for everyone, and still needs a token.

        The identity is unused on purpose: the prompt reveals nothing about a family, but an
        endpoint that answers without a token is an endpoint someone can use to find out that
        this server exists and is running Anuvritti.
        """
        return JSONResponse(content={"prompt": RightNowSnapshot.prompt_for(box.clock.today())})

    @app.post("/v1/right-now", status_code=201)
    def capture_right_now(
        body: CaptureRightNowRequest,
        identity: DeviceIdentity = me,
        idempotency_key: str | None = _IDEMPOTENCY_KEY,
        box: Container = box_dep,
    ) -> Response:
        same_family(identity, body.family_id)

        def perform() -> Response:
            result = box.capture_right_now.execute(
                CaptureRightNowCommand(
                    family_id=identity.family_id,
                    child_id=ChildId(body.child_id),
                    prompt=body.prompt,
                    answer=body.answer,
                )
            )
            if result.is_err():
                return error_response(result.unwrap_err())
            return JSONResponse(status_code=201, content=render_right_now(result.unwrap()))

        return idempotency.replay_or_perform(
            store=box.idempotency,
            clock=box.clock,
            key=idempotency_key,
            family_id=identity.family_id,
            endpoint="POST /v1/right-now",
            payload=body.model_dump(mode="json"),
            perform=perform,
        )

    # ------------------------------------------------------------------- voice
    @app.post("/v1/voice", status_code=201)
    def keep_voice_note(
        body: KeepVoiceNoteRequest,
        identity: DeviceIdentity = me,
        idempotency_key: str | None = _IDEMPOTENCY_KEY,
        box: Container = box_dep,
    ) -> Response:
        """Keep a recording (PRD 12, 17, 24).

        Two requests, not one: the bytes go to `POST /v1/media` and this says what they
        are. That looks like a wasted round trip against the ten-second budget in PRD 11,
        and it is the opposite - the upload is the slow part, so it starts the moment the
        button is released, while the parent is still deciding whether to say anything
        about it. A single multipart call would have to wait for both.
        """
        same_family(identity, body.family_id)
        same_member(identity, body.author_id)

        def perform() -> Response:
            result = box.keep_voice_note.execute(
                KeepVoiceNoteCommand(
                    family_id=identity.family_id,
                    author_id=identity.member_id,
                    media_id=MediaId(body.media_id),
                    duration_seconds=body.duration_seconds,
                    heard_text=body.heard_text,
                    heard_confidence=body.heard_confidence,
                )
            )
            if result.is_err():
                return error_response(result.unwrap_err())
            note = result.unwrap()
            if abs(note.duration_seconds - body.duration_seconds) > 0.25:
                log.info(
                    "handset duration differed from measured audio",
                    extra={
                        "media_id": str(note.media_id),
                        "claimed_duration_seconds": body.duration_seconds,
                        "measured_duration_seconds": note.duration_seconds,
                    },
                )
            return JSONResponse(status_code=201, content=render_voice(note))

        return idempotency.replay_or_perform(
            store=box.idempotency,
            clock=box.clock,
            key=idempotency_key,
            family_id=identity.family_id,
            endpoint="POST /v1/voice",
            payload=body.model_dump(mode="json"),
            perform=perform,
        )

    @app.get("/v1/voice")
    def list_voice_notes(identity: DeviceIdentity = me, box: Container = box_dep) -> Response:
        """The Papa Voice Vault (PRD 21). Newest first, and no count of them.

        There is no `total`, no `unheard` and no cursor. This is a shelf, and a shelf does
        not tell you how far behind you are.
        """
        result = box.list_voice_notes.execute(ListVoiceNotesQuery(identity.family_id))
        if result.is_err():  # pragma: no cover - a list query over one's own family
            return error_response(result.unwrap_err())
        return JSONResponse(content={"recordings": [render_voice(n) for n in result.unwrap()]})

    @app.get("/v1/voice/{media_id}")
    def get_voice_note(
        media_id: str, identity: DeviceIdentity = me, box: Container = box_dep
    ) -> Response:
        result = box.get_voice_note.execute(
            GetVoiceNoteQuery(family_id=identity.family_id, media_id=MediaId(media_id))
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(content=render_voice(result.unwrap()))

    @app.post("/v1/voice/{media_id}/transcript")
    def correct_transcript(
        media_id: str,
        body: CorrectTranscriptRequest,
        identity: DeviceIdentity = me,
        box: Container = box_dep,
    ) -> Response:
        """A parent fixes what the machine misheard. The audio is not touched (PRD 24)."""
        result = box.correct_transcript.execute(
            CorrectTranscriptCommand(
                family_id=identity.family_id, media_id=MediaId(media_id), text=body.text
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(content=render_voice(result.unwrap()))

    # -------------------------------------------------------------------- film
    @app.post("/v1/film/compile")
    def compile_film(identity: DeviceIdentity = me, box: Container = box_dep) -> Response:
        """The evidence shelf behind this year's film, in the order it was captured.

        Rendering remains an offline adapter: the family server deliberately does not grow
        Chromium. This boundary is nevertheless the one place the phone asks for the film,
        and `rendered_media_id` is where an archived render appears when one exists.
        """
        found_family = box.families.get(identity.family_id)
        if found_family.is_err():
            return error_response(found_family.unwrap_err())
        family = found_family.unwrap()
        if not family.children:
            return error_response(DomainError(ErrorCode.CHILD_NOT_FOUND, "no child in this family"))
        child = family.children[0]
        year = box.clock.today().year

        found_sparks = box.sparks.list_for_family(identity.family_id)
        if found_sparks.is_err():  # pragma: no cover - SQLite list has no domain failure
            return error_response(found_sparks.unwrap_err())
        found_notes = box.voice_notes.list_for_family(identity.family_id)
        if found_notes.is_err():  # pragma: no cover - SQLite list has no domain failure
            return error_response(found_notes.unwrap_err())

        materials: list[tuple[Any, dict[str, Any]]] = []
        for note in found_notes.unwrap():
            if note.recorded_at.year == year:
                materials.append(
                    (
                        note.recorded_at,
                        {
                            "kind": "RECORDING",
                            "captured_at": note.recorded_at.isoformat(),
                            "recording": render_voice(note),
                            "spark": None,
                        },
                    )
                )
        for spark in found_sparks.unwrap():
            belongs_to_child = spark.subject_child_id in (None, child.id)
            if spark.why is not None and belongs_to_child and spark.created_at.year == year:
                materials.append(
                    (
                        spark.created_at,
                        {
                            "kind": "SPARK",
                            "captured_at": spark.created_at.isoformat(),
                            "recording": None,
                            "spark": render_spark(
                                spark,
                                now=box.clock.now(),
                                voice=_voice_behind(box, spark.why.voice_media_id),
                            ),
                        },
                    )
                )
        materials.sort(key=lambda item: item[0])
        return JSONResponse(
            content={
                "child_name": child.display_name,
                "year": year,
                "materials": [material for _, material in materials],
                "rendered_media_id": None,
            }
        )

    # ------------------------------------------------------------------- media
    @app.post("/v1/media", status_code=201)
    async def upload_media(
        family_id: str | None = _FORM_FAMILY_ID,
        file: UploadFile = _UPLOAD_FILE,
        identity: DeviceIdentity = me,
        box: Container = box_dep,
    ) -> Response:
        same_family(identity, family_id)
        content = await file.read()
        result = box.media.put(
            identity.family_id,
            content=content,
            mime_type=file.content_type or "application/octet-stream",
            at=box.clock.now(),
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(status_code=201, content=result.unwrap().to_dict())

    @app.get("/v1/media/{media_id}")
    def download_media(
        media_id: str, identity: DeviceIdentity = me, box: Container = box_dep
    ) -> Response:
        described = box.media.describe(MediaId(media_id))
        if described.is_err():
            return error_response(described.unwrap_err())
        if described.unwrap().family_id != identity.family_id:
            # The same answer a nonexistent id gets. A different one would confirm that
            # some other family's photograph exists at this address.
            return error_response(DomainError(ErrorCode.MEDIA_NOT_FOUND, "no such media"))
        content = box.media.get(MediaId(media_id))
        if content.is_err():  # pragma: no cover - describe already proved it is there
            return error_response(content.unwrap_err())
        return Response(
            content=content.unwrap(),
            media_type=described.unwrap().mime_type,
            headers={"Cache-Control": "private, no-store"},
        )

    # ---------------------------------------------------------- family rights
    @app.get("/v1/families/{family_id}/export")
    def export_family(
        family_id: str, identity: DeviceIdentity = me, box: Container = box_dep
    ) -> Response:
        same_family(identity, family_id)
        result = box.export_family.execute(ExportFamilyDataQuery(identity.family_id))
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(
            content=result.unwrap(),
            headers={"Content-Disposition": 'attachment; filename="anuvritti-export.json"'},
        )

    @app.delete("/v1/families/{family_id}")
    def delete_family(
        family_id: str, identity: DeviceIdentity = me, box: Container = box_dep
    ) -> Response:
        same_family(identity, family_id)
        result = box.delete_family.execute(DeleteFamilyDataCommand(identity.family_id))
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(content=result.unwrap())

    return app


def _voice_behind(box: Container, media_id: str | None) -> VoiceNote | None:
    """The recording behind a why or a little thing, when there is one.

    A missing note is not an error and not a 404: the audio is the artifact and it is
    perfectly reachable at `/v1/media/{id}` without a `voice_note` row - a family archive
    restored from a V0 backup has recordings and no notes at all. The screen falls back to
    a player with no waveform and no transcript, which is a worse screen and still a true
    one, and that is exactly the right failure for this to have.
    """
    if not media_id:
        return None
    found = box.voice_notes.get(MediaId(media_id))
    return found.unwrap() if found.is_ok() else None


def _spark_in_family(box: Container, identity: DeviceIdentity, spark_id: str) -> Result[Any, Any]:
    """Fetch a Spark, but only if it belongs to the token's family.

    Every `/v1/sparks/{id}` route goes through here rather than trusting the id, because a
    Spark id is guessable in exactly the way a family id was: it appears in a URL, and a URL
    gets shared. A stranger's id and a nonexistent id produce the same `SPARK_NOT_FOUND`, so
    the response never confirms that a Spark exists somewhere else.
    """
    found = box.sparks.get(SparkId(spark_id))
    if found.is_err():
        return found
    if found.unwrap().family_id != identity.family_id:
        return Err(DomainError(ErrorCode.SPARK_NOT_FOUND, "no such spark"))
    return found


__all__ = ["create_app"]

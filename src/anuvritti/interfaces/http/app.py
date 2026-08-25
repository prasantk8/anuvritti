"""The HTTP interface.

Thin by design: parse, delegate to a use case, render. No business rule lives here, so no
business rule can be bypassed by calling a different endpoint. Implements
docs/contracts/openapi.yaml.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

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
from anuvritti.interfaces.http.container import Container, build_container
from anuvritti.interfaces.http.errors import error_response
from anuvritti.interfaces.http.observability import install_observability
from anuvritti.interfaces.http.schemas import (
    CaptureLittleThingRequest,
    CaptureRightNowRequest,
    CaptureSparkRequest,
    CreateChildRequest,
    CreateFamilyRequest,
    MarkAsDoneRequest,
    OverrideFieldRequest,
    RecordWhyRequest,
    SourceRequest,
    SuggestionResponseRequest,
    parse_intent,
    render_family,
    render_little_thing,
    render_moment,
    render_right_now,
    render_spark,
    render_suggestion,
)
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    MediaId,
    MemberId,
    SparkId,
)
from anuvritti.shared.result import Err, Ok, Result

log = get_logger("http")

# FastAPI marker objects, hoisted so they are not re-created per call (ruff B008).
_UPLOAD_FILE = File(...)
_FORM_FAMILY_ID = Form(...)


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
        version="0.1.0",
        description="For the little things you don't want life to erase.",
        docs_url="/docs" if settings.expose_api_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
    )
    app.state.container = box
    app.state.settings = settings
    install_observability(app, box)

    def get_box(request: Request) -> Container:
        container_from_state: Container = request.app.state.container
        return container_from_state

    box_dep = Depends(get_box)

    # ---------------------------------------------------------------- families
    @app.post("/v1/families", status_code=201)
    def create_family(body: CreateFamilyRequest, box: Container = box_dep) -> Response:
        now = box.clock.now()
        family = Family(
            id=FamilyId(box.ids.new_id()),
            name=body.name,
            members=(
                Member(MemberId(box.ids.new_id()), body.owner_display_name, MemberRole.PARENT),
            ),
            children=(),
            created_at=now,
        )
        with box.uow:
            box.families.save(family)
            box.uow.commit()
        return JSONResponse(status_code=201, content=render_family(family, box.clock.today()))

    @app.get("/v1/families/{family_id}")
    def get_family(family_id: str, box: Container = box_dep) -> Response:
        found = box.families.get(FamilyId(family_id))
        if found.is_err():
            return error_response(found.unwrap_err())
        return JSONResponse(content=render_family(found.unwrap(), box.clock.today()))

    @app.post("/v1/families/{family_id}/children", status_code=201)
    def add_child(family_id: str, body: CreateChildRequest, box: Container = box_dep) -> Response:
        found = box.families.get(FamilyId(family_id))
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
    def capture_spark(body: CaptureSparkRequest, box: Container = box_dep) -> Response:
        source = _build_source(body.source)
        if source.is_err():
            return error_response(source.unwrap_err())

        result = box.capture_spark.execute(
            CaptureSparkCommand(
                family_id=FamilyId(body.family_id),
                owner_id=MemberId(body.owner_id),
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
        return JSONResponse(status_code=201, content=render_spark(result.unwrap()))

    @app.get("/v1/sparks")
    def search_sparks(
        family_id: str,
        actor_id: str,
        q: str | None = None,
        intent: str | None = None,
        child_id: str | None = None,
        age: int | None = None,
        status: str | None = None,
        limit: int = Query(default=25, ge=1, le=100),
        box: Container = box_dep,
    ) -> Response:
        parsed_intent = parse_intent(intent) if intent else None
        if intent and parsed_intent is None:
            return _invalid(f"{intent!r} is not one of the six V0 intents")
        try:
            parsed_status = SparkStatus(status.upper()) if status else None
        except ValueError:
            return _invalid(f"{status!r} is not a spark status")

        result = box.search_vault.execute(
            SearchVaultQuery(
                family_id=FamilyId(family_id),
                actor_id=MemberId(actor_id),
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
        return JSONResponse(content=[render_spark(s) for s in result.unwrap()])

    @app.get("/v1/sparks/{spark_id}")
    def get_spark(spark_id: str, box: Container = box_dep) -> Response:
        found = box.sparks.get(SparkId(spark_id))
        if found.is_err():
            return error_response(found.unwrap_err())
        return JSONResponse(content=render_spark(found.unwrap()))

    @app.post("/v1/sparks/{spark_id}/why")
    def record_why(spark_id: str, body: RecordWhyRequest, box: Container = box_dep) -> Response:
        result = box.record_why.execute(
            RecordWhyCommand(
                spark_id=SparkId(spark_id), text=body.text, voice_media_id=body.voice_media_id
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(content=render_spark(result.unwrap()))

    @app.post("/v1/sparks/{spark_id}/override")
    def override_field(
        spark_id: str, body: OverrideFieldRequest, box: Container = box_dep
    ) -> Response:
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
        return JSONResponse(content=render_spark(result.unwrap()))

    @app.post("/v1/sparks/{spark_id}/done", status_code=201)
    def mark_as_done(spark_id: str, body: MarkAsDoneRequest, box: Container = box_dep) -> Response:
        result = box.mark_as_done.execute(
            MarkAsDoneCommand(
                spark_id=SparkId(spark_id),
                created_by=MemberId(body.created_by),
                happened_on=body.happened_on,
                reflection=body.reflection,
                photo_media_id=body.photo_media_id,
                audio_media_id=body.audio_media_id,
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(status_code=201, content=render_moment(result.unwrap()))

    # ------------------------------------------------------------------ return
    @app.get("/v1/return/worth-bringing-back")
    def worth_bringing_back(
        family_id: str, actor_id: str, child_id: str | None = None, box: Container = box_dep
    ) -> Response:
        result = box.worth_bringing_back.execute(
            WorthBringingBackQuery(
                family_id=FamilyId(family_id),
                actor_id=MemberId(actor_id),
                child_id=ChildId(child_id) if child_id else None,
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(content=[render_suggestion(s) for s in result.unwrap()])

    @app.post("/v1/return/{spark_id}/respond")
    def respond_to_suggestion(
        spark_id: str, body: SuggestionResponseRequest, box: Container = box_dep
    ) -> Response:
        result = box.respond_to_suggestion.execute(
            RespondToSuggestionCommand(
                spark_id=SparkId(spark_id), response=SuggestionResponse(body.response)
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(content=render_spark(result.unwrap()))

    # ---------------------------------------------------------------- presence
    @app.post("/v1/little-things", status_code=201)
    def capture_little_thing(body: CaptureLittleThingRequest, box: Container = box_dep) -> Response:
        result = box.capture_little_thing.execute(
            CaptureLittleThingCommand(
                family_id=FamilyId(body.family_id),
                author_id=MemberId(body.author_id),
                subject_child_id=(
                    ChildId(body.subject_child_id) if body.subject_child_id else None
                ),
                text=body.text,
                audio_media_id=body.audio_media_id,
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(status_code=201, content=render_little_thing(result.unwrap()))

    @app.get("/v1/right-now")
    def todays_prompt(box: Container = box_dep) -> Response:
        return JSONResponse(content={"prompt": RightNowSnapshot.prompt_for(box.clock.today())})

    @app.post("/v1/right-now", status_code=201)
    def capture_right_now(body: CaptureRightNowRequest, box: Container = box_dep) -> Response:
        result = box.capture_right_now.execute(
            CaptureRightNowCommand(
                family_id=FamilyId(body.family_id),
                child_id=ChildId(body.child_id),
                prompt=body.prompt,
                answer=body.answer,
            )
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(status_code=201, content=render_right_now(result.unwrap()))

    # ------------------------------------------------------------------- media
    @app.post("/v1/media", status_code=201)
    async def upload_media(
        family_id: str = _FORM_FAMILY_ID,
        file: UploadFile = _UPLOAD_FILE,
        box: Container = box_dep,
    ) -> Response:
        content = await file.read()
        result = box.media.put(
            FamilyId(family_id),
            content=content,
            mime_type=file.content_type or "application/octet-stream",
            at=box.clock.now(),
        )
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(status_code=201, content=result.unwrap().to_dict())

    @app.get("/v1/media/{media_id}")
    def download_media(media_id: str, box: Container = box_dep) -> Response:
        described = box.media.describe(MediaId(media_id))
        if described.is_err():
            return error_response(described.unwrap_err())
        content = box.media.get(MediaId(media_id))
        if content.is_err():
            return error_response(content.unwrap_err())
        return Response(
            content=content.unwrap(),
            media_type=described.unwrap().mime_type,
            headers={"Cache-Control": "private, no-store"},
        )

    # ---------------------------------------------------------- family rights
    @app.get("/v1/families/{family_id}/export")
    def export_family(family_id: str, box: Container = box_dep) -> Response:
        result = box.export_family.execute(ExportFamilyDataQuery(FamilyId(family_id)))
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(
            content=result.unwrap(),
            headers={"Content-Disposition": 'attachment; filename="anuvritti-export.json"'},
        )

    @app.delete("/v1/families/{family_id}")
    def delete_family(family_id: str, box: Container = box_dep) -> Response:
        result = box.delete_family.execute(DeleteFamilyDataCommand(FamilyId(family_id)))
        if result.is_err():
            return error_response(result.unwrap_err())
        return JSONResponse(content=result.unwrap())

    return app


__all__ = ["create_app"]

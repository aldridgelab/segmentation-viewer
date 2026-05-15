"""FastAPI backend for the segmentation checker desktop app."""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import UTC, datetime
from functools import lru_cache
from io import BytesIO, StringIO
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw

from segmentation_checker import __version__
from segmentation_checker.backend.data_io import (
    coerce_float,
    create_demo_dataset,
    inspect_dataset,
    load_dataset,
    metric_lookup,
)
from segmentation_checker.backend.models import (
    AnnotationRequest,
    BulkAnnotationRequest,
    BulkAnnotationResponse,
    CellItem,
    CellsResponse,
    DatasetConfigRequest,
    DatasetConfigResponse,
    DatasetSummary,
    DemoDatasetResponse,
    InspectDatasetRequest,
    InspectDatasetResponse,
    ReviewAnnotation,
)
from segmentation_checker.backend.state import CellRecord, CheckerState

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(
    os.environ.get("SEGMENTATION_CHECKER_CONFIG_PATH", PROJECT_ROOT / "checker_config.json")
).expanduser()
FRONTEND_DIST_ENV = "SEGMENTATION_CHECKER_FRONTEND_DIST"
DEFAULT_LIMIT = 120
MAX_LIMIT = 1000

checker_state = CheckerState(CONFIG_PATH)
checker_state.load()
_frontend_dist_dir: Optional[Path] = None
_frontend_fallback_registered = False

app = FastAPI(
    title="Segmentation Checker API",
    description="Review and correction API for single-cell segmentation crops.",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:5176",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def resolve_frontend_dist(frontend_dist: Optional[Path] = None) -> Path:
    """Find the production frontend build for desktop/static serving."""
    candidates: list[Path] = []
    if frontend_dist:
        candidates.append(frontend_dist)
    if os.environ.get(FRONTEND_DIST_ENV):
        candidates.append(Path(os.environ[FRONTEND_DIST_ENV]))
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "frontend" / "dist")  # type: ignore[attr-defined]
    candidates.append(PROJECT_ROOT / "frontend" / "dist")

    searched: list[str] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        searched.append(str(resolved))
        if (resolved / "index.html").exists():
            return resolved

    raise RuntimeError(
        "Frontend build not found. Run `npm run build` in frontend/ or set "
        f"{FRONTEND_DIST_ENV}. Searched: {', '.join(searched)}"
    )


def mount_frontend_dist(frontend_dist: Optional[Path] = None) -> Path:
    """Serve the built React app from the same FastAPI process."""
    global _frontend_dist_dir, _frontend_fallback_registered

    _frontend_dist_dir = resolve_frontend_dist(frontend_dist)
    assets_dir = _frontend_dist_dir / "assets"
    has_assets_mount = any(getattr(route, "name", None) == "frontend-assets" for route in app.routes)
    if assets_dir.exists() and not has_assets_mount:
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    if not _frontend_fallback_registered:

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            if _frontend_dist_dir is None:
                raise HTTPException(status_code=404, detail="Frontend not mounted")

            if full_path:
                requested = (_frontend_dist_dir / full_path).resolve()
                try:
                    requested.relative_to(_frontend_dist_dir)
                except ValueError as exc:
                    raise HTTPException(status_code=404, detail="Not found") from exc
                if requested.is_file():
                    return FileResponse(requested)

            return FileResponse(_frontend_dist_dir / "index.html")

        _frontend_fallback_registered = True

    return _frontend_dist_dir


def _load_current_dataset() -> None:
    if checker_state.config is None:
        checker_state.records = []
        return
    checker_state.records = load_dataset(checker_state.config)


def _annotation_for(record_id: str) -> ReviewAnnotation:
    return checker_state.annotations.get(record_id, ReviewAnnotation())


def _summary() -> DatasetSummary:
    annotations = [_annotation_for(record.id) for record in checker_state.records]
    reviewed_cells = sum(1 for annotation in annotations if annotation.status != "unreviewed")
    return DatasetSummary(
        total_cells=len(checker_state.records),
        reviewed_cells=reviewed_cells,
        accepted_cells=sum(1 for annotation in annotations if annotation.status == "accepted"),
        training_candidates=sum(
            1
            for annotation in annotations
            if annotation.status == "training_candidate" or annotation.training_bin != "none"
        ),
        low_eccentricity_cells=sum(
            1 for record in checker_state.records if "possible_v_snap" in record.flags
        ),
        loaded_output_dir=(
            checker_state.config.output_dir if checker_state.config is not None else None
        ),
        loaded_measurements_path=(
            checker_state.config.measurements_path if checker_state.config is not None else None
        ),
        remaining_cells=max(len(checker_state.records) - reviewed_cells, 0),
        review_state_path=str(checker_state.review_state_path()) if checker_state.config else None,
    )


def _mask_channel_for_record(record: CellRecord) -> int | None:
    if record.mask_channel_index is not None:
        return record.mask_channel_index
    configured_index = checker_state.config.mask_channel_index if checker_state.config else 1
    if configured_index < 0 or record.channel_count <= configured_index:
        return None
    return configured_index


def _record_to_item(record: CellRecord) -> CellItem:
    annotation = _annotation_for(record.id)
    quoted_id = quote(record.id, safe="")
    mask_channel_index = None if record.mask_path else _mask_channel_for_record(record)
    mask_url = None
    if record.mask_path or (record.crop_path and mask_channel_index is not None):
        mask_url = f"/api/cells/{quoted_id}/image?kind=mask"
    return CellItem(
        id=record.id,
        row_index=record.row_index,
        crop_url=f"/api/cells/{quoted_id}/image?kind=crop",
        mask_url=mask_url,
        source_path=str(record.crop_path) if record.crop_path else None,
        mask_path=str(record.mask_path) if record.mask_path else None,
        mask_channel_index=mask_channel_index,
        mask_channel_name=(
            record.channel_names[mask_channel_index]
            if mask_channel_index is not None and mask_channel_index < len(record.channel_names)
            else None
        ),
        channel_count=record.channel_count,
        channel_names=record.channel_names,
        channel_metadata=record.channel_metadata,
        image_metadata=record.image_metadata,
        status=annotation.status,
        training_bin=annotation.training_bin,
        note=annotation.note,
        flags=record.flags,
        metrics=record.metrics,
    )


def _record_by_id(cell_id: str) -> CellRecord:
    for record in checker_state.records:
        if record.id == cell_id:
            return record
    raise HTTPException(status_code=404, detail=f"Cell not found: {cell_id}")


def _metric_value(record: CellRecord, metric_name: str) -> float | str | None:
    if metric_name in record.metrics:
        return record.metrics[metric_name]
    lowered = metric_name.lower()
    for key, value in record.metrics.items():
        if key.lower() == lowered:
            return value
    return metric_lookup(record.row, [metric_name])


def _eccentricity(record: CellRecord) -> float | None:
    value = metric_lookup(record.row, ["eccentricity", "Eccentricity", "ecc"])
    return value


def _filtered_records(
    search: str | None,
    status: str,
    training_bin: str,
    flag: str | None,
    eccentricity_max: float | None,
    numeric_filter_field: str | None = None,
    numeric_filter_op: str = "lte",
    numeric_filter_value: float | None = None,
) -> list[CellRecord]:
    records = checker_state.records
    if search:
        lowered = search.lower()
        records = [
            record
            for record in records
            if lowered in record.id.lower()
            or any(lowered in str(value).lower() for value in record.row.values())
        ]
    if status != "all":
        records = [record for record in records if _annotation_for(record.id).status == status]
    if training_bin != "all":
        records = [
            record for record in records if _annotation_for(record.id).training_bin == training_bin
        ]
    if flag:
        records = [record for record in records if flag in record.flags]
    if eccentricity_max is not None:
        records = [
            record
            for record in records
            if (value := _eccentricity(record)) is not None and value <= eccentricity_max
        ]
    if numeric_filter_field and numeric_filter_value is not None:
        records = [
            record
            for record in records
            if (value := _metric_value(record, numeric_filter_field)) is not None
            and isinstance(value, (float, int))
            and (
                value >= numeric_filter_value
                if numeric_filter_op == "gte"
                else value <= numeric_filter_value
            )
        ]
    return records


def _sort_records(records: list[CellRecord], sort_by: str, direction: str) -> list[CellRecord]:
    reverse = direction == "desc"

    def key(record: CellRecord) -> tuple[int, float | str]:
        if sort_by == "review_priority":
            score = 0
            if "possible_v_snap" in record.flags:
                score += 100
            if "low_confidence" in record.flags:
                score += 20
            if _annotation_for(record.id).status == "unreviewed":
                score += 10
            return (0, -score)
        if sort_by == "id":
            return (0, record.id.lower())
        value = _metric_value(record, sort_by)
        if isinstance(value, (float, int)):
            return (0, float(value))
        if value is None:
            return (1, "")
        return (0, str(value).lower())

    return sorted(records, key=key, reverse=reverse)


IMAGE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _image_response(path: Path | None, label: str, kind: str, frame: int = 0) -> Response:
    if path is None or not path.exists():
        return _placeholder_image(label, f"missing {kind}")
    try:
        mtime_ns = path.stat().st_mtime_ns
        content = _render_image_bytes(str(path), mtime_ns, frame)
    except Exception as exc:
        print(f"Could not render {kind} for {label}: {exc}", file=sys.stderr)
        return _placeholder_image(label, f"cannot render {kind}")
    return Response(content=content, media_type="image/png", headers=IMAGE_HEADERS)


@lru_cache(maxsize=512)
def _render_image_bytes(path: str, mtime_ns: int, frame: int) -> bytes:
    del mtime_ns
    with Image.open(path) as image:
        frame_index = min(max(frame, 0), max(int(getattr(image, "n_frames", 1)) - 1, 0))
        image.seek(frame_index)
        rendered = _renderable_image(image)
        buffer = BytesIO()
        rendered.save(buffer, format="PNG")
        return buffer.getvalue()


def _renderable_image(image: Image.Image) -> Image.Image:
    image.load()
    if image.mode in {"RGB", "RGBA"}:
        return image.convert("RGB")
    if image.mode == "L":
        return image.convert("RGB")
    gray = image.convert("I")
    low, high = gray.getextrema()
    if high <= low:
        return Image.new("RGB", gray.size, (0, 0, 0))
    scale = 255.0 / float(high - low)
    raw_pixels = (
        gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata()
    )
    pixels = [
        max(0, min(255, int((int(value) - low) * scale)))
        for value in raw_pixels
    ]
    eight_bit = Image.new("L", gray.size)
    eight_bit.putdata(pixels)
    return eight_bit.convert("L").convert("RGB")


def _placeholder_image(label: str, message: str) -> Response:
    image = Image.new("RGB", (220, 180), (12, 16, 20))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((16, 16, 204, 164), radius=10, outline=(58, 70, 82), width=2)
    draw.text((28, 70), label[:24], fill=(246, 248, 250))
    draw.text((28, 96), message, fill=(170, 180, 191))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png", headers=IMAGE_HEADERS)


try:
    _load_current_dataset()
except Exception:
    checker_state.records = []


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/config", response_model=DatasetConfigResponse)
async def get_config() -> DatasetConfigResponse:
    return checker_state.config_response()


@app.get("/api/summary", response_model=DatasetSummary)
async def get_summary() -> DatasetSummary:
    return _summary()


@app.post("/api/inspect", response_model=InspectDatasetResponse)
async def inspect_dataset_endpoint(request: InspectDatasetRequest) -> InspectDatasetResponse:
    try:
        return inspect_dataset(request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not inspect dataset: {exc}") from exc


@app.post("/api/config", response_model=DatasetConfigResponse)
async def set_config(request: DatasetConfigRequest) -> DatasetConfigResponse:
    try:
        records = load_dataset(request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not load dataset: {exc}") from exc
    checker_state.config = request
    checker_state.records = records
    checker_state.load_annotations()
    checker_state.save_config()
    return checker_state.config_response()


@app.post("/api/demo", response_model=DemoDatasetResponse)
async def load_demo_dataset() -> DemoDatasetResponse:
    config = create_demo_dataset(PROJECT_ROOT)
    checker_state.config = config
    checker_state.records = load_dataset(config)
    checker_state.load_annotations()
    checker_state.save_config()
    return DemoDatasetResponse(config=checker_state.config_response(), summary=_summary())


@app.get("/api/cells", response_model=CellsResponse)
async def list_cells(
    search: Optional[str] = None,
    status: str = "all",
    training_bin: str = "all",
    flag: Optional[str] = None,
    eccentricity_max: Optional[float] = None,
    numeric_filter_field: Optional[str] = None,
    numeric_filter_op: Literal["lte", "gte"] = "lte",
    numeric_filter_value: Optional[float] = None,
    sort_by: str = "review_priority",
    sort_dir: Literal["asc", "desc"] = "asc",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> CellsResponse:
    filtered = _filtered_records(
        search,
        status,
        training_bin,
        flag,
        eccentricity_max,
        numeric_filter_field,
        numeric_filter_op,
        numeric_filter_value,
    )
    sorted_records = _sort_records(filtered, sort_by, sort_dir)
    paged = sorted_records[offset : offset + limit]
    return CellsResponse(
        items=[_record_to_item(record) for record in paged],
        total=len(filtered),
        shown=len(paged),
        low_eccentricity_total=sum(1 for record in filtered if "possible_v_snap" in record.flags),
        reviewed_total=sum(
            1 for record in filtered if _annotation_for(record.id).status != "unreviewed"
        ),
    )


@app.get("/api/cells/{cell_id}", response_model=CellItem)
async def get_cell(cell_id: str) -> CellItem:
    return _record_to_item(_record_by_id(cell_id))


@app.post("/api/cells/{cell_id}/annotation", response_model=CellItem)
async def save_annotation(cell_id: str, request: AnnotationRequest) -> CellItem:
    record = _record_by_id(cell_id)
    checker_state.annotations[cell_id] = ReviewAnnotation(
        status=request.status,
        training_bin=request.training_bin,
        note=request.note.strip(),
        updated_at=datetime.now(UTC).isoformat(),
    )
    checker_state.save_annotations()
    return _record_to_item(record)


@app.post("/api/annotations/bulk", response_model=BulkAnnotationResponse)
async def save_bulk_annotations(request: BulkAnnotationRequest) -> BulkAnnotationResponse:
    records = _filtered_records(
        request.search,
        request.status_filter,
        request.training_bin_filter,
        request.flag,
        request.eccentricity_max,
        request.numeric_filter_field,
        request.numeric_filter_op,
        request.numeric_filter_value,
    )
    updated_at = datetime.now(UTC).isoformat()
    for record in records:
        checker_state.annotations[record.id] = ReviewAnnotation(
            status=request.status,
            training_bin=request.training_bin,
            note=request.note.strip(),
            updated_at=updated_at,
        )
    checker_state.save_annotations()
    return BulkAnnotationResponse(updated_count=len(records))


@app.get("/api/cells/{cell_id}/image")
async def get_cell_image(
    cell_id: str,
    kind: Literal["crop", "mask"] = "crop",
    frame: int = Query(default=0, ge=0),
) -> Response:
    record = _record_by_id(cell_id)
    if kind == "mask":
        if record.mask_path:
            return _image_response(record.mask_path, record.id, kind, frame)
        mask_frame = _mask_channel_for_record(record)
        return _image_response(record.crop_path, record.id, kind, mask_frame or 0)
    return _image_response(record.crop_path, record.id, kind, frame)


@app.get("/api/export/annotations")
async def export_annotations() -> StreamingResponse:
    fieldnames: list[str] = []
    for record in checker_state.records:
        for key in record.row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    export_fields = fieldnames + [
        "review_status",
        "training_bin",
        "review_note",
        "review_updated_at",
        "review_flags",
        "crop_path_resolved",
        "mask_path_resolved",
        "channel_names",
        "mask_channel_index",
        "mask_channel_name",
        "image_metadata_json",
    ]
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=export_fields)
    writer.writeheader()
    for record in checker_state.records:
        annotation = _annotation_for(record.id)
        mask_channel_index = _mask_channel_for_record(record)
        row = dict(record.row)
        row.update(
            {
                "review_status": annotation.status,
                "training_bin": annotation.training_bin,
                "review_note": annotation.note,
                "review_updated_at": annotation.updated_at or "",
                "review_flags": ";".join(record.flags),
                "crop_path_resolved": str(record.crop_path or ""),
                "mask_path_resolved": str(record.mask_path or ""),
                "channel_names": ";".join(record.channel_names),
                "mask_channel_index": str(mask_channel_index)
                if mask_channel_index is not None
                else "",
                "mask_channel_name": (
                    record.channel_names[mask_channel_index]
                    if mask_channel_index is not None
                    and mask_channel_index < len(record.channel_names)
                    else ""
                ),
                "image_metadata_json": json.dumps(record.image_metadata, sort_keys=True),
            }
        )
        writer.writerow(row)

    filename = "segmentation-review-annotations.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers=headers)

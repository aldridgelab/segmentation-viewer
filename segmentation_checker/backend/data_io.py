"""Dataset loading, image matching, and demo data generation."""

from __future__ import annotations

import csv
import json
import math
import random
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw

from segmentation_checker.backend.models import (
    DEFAULT_CROP_PATTERNS,
    DatasetConfigRequest,
    InspectDatasetRequest,
    InspectDatasetResponse,
)
from segmentation_checker.backend.state import CellRecord

ID_COLUMN_CANDIDATES = (
    "cell_id",
    "object_id",
    "label_id",
    "label",
    "id",
    "mask_id",
    "track_id",
    "filename",
)

IMAGE_COLUMN_CANDIDATES = (
    "crop_path",
    "image_path",
    "thumbnail_path",
    "file_path",
    "filename",
    "image",
)

ECCENTRICITY_NAMES = ("eccentricity", "Eccentricity", "ecc")
SOLIDITY_NAMES = ("solidity", "Solidity")
AREA_NAMES = ("area", "Area", "cell_area")
CONFIDENCE_NAMES = ("confidence", "probability", "score", "unet_confidence")
OUTPUT_DATA_SUFFIX = "_data.csv"
OUTPUT_MAPPING_SUFFIX = "_mapping.csv"
OUTPUT_DIAGNOSTICS_SUFFIX = "_diagnostics.csv"
OUTPUT_META_SUFFIX = "_meta.csv"
PASSED_CROPS_DIR_NAME = "passed_crops"
CROPS_MANIFEST_NAME = "crops_manifest.csv"
IMAGEJ_METADATA_BYTE_COUNTS = 50838
IMAGEJ_METADATA = 50839


@dataclass(frozen=True)
class CropTiffMetadata:
    """Lightweight TIFF metadata needed by the review app."""

    frame_count: int = 1
    channel_names: list[str] = field(default_factory=list)
    channel_metadata: list[dict[str, Any]] = field(default_factory=list)
    image_metadata: dict[str, Any] = field(default_factory=dict)
    mask_channel_index: int | None = None


def read_measurements(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read CSV/TSV measurements with dialect sniffing."""
    if not path.exists():
        raise FileNotFoundError(f"Measurements file not found: {path}")
    sample = path.read_text(encoding="utf-8-sig", errors="replace")[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel_tab if path.suffix.lower() in {".tsv", ".tab"} else csv.excel

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, dialect=dialect)
        rows = [{key: value or "" for key, value in row.items()} for row in reader]
        return rows, list(reader.fieldnames or [])


def coerce_float(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (float, int)):
        value_float = float(value)
        return value_float if math.isfinite(value_float) else None
    stripped = str(value).strip()
    if not stripped:
        return None
    try:
        value_float = float(stripped)
    except ValueError:
        return None
    return value_float if math.isfinite(value_float) else None


def find_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    columns_list = list(columns)
    lower_map = {column.lower(): column for column in columns_list}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    for column in columns_list:
        lowered = column.lower()
        if any(candidate.lower() in lowered for candidate in candidates):
            return column
    return None


def numeric_columns(rows: list[dict[str, str]], columns: list[str]) -> list[str]:
    detected: list[str] = []
    sample_rows = rows[:500]
    for column in columns:
        seen_number = False
        seen_text = False
        for row in sample_rows:
            value = row.get(column, "").strip()
            if not value:
                continue
            if coerce_float(value) is None:
                seen_text = True
                break
            seen_number = True
        if seen_number and not seen_text:
            detected.append(column)
    return detected


def list_image_files(directory: Path | None, patterns: list[str] | None = None) -> list[Path]:
    if directory is None or not directory.exists() or not directory.is_dir():
        return []
    resolved_patterns = patterns or list(DEFAULT_CROP_PATTERNS)
    files: list[Path] = []
    for pattern in resolved_patterns:
        files.extend(path for path in directory.glob(pattern) if path.is_file())
    return sorted(set(files))


def infer_output_paths(config: DatasetConfigRequest | InspectDatasetRequest) -> dict[str, Path | None]:
    output_dir = optional_path(config.output_dir)
    if output_dir is not None:
        output_dir = output_dir.resolve()

    def configured_path(value: str | None) -> Path | None:
        if not value:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute() and output_dir is not None:
            path = output_dir / path
        return path.resolve()

    def first_match(suffix: str) -> Path | None:
        if output_dir is None or not output_dir.exists():
            return None
        matches = sorted(output_dir.glob(f"*{suffix}"))
        return matches[0].resolve() if matches else None

    inferred_crops = output_dir / PASSED_CROPS_DIR_NAME if output_dir is not None else None
    crops_dir = configured_path(config.crops_dir) or (
        inferred_crops.resolve() if inferred_crops is not None and inferred_crops.is_dir() else None
    )
    masks_dir = configured_path(config.masks_dir)
    return {
        "output_dir": output_dir,
        "crops_dir": crops_dir,
        "masks_dir": masks_dir,
        "measurements_path": configured_path(config.measurements_path),
        "data_matrix_path": configured_path(config.data_matrix_path) or first_match(OUTPUT_DATA_SUFFIX),
        "mapping_path": configured_path(config.mapping_path) or first_match(OUTPUT_MAPPING_SUFFIX),
        "diagnostics_path": configured_path(config.diagnostics_path)
        or first_match(OUTPUT_DIAGNOSTICS_SUFFIX),
        "meta_path": configured_path(config.meta_path) or first_match(OUTPUT_META_SUFFIX),
        "manifest_path": (output_dir / CROPS_MANIFEST_NAME).resolve()
        if output_dir is not None and (output_dir / CROPS_MANIFEST_NAME).exists()
        else None,
        "summary_path": (output_dir / "extract_summary.json").resolve()
        if output_dir is not None and (output_dir / "extract_summary.json").exists()
        else None,
    }


def read_keyed_csv(path: Path | None, id_column: str = "Cell_ID") -> dict[str, dict[str, str]]:
    if path is None or not path.exists():
        return {}
    rows, columns = read_measurements(path)
    resolved_id_column = find_column(columns, [id_column, "cell_id", "Cell_ID", "id"])
    if resolved_id_column is None:
        return {}
    return {
        row[resolved_id_column].strip(): row
        for row in rows
        if row.get(resolved_id_column, "").strip()
    }


def read_transposed_feature_csv(
    path: Path | None,
    allowed_ids: set[str] | None = None,
) -> tuple[dict[str, dict[str, float | str]], list[str], int]:
    if path is None or not path.exists():
        return {}, [], 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return {}, [], 0
        cell_ids = header[1:]
        selected_positions = [
            (index, cell_id)
            for index, cell_id in enumerate(cell_ids, start=1)
            if allowed_ids is None or cell_id in allowed_ids
        ]
        metrics_by_cell: dict[str, dict[str, float | str]] = {
            cell_id: {} for _, cell_id in selected_positions
        }
        features: list[str] = []
        for row in reader:
            if not row:
                continue
            feature = row[0].strip()
            if not feature:
                continue
            features.append(feature)
            for index, cell_id in selected_positions:
                if index >= len(row):
                    continue
                raw_value = row[index].strip()
                if not raw_value:
                    continue
                numeric_value = coerce_float(raw_value)
                metrics_by_cell[cell_id][feature] = (
                    round(numeric_value, 6) if numeric_value is not None else raw_value
                )
        return metrics_by_cell, features, len(cell_ids)


def read_summary_channels(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    channels_seen = payload.get("channels_seen")
    if isinstance(channels_seen, dict):
        for value in channels_seen.values():
            if isinstance(value, list):
                return [str(channel) for channel in value]
    return []


def decode_imagej_text(raw: bytes) -> str:
    """Decode ImageJ metadata text written by tifffile."""
    for encoding in ("utf-16", "utf-16le", "utf-8"):
        try:
            return raw.decode(encoding).strip("\x00")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip("\x00")


def imagej_metadata_key(raw_key: bytes) -> str:
    known = {"info", "labl", "unit"}
    candidates: list[str] = []
    for key_bytes in (raw_key, raw_key[::-1]):
        try:
            candidates.append(key_bytes.decode("ascii"))
        except UnicodeDecodeError:
            continue
    for candidate in candidates:
        if candidate in known:
            return candidate
    return candidates[0].strip() if candidates else ""


def parse_imagej_metadata_tags(
    byte_counts: Iterable[int] | None,
    raw_metadata: bytes | None,
) -> dict[str, list[str]]:
    """Parse ImageJ IJMetadata tags 50838/50839 without requiring tifffile."""
    if not byte_counts or not raw_metadata:
        return {}
    counts = [int(value) for value in byte_counts]
    if not counts:
        return {}
    header_size = counts[0]
    if header_size < 12 or len(raw_metadata) < header_size:
        return {}

    little_count = struct.unpack("<I", raw_metadata[8:12])[0]
    big_count = struct.unpack(">I", raw_metadata[8:12])[0]
    endian = "<" if little_count < big_count else ">"

    entries: list[tuple[str, int]] = []
    offset = 4
    while offset + 8 <= header_size:
        key = imagej_metadata_key(raw_metadata[offset : offset + 4])
        count = struct.unpack(endian + "I", raw_metadata[offset + 4 : offset + 8])[0]
        entries.append((key, count))
        offset += 8

    parsed: dict[str, list[str]] = {}
    data_offset = header_size
    count_index = 1
    for key, item_count in entries:
        values: list[str] = []
        for _ in range(item_count):
            if count_index >= len(counts):
                break
            size = counts[count_index]
            count_index += 1
            payload = raw_metadata[data_offset : data_offset + size]
            data_offset += size
            if key in {"info", "labl", "unit"}:
                values.append(decode_imagej_text(payload))
        if values:
            parsed[key] = values
    return parsed


def parse_channel_metadata(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return [
            {"label": label.strip(), "kind": "unknown"}
            for label in value.split(";")
            if label.strip()
        ]
    if isinstance(payload, list):
        return [
            dict(item)
            for item in payload
            if isinstance(item, dict)
        ]
    return []


def channel_metadata_labels(channel_metadata: list[dict[str, Any]]) -> list[str]:
    return [
        str(channel.get("label") or f"Frame {index + 1}")
        for index, channel in enumerate(channel_metadata)
    ]


def mask_channel_index_for(
    channel_names: list[str],
    channel_metadata: list[dict[str, Any]],
) -> int | None:
    for index, channel in enumerate(channel_metadata):
        if str(channel.get("kind", "")).lower() == "mask":
            return index
    for index, name in enumerate(channel_names):
        if name.strip().lower() == "mask":
            return index
    return None


def read_crop_tiff_metadata(path: Path | None) -> CropTiffMetadata:
    if path is None or not path.exists():
        return CropTiffMetadata()
    try:
        with Image.open(path) as image:
            image_count = max(int(getattr(image, "n_frames", 1)), 1)
            byte_counts = image.tag_v2.get(IMAGEJ_METADATA_BYTE_COUNTS)
            raw_metadata = image.tag_v2.get(IMAGEJ_METADATA)
            parsed = parse_imagej_metadata_tags(byte_counts, raw_metadata)
    except Exception:
        return CropTiffMetadata()

    image_metadata: dict[str, Any] = {}
    if parsed.get("info"):
        try:
            payload = json.loads(parsed["info"][0])
            if isinstance(payload, dict):
                image_metadata = payload
        except json.JSONDecodeError:
            image_metadata = {"Info": parsed["info"][0]}

    channel_metadata = []
    raw_channels = image_metadata.get("channels")
    if isinstance(raw_channels, list):
        channel_metadata = [
            dict(channel)
            for channel in raw_channels
            if isinstance(channel, dict)
        ]
    labels = parsed.get("labl", []) or channel_metadata_labels(channel_metadata)
    channel_names = channel_names_for_count(labels, image_count)
    mask_channel_index = mask_channel_index_for(channel_names, channel_metadata)
    return CropTiffMetadata(
        frame_count=image_count,
        channel_names=channel_names,
        channel_metadata=channel_metadata,
        image_metadata=image_metadata,
        mask_channel_index=mask_channel_index,
    )


def metadata_from_manifest_row(row: dict[str, str]) -> CropTiffMetadata:
    channel_metadata = parse_channel_metadata(row.get("channel_metadata"))
    labels = channel_metadata_labels(channel_metadata)
    if not labels and row.get("channels"):
        labels = [label.strip() for label in row["channels"].split(";") if label.strip()]
    frame_count_value = coerce_float(row.get("channels_count") or row.get("channel_count"))
    frame_total = int(frame_count_value) if frame_count_value is not None else len(labels) or 1
    channel_names = channel_names_for_count(labels, frame_total)
    image_metadata: dict[str, Any] = {}
    for key, value in row.items():
        if key in {"channel_metadata"}:
            continue
        if key == "bbox" and value:
            try:
                parsed_bbox = json.loads(value)
                image_metadata[key] = parsed_bbox
                continue
            except json.JSONDecodeError:
                pass
        if value:
            image_metadata[key] = value
    if channel_metadata:
        image_metadata["channels"] = channel_metadata
    return CropTiffMetadata(
        frame_count=frame_total,
        channel_names=channel_names,
        channel_metadata=channel_metadata,
        image_metadata=image_metadata,
        mask_channel_index=mask_channel_index_for(channel_names, channel_metadata),
    )


def combine_crop_metadata(
    path: Path | None,
    fallback_names: list[str] | None = None,
    manifest_row: dict[str, str] | None = None,
) -> CropTiffMetadata:
    manifest_metadata = metadata_from_manifest_row(manifest_row or {}) if manifest_row else CropTiffMetadata()
    tiff_metadata = read_crop_tiff_metadata(path)
    frame_total = max(tiff_metadata.frame_count, manifest_metadata.frame_count, 1)
    names = (
        tiff_metadata.channel_names
        or manifest_metadata.channel_names
        or list(fallback_names or [])
    )
    channel_names = channel_names_for_count(names, frame_total)
    channel_metadata = tiff_metadata.channel_metadata or manifest_metadata.channel_metadata
    image_metadata = dict(manifest_metadata.image_metadata)
    image_metadata.update(tiff_metadata.image_metadata)
    mask_channel_index = (
        tiff_metadata.mask_channel_index
        if tiff_metadata.mask_channel_index is not None
        else manifest_metadata.mask_channel_index
    )
    return CropTiffMetadata(
        frame_count=frame_total,
        channel_names=channel_names,
        channel_metadata=channel_metadata,
        image_metadata=image_metadata,
        mask_channel_index=mask_channel_index,
    )


def frame_count(path: Path | None) -> int:
    if path is None or not path.exists():
        return 1
    try:
        with Image.open(path) as image:
            return max(int(getattr(image, "n_frames", 1)), 1)
    except Exception:
        return 1


def channel_names_for_count(names: list[str], count: int) -> list[str]:
    if count <= 0:
        return []
    resolved = list(names[:count])
    while len(resolved) < count:
        resolved.append(f"Frame {len(resolved) + 1}")
    return resolved


def inspect_dataset(request: InspectDatasetRequest) -> InspectDatasetResponse:
    paths = infer_output_paths(request)
    crop_files = list_image_files(paths["crops_dir"], request.crop_patterns)
    mask_files = list_image_files(paths["masks_dir"], request.crop_patterns)
    crop_ids = {path.stem for path in crop_files}
    feature_metrics, feature_names, feature_cell_count = read_transposed_feature_csv(
        paths["data_matrix_path"],
        crop_ids or None,
    )
    mapping_rows = read_keyed_csv(paths["mapping_path"])
    diagnostic_rows = read_keyed_csv(paths["diagnostics_path"])
    meta_rows = read_keyed_csv(paths["meta_path"])
    manifest_rows = read_keyed_csv(paths.get("manifest_path"))
    output_columns = sorted(
        set(feature_names)
        | set(next(iter(manifest_rows.values()), {}).keys())
        | set(next(iter(mapping_rows.values()), {}).keys())
        | set(next(iter(diagnostic_rows.values()), {}).keys())
        | set(next(iter(meta_rows.values()), {}).keys())
    )
    output_numeric = sorted(
        set(feature_names)
        | {
            column
            for rows_by_id in (manifest_rows, mapping_rows, diagnostic_rows, meta_rows)
            for row in rows_by_id.values()
            for column, value in row.items()
            if coerce_float(value) is not None
        }
    )
    if paths["output_dir"] is not None or paths["data_matrix_path"] is not None:
        low_eccentricity_count = sum(
            1
            for metrics in feature_metrics.values()
            if (value := metrics.get("eccentricity")) is not None
            and isinstance(value, (int, float))
            and value <= 0.85
        )
        sample_metadata = combine_crop_metadata(
            crop_files[0] if crop_files else None,
            fallback_names=read_summary_channels(paths["summary_path"]),
            manifest_row=manifest_rows.get(crop_files[0].stem) if crop_files else None,
        )
        channel_names = sample_metadata.channel_names
        return InspectDatasetResponse(
            total_rows=feature_cell_count or len(mapping_rows) or len(crop_files),
            crop_count=len(crop_files),
            mask_count=len(mask_files),
            output_dir=str(paths["output_dir"]) if paths["output_dir"] is not None else None,
            inferred_crops_dir=str(paths["crops_dir"]) if paths["crops_dir"] is not None else None,
            data_matrix_path=str(paths["data_matrix_path"])
            if paths["data_matrix_path"] is not None
            else None,
            mapping_path=str(paths["mapping_path"]) if paths["mapping_path"] is not None else None,
            diagnostics_path=str(paths["diagnostics_path"])
            if paths["diagnostics_path"] is not None
            else None,
            meta_path=str(paths["meta_path"]) if paths["meta_path"] is not None else None,
            summary_path=str(paths["summary_path"]) if paths["summary_path"] is not None else None,
            channel_names=channel_names,
            columns=output_columns,
            numeric_columns=output_numeric,
            suggested_id_column="Cell_ID",
            suggested_image_column="crop_path",
            low_eccentricity_count=low_eccentricity_count,
            sample_ids=[path.stem for path in crop_files[:8]],
        )

    if request.measurements_path is None:
        raise FileNotFoundError("Provide an output directory or measurements file.")
    measurements_path = Path(request.measurements_path).expanduser()
    rows, columns = read_measurements(measurements_path)
    detected_numeric = numeric_columns(rows, columns)
    id_column = find_column(columns, ID_COLUMN_CANDIDATES)
    image_column = find_column(columns, IMAGE_COLUMN_CANDIDATES)
    eccentricity_column = find_column(columns, ECCENTRICITY_NAMES)
    low_eccentricity_count = 0
    if eccentricity_column:
        low_eccentricity_count = sum(
            1
            for row in rows
            if (value := coerce_float(row.get(eccentricity_column))) is not None and value <= 0.85
        )

    sample_ids = [
        cell_id_for_row(row, index, id_column)
        for index, row in enumerate(rows[:8])
    ]
    return InspectDatasetResponse(
        total_rows=len(rows),
        crop_count=len(list_image_files(optional_path(request.crops_dir), request.crop_patterns)),
        mask_count=len(list_image_files(optional_path(request.masks_dir), request.crop_patterns)),
        columns=columns,
        numeric_columns=detected_numeric,
        suggested_id_column=id_column,
        suggested_image_column=image_column,
        low_eccentricity_count=low_eccentricity_count,
        sample_ids=sample_ids,
    )


def optional_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def cell_id_for_row(row: dict[str, str], row_index: int, id_column: str | None) -> str:
    if id_column and row.get(id_column):
        return str(row[id_column]).strip()
    for candidate in ID_COLUMN_CANDIDATES:
        for column, value in row.items():
            if column.lower() == candidate.lower() and value.strip():
                return value.strip()
    return f"cell_{row_index + 1:05d}"


def metrics_for_row(row: dict[str, str], numeric: list[str]) -> dict[str, float | str]:
    metrics: dict[str, float | str] = {}
    for column in numeric:
        value = coerce_float(row.get(column))
        if value is not None:
            metrics[column] = round(value, 6)
    return metrics


def build_image_lookup(files: list[Path]) -> dict[str, Path]:
    lookup: dict[str, Path] = {}
    for path in files:
        stem = path.stem.lower()
        lookup.setdefault(stem, path)
    return lookup


def resolve_path_from_row(
    row: dict[str, str],
    image_column: str | None,
    measurements_dir: Path,
    asset_dir: Path | None,
) -> Path | None:
    if not image_column or not row.get(image_column):
        return None
    raw_path = Path(row[image_column]).expanduser()
    candidates = [raw_path]
    if not raw_path.is_absolute():
        candidates.append(measurements_dir / raw_path)
        if asset_dir:
            candidates.append(asset_dir / raw_path)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def resolve_asset_path(
    cell_id: str,
    lookup: dict[str, Path],
    files: list[Path],
) -> Path | None:
    normalized = cell_id.lower()
    if normalized in lookup:
        return lookup[normalized]
    for path in files:
        stem = path.stem.lower()
        if stem.startswith(normalized) or normalized in stem:
            return path
    return None


def metric_lookup(row: dict[str, str], names: Iterable[str]) -> float | None:
    for name in names:
        for column, value in row.items():
            if column.lower() == name.lower():
                return coerce_float(value)
    return None


def flags_for_row(row: dict[str, str]) -> list[str]:
    flags: list[str] = []
    eccentricity = metric_lookup(row, ECCENTRICITY_NAMES)
    if eccentricity is not None and eccentricity <= 0.85:
        flags.append("possible_v_snap")
    solidity = metric_lookup(row, SOLIDITY_NAMES)
    if solidity is not None and solidity < 0.86:
        flags.append("low_solidity")
    confidence = metric_lookup(row, CONFIDENCE_NAMES)
    if confidence is not None and confidence < 0.72:
        flags.append("low_confidence")
    area = metric_lookup(row, AREA_NAMES)
    if area is not None and area < 40:
        flags.append("tiny_object")
    return flags


def load_dataset(config: DatasetConfigRequest) -> list[CellRecord]:
    paths = infer_output_paths(config)
    if paths["output_dir"] is not None or paths["data_matrix_path"] is not None:
        return load_output_dataset(config, paths)
    if config.measurements_path is None:
        raise FileNotFoundError("Provide an output directory or measurements file.")
    measurements_path = Path(config.measurements_path).expanduser().resolve()
    rows, columns = read_measurements(measurements_path)
    detected_numeric = numeric_columns(rows, columns)
    id_column = config.id_column or find_column(columns, ID_COLUMN_CANDIDATES)
    image_column = config.image_column or find_column(columns, IMAGE_COLUMN_CANDIDATES)
    crops_dir = optional_path(config.crops_dir)
    masks_dir = optional_path(config.masks_dir)
    crop_files = list_image_files(crops_dir, config.crop_patterns)
    mask_files = list_image_files(masks_dir, config.crop_patterns)
    crop_lookup = build_image_lookup(crop_files)
    mask_lookup = build_image_lookup(mask_files)
    measurements_dir = measurements_path.parent

    records: list[CellRecord] = []
    for index, row in enumerate(rows):
        cell_id = cell_id_for_row(row, index, id_column)
        crop_path = resolve_path_from_row(row, image_column, measurements_dir, crops_dir)
        if crop_path is None:
            crop_path = resolve_asset_path(cell_id, crop_lookup, crop_files)
        mask_path = resolve_asset_path(cell_id, mask_lookup, mask_files)
        crop_metadata = combine_crop_metadata(crop_path)
        records.append(
            CellRecord(
                id=cell_id,
                row_index=index,
                row=row,
                metrics=metrics_for_row(row, detected_numeric),
                crop_path=crop_path,
                mask_path=mask_path,
                channel_count=crop_metadata.frame_count,
                channel_names=crop_metadata.channel_names,
                channel_metadata=crop_metadata.channel_metadata,
                image_metadata=crop_metadata.image_metadata,
                mask_channel_index=crop_metadata.mask_channel_index,
                flags=flags_for_row(row),
            )
        )
    return records


def merge_output_row(
    cell_id: str,
    rows_by_source: list[dict[str, dict[str, str]]],
    metrics: dict[str, float | str],
) -> dict[str, str]:
    row: dict[str, str] = {"Cell_ID": cell_id}
    for rows_by_id in rows_by_source:
        row.update(rows_by_id.get(cell_id, {}))
    for key, value in metrics.items():
        row.setdefault(key, str(value))
    return row


def load_output_dataset(
    config: DatasetConfigRequest,
    paths: dict[str, Path | None],
) -> list[CellRecord]:
    crop_files = list_image_files(paths["crops_dir"], config.crop_patterns)
    crop_lookup = build_image_lookup(crop_files)
    crop_ids = {path.stem for path in crop_files}
    metrics_by_cell, _, _ = read_transposed_feature_csv(paths["data_matrix_path"], crop_ids or None)
    mapping_rows = read_keyed_csv(paths["mapping_path"])
    diagnostic_rows = read_keyed_csv(paths["diagnostics_path"])
    meta_rows = read_keyed_csv(paths["meta_path"])
    manifest_rows = read_keyed_csv(paths.get("manifest_path"))
    mask_files = list_image_files(paths["masks_dir"], config.crop_patterns)
    mask_lookup = build_image_lookup(mask_files)
    summary_channel_names = read_summary_channels(paths["summary_path"])

    if crop_files:
        ordered_ids = [path.stem for path in crop_files]
    else:
        ordered_ids = sorted(
            set(metrics_by_cell) | set(mapping_rows) | set(diagnostic_rows) | set(meta_rows)
        )

    records: list[CellRecord] = []
    for index, cell_id in enumerate(ordered_ids):
        crop_path = crop_lookup.get(cell_id.lower())
        metrics = metrics_by_cell.get(cell_id, {})
        row = merge_output_row(
            cell_id,
            [manifest_rows, mapping_rows, diagnostic_rows, meta_rows],
            metrics,
        )
        if crop_path is None:
            crop_path = resolve_path_from_row(row, "crop_path", paths["output_dir"] or Path.cwd(), paths["crops_dir"])
        crop_metadata = combine_crop_metadata(
            crop_path,
            fallback_names=summary_channel_names,
            manifest_row=manifest_rows.get(cell_id),
        )
        records.append(
            CellRecord(
                id=cell_id,
                row_index=index,
                row=row,
                metrics=metrics_for_row(row, list(row.keys())) | metrics,
                crop_path=crop_path,
                mask_path=resolve_asset_path(cell_id, mask_lookup, mask_files),
                channel_count=crop_metadata.frame_count,
                channel_names=crop_metadata.channel_names,
                channel_metadata=crop_metadata.channel_metadata,
                image_metadata=crop_metadata.image_metadata,
                mask_channel_index=crop_metadata.mask_channel_index,
                flags=flags_for_row(row),
            )
        )
    return records


def create_demo_dataset(root: Path) -> DatasetConfigRequest:
    """Create a small synthetic review dataset that exercises the workflow."""
    demo_root = root / "demo_data"
    crops_dir = demo_root / PASSED_CROPS_DIR_NAME
    masks_dir = demo_root / "masks"
    crops_dir.mkdir(parents=True, exist_ok=True)
    masks_dir.mkdir(parents=True, exist_ok=True)
    measurements_path = demo_root / "measurements.csv"

    random.seed(42)
    rows: list[dict[str, str]] = []
    for index in range(48):
        cell_id = f"mabs_{index + 1:03d}"
        is_v_snap = index % 5 == 0 or index in {17, 31}
        eccentricity = random.uniform(0.58, 0.84) if is_v_snap else random.uniform(0.88, 0.98)
        solidity = random.uniform(0.68, 0.84) if is_v_snap else random.uniform(0.88, 0.97)
        area = random.uniform(95, 180) if is_v_snap else random.uniform(55, 110)
        major_axis = random.uniform(34, 56)
        minor_axis = major_axis * random.uniform(0.28, 0.58 if is_v_snap else 0.34)
        confidence = random.uniform(0.56, 0.82) if is_v_snap else random.uniform(0.79, 0.96)
        draw_demo_crop(crops_dir / f"{cell_id}.png", is_v_snap, index)
        draw_demo_mask(masks_dir / f"{cell_id}.png", is_v_snap, index)
        rows.append(
            {
                "cell_id": cell_id,
                "organism": "M. abscessus" if index % 3 else "Mtb-like control",
                "eccentricity": f"{eccentricity:.3f}",
                "solidity": f"{solidity:.3f}",
                "area": f"{area:.1f}",
                "major_axis_length": f"{major_axis:.1f}",
                "minor_axis_length": f"{minor_axis:.1f}",
                "unet_confidence": f"{confidence:.3f}",
                "crop_path": f"crops/{cell_id}.png",
            }
        )

    with measurements_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    data_matrix_path = demo_root / "mabs_demo_data.csv"
    feature_names = [
        "area",
        "eccentricity",
        "solidity",
        "major_axis_length",
        "minor_axis_length",
        "unet_confidence",
    ]
    with data_matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["feature"] + [row["cell_id"] for row in rows])
        for feature in feature_names:
            writer.writerow([feature] + [row[feature] for row in rows])

    mapping_path = demo_root / "mabs_demo_mapping.csv"
    with mapping_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Cell_ID", "crop_path", "organism", "mask_label", "channels"],
        )
        writer.writeheader()
        for index, row in enumerate(rows):
            writer.writerow(
                {
                    "Cell_ID": row["cell_id"],
                    "crop_path": f"passed_crops/{row['cell_id']}.png",
                    "organism": row["organism"],
                    "mask_label": str(index + 1),
                    "channels": "Phase;Cy5;OG514",
                }
            )

    diagnostics_path = demo_root / "mabs_demo_diagnostics.csv"
    with diagnostics_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Cell_ID", "filter_passed", "included", "predicted_class", "confidence"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Cell_ID": row["cell_id"],
                    "filter_passed": "True",
                    "included": "True",
                    "predicted_class": "cell",
                    "confidence": row["unet_confidence"],
                }
            )

    meta_path = demo_root / "mabs_demo_meta.csv"
    with meta_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Cell_ID", "drug", "GroupLabels_Strict"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Cell_ID": row["cell_id"],
                    "drug": "demo",
                    "GroupLabels_Strict": row["organism"],
                }
            )

    summary_path = demo_root / "extract_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "n_cells_in": len(rows),
                "n_cells_passed": len(rows),
                "channels_seen": {"demo": ["Phase", "Cy5", "OG514"]},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return DatasetConfigRequest(
        output_dir=str(demo_root),
        measurements_path=str(measurements_path),
        crops_dir=str(crops_dir),
        masks_dir=str(masks_dir),
        data_matrix_path=str(data_matrix_path),
        mapping_path=str(mapping_path),
        diagnostics_path=str(diagnostics_path),
        meta_path=str(meta_path),
        id_column="cell_id",
        image_column="crop_path",
        mask_channel_index=1,
    )


def draw_demo_crop(path: Path, is_v_snap: bool, index: int) -> None:
    image = Image.new("RGB", (180, 180), (8, 11, 14))
    draw = ImageDraw.Draw(image, "RGBA")
    for offset in range(0, 180, 18):
        tone = 24 + (offset // 18) % 2 * 5
        draw.line([(offset, 0), (offset + 40, 180)], fill=(tone, tone + 3, tone + 8, 90), width=1)
    color = (88, 166, 255, 230) if not is_v_snap else (242, 184, 75, 235)
    if is_v_snap:
        draw.rounded_rectangle((78, 42, 100, 133), radius=11, fill=color)
        draw.rounded_rectangle((78, 82, 137, 105), radius=11, fill=color)
        draw.ellipse((72, 76, 105, 109), fill=(239, 107, 125, 180))
    else:
        x_offset = (index % 7) * 5
        draw.rounded_rectangle((62 + x_offset, 44, 92 + x_offset, 139), radius=15, fill=color)
        draw.ellipse((67 + x_offset, 54, 88 + x_offset, 75), fill=(86, 209, 155, 120))
    image.save(path)


def draw_demo_mask(path: Path, is_v_snap: bool, index: int) -> None:
    image = Image.new("L", (180, 180), 0)
    draw = ImageDraw.Draw(image)
    if is_v_snap:
        draw.rounded_rectangle((78, 42, 100, 133), radius=11, fill=255)
        draw.rounded_rectangle((78, 82, 137, 105), radius=11, fill=255)
    else:
        x_offset = (index % 7) * 5
        draw.rounded_rectangle((62 + x_offset, 44, 92 + x_offset, 139), radius=15, fill=255)
    image.save(path)

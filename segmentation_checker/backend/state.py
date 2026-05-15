"""Persistent backend state for the segmentation checker."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from segmentation_checker.backend.models import (
    DatasetConfigRequest,
    DatasetConfigResponse,
    ReviewAnnotation,
)


@dataclass
class CellRecord:
    """Internal representation of one measurements row plus resolved assets."""

    id: str
    row_index: int
    row: dict[str, str]
    metrics: dict[str, float | str]
    crop_path: Path | None = None
    mask_path: Path | None = None
    channel_count: int = 1
    channel_names: list[str] = field(default_factory=list)
    channel_metadata: list[dict[str, Any]] = field(default_factory=list)
    image_metadata: dict[str, Any] = field(default_factory=dict)
    mask_channel_index: int | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class CheckerState:
    """Mutable app state loaded by the FastAPI process."""

    config_path: Path
    config: DatasetConfigRequest | None = None
    annotations: dict[str, ReviewAnnotation] = field(default_factory=dict)
    records: list[CellRecord] = field(default_factory=list)

    @property
    def annotations_path(self) -> Path:
        return self.config_path.with_name("checker_annotations.json")

    def review_state_path(self, config: DatasetConfigRequest | None = None) -> Path:
        active_config = config or self.config
        if active_config is not None:
            if active_config.output_dir:
                return Path(active_config.output_dir).expanduser().resolve() / "segmentation_checker_reviews.json"
            if active_config.measurements_path:
                return (
                    Path(active_config.measurements_path)
                    .expanduser()
                    .resolve()
                    .parent
                    / "segmentation_checker_reviews.json"
                )
        return self.annotations_path

    def config_response(self) -> DatasetConfigResponse:
        if self.config is None:
            return DatasetConfigResponse(is_loaded=False)
        return DatasetConfigResponse(**self.config.model_dump(), is_loaded=bool(self.records))

    def load(self) -> None:
        if self.config_path.exists():
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            if data.get("output_dir") or data.get("measurements_path") or data.get("crops_dir"):
                self.config = DatasetConfigRequest(**data)
        self.load_annotations()

    def save_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.config.model_dump() if self.config is not None else {}
        self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_annotations(self) -> None:
        path = self.review_state_path()
        if not path.exists():
            self.annotations = {}
            return
        raw_annotations: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        self.annotations = {
            cell_id: ReviewAnnotation(**annotation)
            for cell_id, annotation in raw_annotations.items()
        }

    def save_annotations(self) -> None:
        path = self.review_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            cell_id: annotation.model_dump()
            for cell_id, annotation in sorted(self.annotations.items())
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

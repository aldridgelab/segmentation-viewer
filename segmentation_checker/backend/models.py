"""Pydantic API models for segmentation review."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ReviewStatus = Literal[
    "unreviewed",
    "accepted",
    "split_needed",
    "merge_needed",
    "rejected",
    "training_candidate",
]

TrainingBin = Literal[
    "none",
    "v_snap",
    "clean_training",
    "hard_negative",
    "needs_resegmentation",
    "out_of_focus",
]

SortDirection = Literal["asc", "desc"]

DEFAULT_CROP_PATTERNS = ["*.png", "*.jpg", "*.jpeg", "*.tif", "*.tiff"]


class DatasetConfigRequest(BaseModel):
    """Request body for loading a segmentation review dataset."""

    output_dir: Optional[str] = None
    measurements_path: Optional[str] = None
    crops_dir: Optional[str] = None
    masks_dir: Optional[str] = None
    data_matrix_path: Optional[str] = None
    mapping_path: Optional[str] = None
    diagnostics_path: Optional[str] = None
    meta_path: Optional[str] = None
    id_column: Optional[str] = None
    image_column: Optional[str] = None
    mask_channel_index: int = Field(default=1, ge=0)
    crop_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_CROP_PATTERNS))


class DatasetConfigResponse(BaseModel):
    """Current dataset configuration."""

    output_dir: Optional[str] = None
    measurements_path: Optional[str] = None
    crops_dir: Optional[str] = None
    masks_dir: Optional[str] = None
    data_matrix_path: Optional[str] = None
    mapping_path: Optional[str] = None
    diagnostics_path: Optional[str] = None
    meta_path: Optional[str] = None
    id_column: Optional[str] = None
    image_column: Optional[str] = None
    mask_channel_index: int = 1
    crop_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_CROP_PATTERNS))
    is_loaded: bool = False


class InspectDatasetRequest(BaseModel):
    """Request body for inspecting measurements and image folders."""

    output_dir: Optional[str] = None
    measurements_path: Optional[str] = None
    crops_dir: Optional[str] = None
    masks_dir: Optional[str] = None
    data_matrix_path: Optional[str] = None
    mapping_path: Optional[str] = None
    diagnostics_path: Optional[str] = None
    meta_path: Optional[str] = None
    crop_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_CROP_PATTERNS))


class InspectDatasetResponse(BaseModel):
    """Inspection summary for a candidate dataset."""

    total_rows: int
    crop_count: int
    mask_count: int
    output_dir: Optional[str] = None
    inferred_crops_dir: Optional[str] = None
    data_matrix_path: Optional[str] = None
    mapping_path: Optional[str] = None
    diagnostics_path: Optional[str] = None
    meta_path: Optional[str] = None
    summary_path: Optional[str] = None
    channel_names: list[str] = Field(default_factory=list)
    columns: list[str]
    numeric_columns: list[str]
    suggested_id_column: Optional[str] = None
    suggested_image_column: Optional[str] = None
    low_eccentricity_count: int = 0
    sample_ids: list[str] = Field(default_factory=list)


class ReviewAnnotation(BaseModel):
    """Stored review decision for one cell."""

    status: ReviewStatus = "unreviewed"
    training_bin: TrainingBin = "none"
    note: str = ""
    updated_at: Optional[str] = None


class AnnotationRequest(BaseModel):
    """Request body for saving a review annotation."""

    status: ReviewStatus
    training_bin: TrainingBin = "none"
    note: str = ""


class BulkAnnotationRequest(BaseModel):
    """Request body for applying one annotation to the active filtered group."""

    search: Optional[str] = None
    status_filter: str = "all"
    training_bin_filter: str = "all"
    flag: Optional[str] = None
    eccentricity_max: Optional[float] = None
    numeric_filter_field: Optional[str] = None
    numeric_filter_op: Literal["lte", "gte"] = "lte"
    numeric_filter_value: Optional[float] = None
    status: ReviewStatus
    training_bin: TrainingBin = "none"
    note: str = ""


class BulkAnnotationResponse(BaseModel):
    """Response after a bulk annotation update."""

    updated_count: int


class CellItem(BaseModel):
    """A single reviewable segmentation/cell crop."""

    id: str
    row_index: int
    crop_url: str
    mask_url: Optional[str] = None
    source_path: Optional[str] = None
    mask_path: Optional[str] = None
    mask_channel_index: Optional[int] = None
    mask_channel_name: Optional[str] = None
    channel_count: int = 1
    channel_names: list[str] = Field(default_factory=list)
    channel_metadata: list[dict[str, Any]] = Field(default_factory=list)
    image_metadata: dict[str, Any] = Field(default_factory=dict)
    status: ReviewStatus = "unreviewed"
    training_bin: TrainingBin = "none"
    note: str = ""
    flags: list[str] = Field(default_factory=list)
    metrics: dict[str, float | str] = Field(default_factory=dict)


class CellsResponse(BaseModel):
    """Paginated cell listing."""

    items: list[CellItem]
    total: int
    shown: int
    low_eccentricity_total: int
    reviewed_total: int


class DatasetSummary(BaseModel):
    """Loaded dataset summary for dashboard counts."""

    total_cells: int = 0
    reviewed_cells: int = 0
    accepted_cells: int = 0
    training_candidates: int = 0
    low_eccentricity_cells: int = 0
    remaining_cells: int = 0
    loaded_output_dir: Optional[str] = None
    loaded_measurements_path: Optional[str] = None
    review_state_path: Optional[str] = None


class DemoDatasetResponse(BaseModel):
    """Response after creating and loading the built-in demo dataset."""

    config: DatasetConfigResponse
    summary: DatasetSummary

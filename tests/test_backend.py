from __future__ import annotations

import json
import struct
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, TiffImagePlugin

from segmentation_checker.backend.data_io import create_demo_dataset, read_crop_tiff_metadata
from segmentation_checker.backend.main import app, checker_state


def imagej_metadata(info: dict, labels: list[str]) -> tuple[tuple[int, ...], bytes]:
    entries = [
        (b"ofni", [json.dumps(info, sort_keys=True).encode("utf-16")]),
        (b"lbal", [label.encode("utf-16") for label in labels]),
    ]
    header = b"JIJI" + b"".join(
        key + struct.pack("<I", len(values))
        for key, values in entries
    )
    payloads = [payload for _, values in entries for payload in values]
    return (len(header), *[len(payload) for payload in payloads]), header + b"".join(payloads)


@pytest.fixture()
def client(tmp_path: Path) -> tuple[TestClient, Path]:
    checker_state.config_path = tmp_path / "checker_config.json"
    checker_state.config = None
    checker_state.annotations = {}
    checker_state.records = []
    demo_config = create_demo_dataset(tmp_path)
    return TestClient(app), Path(demo_config.measurements_path)


def test_inspects_measurements_and_suggests_columns(client: tuple[TestClient, Path]) -> None:
    test_client, measurements_path = client
    response = test_client.post(
        "/api/inspect",
        json={"measurements_path": str(measurements_path)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_rows"] == 48
    assert payload["suggested_id_column"] == "cell_id"
    assert payload["suggested_image_column"] == "crop_path"
    assert payload["low_eccentricity_count"] > 0
    assert "eccentricity" in payload["numeric_columns"]


def test_loads_dataset_and_filters_v_snap_candidates(client: tuple[TestClient, Path]) -> None:
    test_client, measurements_path = client
    config_response = test_client.post(
        "/api/config",
        json={
            "measurements_path": str(measurements_path),
            "crops_dir": str(measurements_path.parent / "passed_crops"),
            "masks_dir": str(measurements_path.parent / "masks"),
            "id_column": "cell_id",
            "image_column": "crop_path",
        },
    )
    assert config_response.status_code == 200

    response = test_client.get("/api/cells?flag=possible_v_snap&eccentricity_max=0.85")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] > 0
    assert all("possible_v_snap" in item["flags"] for item in payload["items"])

    custom_response = test_client.get(
        "/api/cells?numeric_filter_field=eccentricity&numeric_filter_op=lte&numeric_filter_value=0.85"
    )
    assert custom_response.status_code == 200
    assert custom_response.json()["total"] == payload["total"]


def test_loads_pipeline_output_directory(client: tuple[TestClient, Path]) -> None:
    test_client, measurements_path = client
    output_dir = measurements_path.parent

    inspect_response = test_client.post(
        "/api/inspect",
        json={"output_dir": str(output_dir)},
    )
    assert inspect_response.status_code == 200
    inspected = inspect_response.json()
    assert inspected["crop_count"] == 48
    assert inspected["data_matrix_path"].endswith("mabs_demo_data.csv")
    assert inspected["mapping_path"].endswith("mabs_demo_mapping.csv")
    assert inspected["low_eccentricity_count"] > 0

    config_response = test_client.post(
        "/api/config",
        json={"output_dir": str(output_dir)},
    )
    assert config_response.status_code == 200

    response = test_client.get("/api/cells?sort_by=eccentricity&limit=5")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 48
    assert payload["items"][0]["source_path"].endswith(".png")
    assert "eccentricity" in payload["items"][0]["metrics"]


def test_uses_configured_crop_channel_as_mask_when_no_mask_file(tmp_path: Path) -> None:
    checker_state.config_path = tmp_path / "checker_config.json"
    checker_state.config = None
    checker_state.annotations = {}
    checker_state.records = []
    test_client = TestClient(app)

    output_dir = tmp_path / "pipeline_output"
    crops_dir = output_dir / "passed_crops"
    crops_dir.mkdir(parents=True)
    cell_id = "sc_two_channel"
    phase = Image.new("I;16", (24, 24), 1000)
    mask = Image.new("I;16", (24, 24), 0)
    for x in range(8, 16):
        for y in range(6, 18):
            mask.putpixel((x, y), 50000)
    metadata_counts, metadata_payload = imagej_metadata(
        {
            "Cell_ID": cell_id,
            "label": 42,
            "bbox": {"min_row": 6, "min_col": 8, "max_row": 18, "max_col": 16},
            "channels": [
                {"label": "Phase", "kind": "image", "path": "phase.tif"},
                {"label": "Mask", "kind": "mask", "path": "mask.tif"},
            ],
        },
        ["Phase", "Mask"],
    )
    tiffinfo = TiffImagePlugin.ImageFileDirectory_v2()
    tiffinfo[270] = "ImageJ=1.11a\nimages=2\nchannels=2\nhyperstack=true\nmode=grayscale\n"
    tiffinfo[50838] = metadata_counts
    tiffinfo[50839] = metadata_payload
    crop_path = crops_dir / f"{cell_id}.tif"
    phase.save(crop_path, save_all=True, append_images=[mask], tiffinfo=tiffinfo)
    parsed_metadata = read_crop_tiff_metadata(crop_path)
    assert parsed_metadata.channel_names == ["Phase", "Mask"]
    assert parsed_metadata.mask_channel_index == 1
    assert parsed_metadata.image_metadata["label"] == 42
    (output_dir / "demo_data.csv").write_text(
        f"feature,{cell_id}\neccentricity,0.7\narea_px,72\n",
        encoding="utf-8",
    )
    (output_dir / "demo_mapping.csv").write_text(
        f"Cell_ID,crop_path\n{cell_id},passed_crops/{cell_id}.tif\n",
        encoding="utf-8",
    )
    (output_dir / "extract_summary.json").write_text(
        '{"channels_seen": {"demo": ["Phase", "Mask"]}}',
        encoding="utf-8",
    )

    config_response = test_client.post(
        "/api/config",
        json={"output_dir": str(output_dir), "mask_channel_index": 0},
    )
    assert config_response.status_code == 200

    first_cell = test_client.get("/api/cells?limit=1").json()["items"][0]
    assert first_cell["mask_url"] is not None
    assert first_cell["mask_channel_index"] == 1
    assert first_cell["mask_channel_name"] == "Mask"

    image_response = test_client.get(f"/api/cells/{cell_id}/image?kind=mask")
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/png"
    assert image_response.headers["cache-control"] == "no-store"
    assert len(image_response.content) > 100
    assert Image.open(BytesIO(image_response.content)).size == (24, 24)


def test_bulk_annotations_apply_to_filtered_group(client: tuple[TestClient, Path]) -> None:
    test_client, measurements_path = client
    output_dir = measurements_path.parent
    assert test_client.post("/api/config", json={"output_dir": str(output_dir)}).status_code == 200

    filtered = test_client.get("/api/cells?status=unreviewed&flag=possible_v_snap")
    assert filtered.status_code == 200
    target_count = filtered.json()["total"]
    assert target_count > 0

    response = test_client.post(
        "/api/annotations/bulk",
        json={
            "status_filter": "unreviewed",
            "flag": "possible_v_snap",
            "status": "training_candidate",
            "training_bin": "v_snap",
            "note": "",
        },
    )
    assert response.status_code == 200
    assert response.json()["updated_count"] == target_count

    tagged = test_client.get("/api/cells?status=training_candidate&training_bin=v_snap")
    assert tagged.status_code == 200
    assert tagged.json()["total"] == target_count


def test_saves_annotation_exports_csv_and_renders_image(client: tuple[TestClient, Path]) -> None:
    test_client, measurements_path = client
    test_client.post(
        "/api/config",
        json={
            "measurements_path": str(measurements_path),
            "crops_dir": str(measurements_path.parent / "passed_crops"),
            "masks_dir": str(measurements_path.parent / "masks"),
            "id_column": "cell_id",
            "image_column": "crop_path",
        },
    )
    first_cell = test_client.get("/api/cells?limit=1").json()["items"][0]
    cell_id = first_cell["id"]

    annotation_response = test_client.post(
        f"/api/cells/{cell_id}/annotation",
        json={
            "status": "split_needed",
            "training_bin": "needs_resegmentation",
            "note": "single mask covers V-snap pair",
        },
    )

    assert annotation_response.status_code == 200
    assert annotation_response.json()["status"] == "split_needed"
    assert annotation_response.json()["training_bin"] == "needs_resegmentation"
    assert (measurements_path.parent / "segmentation_checker_reviews.json").exists()

    image_response = test_client.get(f"/api/cells/{cell_id}/image")
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/png"
    assert image_response.headers["cache-control"] == "no-store"
    assert len(image_response.content) > 100
    assert Image.open(BytesIO(image_response.content)).size == (180, 180)

    export_response = test_client.get("/api/export/annotations")
    assert export_response.status_code == 200
    assert "split_needed" in export_response.text
    assert "single mask covers V-snap pair" in export_response.text

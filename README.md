# Aldridge Segmentation Checker

Desktop review app for U-Net single-cell segmentation crops and morphology tables. It is built in the same local-app style as `../image-viewer`: Python/FastAPI backend, React/Vite frontend, and a `pywebview` macOS wrapper.

## What It Does

- Loads a pipeline output root like `example_dir/` with `passed_crops/`, `*_data.csv`, `*_mapping.csv`, `*_diagnostics.csv`, `*_meta.csv`, and `extract_summary.json`.
- Joins crop TIFFs, transposed feature tables, mapping rows, diagnostics, and metadata by `Cell_ID`.
- Shows multi-frame 16-bit TIFF crops with per-frame channel controls read from ImageJ TIFF metadata.
- Detects the mask plane from TIFF `Info.channels[].kind == "mask"` or `Labels`, with a configurable fallback.
- Flags likely review targets, including low-eccentricity cells (`eccentricity <= 0.85`) for V-snapping checks.
- Lets a reviewer mark cells as accepted, rejected, out of focus, or reviewer-defined custom review bins.
- Provides an optional custom quick-bin button so V-snap can stay hidden during routine review.
- Applies a training bin in bulk to the current filtered result set, such as all unreviewed V-snap candidates.
- Includes in-app docs for review labels, filters, buttons, and crop metadata.
- Assigns bins such as V-snap, out of focus, clean training, hard negative, and needs resegmentation.
- Saves review progress to `segmentation_checker_reviews.json` next to the loaded output so long review sessions can be resumed.
- Exports the original table with review status, notes, bins, flags, and resolved crop/mask paths.
- Includes a synthetic demo dataset for checking the workflow without real data.

## Quickstart

```bash
cd /Users/josh/aldridge-multiomics/segmentation-checker

./scripts/install.sh
./scripts/start_app.sh
```

Or run the same two-step setup/start flow with:

```bash
./scripts/quickstart.sh
```

Open http://127.0.0.1:5176 for browser development.

In the app, put the pipeline output folder in **Output directory**, then click **Inspect** and **Load**. The app infers the crop folder and CSV files from that one directory, and it reads channel labels, mask position, bbox, source paths, and cell provenance from each crop TIFF. The fallback mask channel is only used if metadata is missing. For the attached example:

```text
/Users/josh/aldridge-multiomics/segmentation-checker/example_dir
```

Use **Bulk review** for grouped work. For example, set filters to unreviewed V-snap candidates, choose the `V-snap` training bin, confirm the matching count, and annotate the whole filtered group at once. Use **Docs** in the header for the in-app action guide.

Launch the desktop wrapper:

```bash
./scripts/start_desktop.sh
```

Use the Codex Run action or this command for the build/run loop:

```bash
./script/build_and_run.sh
```

## Verification

```bash
uv run pytest
cd frontend
npm run lint
npm run build
cd ..
uv run python -m segmentation_checker.desktop --check
```

## Packaging

```bash
./scripts/package_app.sh
```

The package script builds the frontend, generates an icon if needed, creates `dist/Aldridge Segmentation Checker.app`, signs it ad hoc, and writes a DMG.

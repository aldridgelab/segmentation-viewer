# Usage Notes

## Dataset Inputs

The app expects one pipeline output directory. It auto-detects these files:

- `passed_crops/`: local reviewable single-cell crop TIFFs with ImageJ `Labels` and JSON `Info` metadata.
- `*_data.csv`: transposed feature matrix with `feature` in the first column and `Cell_ID` values as columns.
- `*_mapping.csv`: row-wise cell mapping with `Cell_ID`, source image, bounding box, crop path, and channel metadata.
- `*_diagnostics.csv`: classifier/filter diagnostics such as `confidence`, `p_cell`, and `failure_reasons`.
- `*_meta.csv`: treatment/group metadata keyed by `Cell_ID`.
- `extract_summary.json`: extraction counts and fallback channel names.

The app reviews crops that exist locally in `passed_crops/` and enriches each one with matching rows from the feature, mapping, diagnostics, and metadata files.
The mask view is detected from the crop TIFF metadata. The app first uses `Info.channels[].kind == "mask"`, then an ImageJ `Labels` value of `Mask`, and only then the fallback mask-channel selector.

## Review Labels

- `Accepted`: segmentation looks correct.
- `Split needed`: legacy status for one mask likely containing multiple cells. It is available in filters and bulk status, but no longer has a one-click cell button.
- `Merge needed`: legacy status for one cell split across masks. It is available in filters and bulk status, but no longer has a one-click cell button.
- `Reject`: crop is not useful for correction or training.
- `Custom quick bin`: optional reviewer-defined button with a custom label, status, and training bin.
- `Out of focus`: mark the selected cell as rejected and put it in the out-of-focus bin.

## Buttons and Workflow

- `Dataset`: open output-directory and fallback mask-channel settings.
- `Inspect`: preview detected files, channels, and row counts before loading.
- `Load`: load the selected output directory and restore saved reviews.
- `Refresh`: reload counts and the active filtered cell list.
- `Export`: download review annotations merged with metadata.
- `Docs`: open the in-app reference for review labels, filters, buttons, and metadata.
- `Accept`, `Reject`, `Out of focus`: save the corresponding review status/bin for the selected cell.
- `Back`: return to the most recently reviewed cell so a mistaken accept/reject can be changed without searching accepted/rejected filters.
- `Next`: move to the next cell in the current page.
- `Bulk review`: open the bulk page with counts, bulk controls, and the action guide.
- `Show custom quick bin button`: in the Training bin panel, enable a reviewer-defined quick action such as `borderline_non_cell`, `doublet`, or any other custom bin.

## Filters

- `V-snap`: preset for likely snapped candidates; it sets the V-snap flag and `eccentricity <= 0.85`.
- Custom metric filter: choose any numeric metric, choose `<=` or `>=`, and enter a value.
- `Clear`: remove the V-snap/custom numeric filter.

## Bulk Review

The bulk page uses the same active filters as the cell browser. Filter to the group you want, check the matching count, choose a review status and training bin, then use **Apply to matching cells**. For example, filter to unreviewed V-snap candidates, choose `Training` and `V-snap`, and apply once instead of opening each cell.

The confirmation dialog shows how many cells will be updated.

The exported CSV preserves the original measurements and appends review columns.
Every saved review also updates `segmentation_checker_reviews.json` in the loaded output directory, so reopening the same directory resumes reviewed/unreviewed state.

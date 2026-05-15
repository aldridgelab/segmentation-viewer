export type ReviewStatus =
  | 'unreviewed'
  | 'accepted'
  | 'split_needed'
  | 'merge_needed'
  | 'rejected'
  | 'training_candidate';

export type TrainingBin =
  | 'none'
  | 'v_snap'
  | 'clean_training'
  | 'hard_negative'
  | 'needs_resegmentation'
  | 'out_of_focus';

export type MetadataValue = string | number | boolean | null | MetadataValue[] | { [key: string]: MetadataValue };

export interface DatasetConfig {
  output_dir: string | null;
  measurements_path: string | null;
  crops_dir: string | null;
  masks_dir: string | null;
  data_matrix_path: string | null;
  mapping_path: string | null;
  diagnostics_path: string | null;
  meta_path: string | null;
  id_column: string | null;
  image_column: string | null;
  mask_channel_index: number;
  crop_patterns: string[];
  is_loaded: boolean;
}

export interface InspectDatasetResponse {
  total_rows: number;
  crop_count: number;
  mask_count: number;
  output_dir: string | null;
  inferred_crops_dir: string | null;
  data_matrix_path: string | null;
  mapping_path: string | null;
  diagnostics_path: string | null;
  meta_path: string | null;
  summary_path: string | null;
  channel_names: string[];
  columns: string[];
  numeric_columns: string[];
  suggested_id_column: string | null;
  suggested_image_column: string | null;
  low_eccentricity_count: number;
  sample_ids: string[];
}

export interface DatasetSummary {
  total_cells: number;
  reviewed_cells: number;
  accepted_cells: number;
  training_candidates: number;
  low_eccentricity_cells: number;
  remaining_cells: number;
  loaded_output_dir: string | null;
  loaded_measurements_path: string | null;
  review_state_path: string | null;
}

export interface CellItem {
  id: string;
  row_index: number;
  crop_url: string;
  mask_url: string | null;
  source_path: string | null;
  mask_path: string | null;
  mask_channel_index: number | null;
  mask_channel_name: string | null;
  channel_count: number;
  channel_names: string[];
  channel_metadata: Record<string, MetadataValue>[];
  image_metadata: Record<string, MetadataValue>;
  status: ReviewStatus;
  training_bin: TrainingBin;
  note: string;
  flags: string[];
  metrics: Record<string, number | string>;
}

export interface CellsResponse {
  items: CellItem[];
  total: number;
  shown: number;
  low_eccentricity_total: number;
  reviewed_total: number;
}

export interface DatasetConfigRequest {
  output_dir?: string | null;
  measurements_path?: string | null;
  crops_dir?: string | null;
  masks_dir?: string | null;
  data_matrix_path?: string | null;
  mapping_path?: string | null;
  diagnostics_path?: string | null;
  meta_path?: string | null;
  id_column?: string | null;
  image_column?: string | null;
  mask_channel_index?: number;
  crop_patterns?: string[];
}

export interface AnnotationRequest {
  status: ReviewStatus;
  training_bin: TrainingBin;
  note: string;
}

export interface BulkAnnotationRequest extends AnnotationRequest {
  search?: string | null;
  status_filter?: string;
  training_bin_filter?: string;
  flag?: string | null;
  eccentricity_max?: number | null;
  numeric_filter_field?: string | null;
  numeric_filter_op?: 'lte' | 'gte';
  numeric_filter_value?: number | null;
}

export interface BulkAnnotationResponse {
  updated_count: number;
}

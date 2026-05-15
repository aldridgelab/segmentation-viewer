import type {
  AnnotationRequest,
  BulkAnnotationRequest,
  BulkAnnotationResponse,
  CellItem,
  CellsResponse,
  DatasetConfig,
  DatasetConfigRequest,
  DatasetSummary,
  InspectDatasetResponse,
} from './types';

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        message = body.detail;
      }
    } catch {
      // Keep status message.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function getConfig(): Promise<DatasetConfig> {
  return requestJson<DatasetConfig>('/api/config');
}

export function getSummary(): Promise<DatasetSummary> {
  return requestJson<DatasetSummary>('/api/summary');
}

export function inspectDataset(payload: DatasetConfigRequest): Promise<InspectDatasetResponse> {
  return requestJson<InspectDatasetResponse>('/api/inspect', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function setConfig(payload: DatasetConfigRequest): Promise<DatasetConfig> {
  return requestJson<DatasetConfig>('/api/config', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function loadDemoDataset(): Promise<void> {
  await requestJson('/api/demo', { method: 'POST' });
}

export interface CellQuery {
  search?: string;
  status?: string;
  trainingBin?: string;
  flag?: string;
  eccentricityMax?: string;
  numericFilterField?: string;
  numericFilterOp?: 'lte' | 'gte';
  numericFilterValue?: string;
  sortBy?: string;
  sortDir?: 'asc' | 'desc';
  offset?: number;
  limit?: number;
}

export function getCells(query: CellQuery): Promise<CellsResponse> {
  const params = new URLSearchParams();
  if (query.search) params.set('search', query.search);
  if (query.status && query.status !== 'all') params.set('status', query.status);
  if (query.trainingBin && query.trainingBin !== 'all') params.set('training_bin', query.trainingBin);
  if (query.flag) params.set('flag', query.flag);
  if (query.eccentricityMax) params.set('eccentricity_max', query.eccentricityMax);
  if (query.numericFilterField) params.set('numeric_filter_field', query.numericFilterField);
  if (query.numericFilterOp) params.set('numeric_filter_op', query.numericFilterOp);
  if (query.numericFilterValue) params.set('numeric_filter_value', query.numericFilterValue);
  if (query.sortBy) params.set('sort_by', query.sortBy);
  if (query.sortDir) params.set('sort_dir', query.sortDir);
  if (query.offset) params.set('offset', String(query.offset));
  if (query.limit) params.set('limit', String(query.limit));
  const suffix = params.toString();
  return requestJson<CellsResponse>(`/api/cells${suffix ? `?${suffix}` : ''}`);
}

export function saveAnnotation(cellId: string, payload: AnnotationRequest): Promise<CellItem> {
  return requestJson<CellItem>(`/api/cells/${encodeURIComponent(cellId)}/annotation`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function saveBulkAnnotations(payload: BulkAnnotationRequest): Promise<BulkAnnotationResponse> {
  return requestJson<BulkAnnotationResponse>('/api/annotations/bulk', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function downloadAnnotations(): Promise<void> {
  const response = await fetch('/api/export/annotations');
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'segmentation-review-annotations.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

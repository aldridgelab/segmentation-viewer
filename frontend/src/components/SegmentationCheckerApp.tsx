import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Ban,
  BookOpen,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  Download,
  EyeOff,
  Filter,
  FlaskConical,
  FolderOpen,
  ImageIcon,
  ListChecks,
  Loader2,
  RefreshCw,
  Search,
  Settings,
  Tag,
  XCircle,
} from 'lucide-react';
import {
  downloadAnnotations,
  getCells,
  getConfig,
  getSummary,
  inspectDataset,
  loadDemoDataset,
  saveAnnotation,
  saveBulkAnnotations,
  setConfig,
} from '../api/client';
import type {
  CellItem,
  CellsResponse,
  DatasetConfig,
  DatasetSummary,
  InspectDatasetResponse,
  MetadataValue,
  ReviewStatus,
  TrainingBin,
} from '../api/types';
import { APP_VERSION } from '../version';

const emptySummary: DatasetSummary = {
  total_cells: 0,
  reviewed_cells: 0,
  accepted_cells: 0,
  training_candidates: 0,
  low_eccentricity_cells: 0,
  remaining_cells: 0,
  loaded_output_dir: null,
  loaded_measurements_path: null,
  review_state_path: null,
};

const PAGE_SIZE = 100;

const statusOptions: Array<{ value: ReviewStatus | 'all'; label: string }> = [
  { value: 'all', label: 'All status' },
  { value: 'unreviewed', label: 'Unreviewed' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'split_needed', label: 'Split needed' },
  { value: 'merge_needed', label: 'Merge needed' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'training_candidate', label: 'Training' },
];

const binOptions: Array<{ value: TrainingBin | 'all'; label: string }> = [
  { value: 'all', label: 'All bins' },
  { value: 'none', label: 'No bin' },
  { value: 'v_snap', label: 'V-snap' },
  { value: 'clean_training', label: 'Clean train' },
  { value: 'hard_negative', label: 'Hard negative' },
  { value: 'needs_resegmentation', label: 'Resegment' },
  { value: 'out_of_focus', label: 'Out of focus' },
];

const reviewGuide = [
  ['Accept', 'Segmentation is usable as-is and counts as reviewed.'],
  ['Split needed', 'Legacy status for one mask containing more than one cell; available in filters and bulk status.'],
  ['Merge needed', 'Legacy status for one cell split across masks; available in filters and bulk status.'],
  ['Reject', 'Crop should not be used for correction or training; stores hard_negative.'],
  ['V-snap action', 'Marks the cell as a training candidate in the V-snap bin.'],
  ['Out of focus', 'Marks the cell as rejected and stores it in the out-of-focus bin.'],
  ['V-snap bin', 'Training bin for low-eccentricity V-shaped or snapped candidates.'],
  ['Clean train', 'Training bin for clean positive examples.'],
  ['Hard negative', 'Training bin for difficult non-cell or bad crop examples.'],
  ['Resegment', 'Training bin for examples that need corrected segmentation.'],
  ['Out of focus bin', 'Training/review bin for blurred crops that should be separated from segmentation errors.'],
];

const buttonGuide = [
  ['Dataset', 'Open output-directory and fallback mask-channel settings.'],
  ['Refresh', 'Reload counts and the active filtered cell list.'],
  ['Export', 'Download review annotations merged with metadata.'],
  ['Docs', 'Open the in-app reference for labels, buttons, filters, and metadata.'],
  ['Inspect', 'Preview detected files, channels, and row counts before loading.'],
  ['Load', 'Load the selected output directory and restore saved reviews.'],
  ['Bulk review', 'Open grouped annotation controls for every active filter match.'],
  ['Next', 'Move to the next cell in the current page.'],
];

const filterGuide = [
  ['V-snap preset', 'Sets the V-snap flag and eccentricity <= 0.85 filter.'],
  ['Custom metric filter', 'Choose any numeric metric, an operator, and a threshold for the current result set.'],
  ['Status filter', 'Use Unreviewed for normal work so completed cells leave the queue after saving.'],
  ['Training bin filter', 'Review or export cells already assigned to a specific training bin.'],
  ['Search', 'Find a cell ID or matching metadata text.'],
];

function formatCount(value: number): string {
  return value.toLocaleString();
}

function compactPath(path: string | null | undefined): string {
  if (!path) {
    return 'No dataset loaded';
  }
  const parts = path.split('/');
  return parts.length > 3 ? `.../${parts.slice(-3).join('/')}` : path;
}

function formatMetric(value: number | string): string {
  if (typeof value === 'number') {
    if (Math.abs(value) >= 100) return value.toFixed(1);
    if (Math.abs(value) >= 10) return value.toFixed(2);
    return value.toFixed(3);
  }
  return value;
}

function formatMetadataValue(value: MetadataValue): string {
  if (value === null) return '';
  if (typeof value === 'string') return value.includes('/') ? compactPath(value) : value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

function statusLabel(status: ReviewStatus): string {
  return statusOptions.find((option) => option.value === status)?.label ?? status;
}

function flagLabel(flag: string): string {
  const labels: Record<string, string> = {
    possible_v_snap: 'V-snap candidate',
    low_solidity: 'Low solidity',
    low_confidence: 'Low confidence',
    tiny_object: 'Tiny object',
  };
  return labels[flag] ?? flag.replaceAll('_', ' ');
}

export function SegmentationCheckerApp() {
  const [config, setConfigState] = useState<DatasetConfig | null>(null);
  const [summary, setSummary] = useState<DatasetSummary>(emptySummary);
  const [inspectResult, setInspectResult] = useState<InspectDatasetResponse | null>(null);
  const [cellsResponse, setCellsResponse] = useState<CellsResponse | null>(null);
  const [selectedCell, setSelectedCell] = useState<CellItem | null>(null);
  const [draftNote, setDraftNote] = useState('');

  const [outputDir, setOutputDir] = useState('');
  const [selectedFrame, setSelectedFrame] = useState(0);
  const [maskChannelIndex, setMaskChannelIndex] = useState(1);
  const [pageOffset, setPageOffset] = useState(0);

  const [showSetup, setShowSetup] = useState(false);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<ReviewStatus | 'all'>('unreviewed');
  const [binFilter, setBinFilter] = useState<TrainingBin | 'all'>('all');
  const [bulkStatus, setBulkStatus] = useState<ReviewStatus>('training_candidate');
  const [bulkBin, setBulkBin] = useState<TrainingBin>('v_snap');
  const [bulkNote, setBulkNote] = useState('');
  const [flagFilter, setFlagFilter] = useState('');
  const [numericFilterField, setNumericFilterField] = useState('eccentricity');
  const [numericFilterOp, setNumericFilterOp] = useState<'lte' | 'gte'>('lte');
  const [numericFilterValue, setNumericFilterValue] = useState('');
  const [sortBy, setSortBy] = useState('review_priority');
  const [isLoading, setIsLoading] = useState(false);
  const [isInspecting, setIsInspecting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isBulkSaving, setIsBulkSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<'single' | 'bulk' | 'docs'>('single');

  const metricKeys = useMemo(() => {
    const keys = new Set<string>();
    cellsResponse?.items.forEach((cell) => {
      Object.keys(cell.metrics).forEach((key) => keys.add(key));
    });
    return Array.from(keys).sort((a, b) => a.localeCompare(b));
  }, [cellsResponse]);

  const loadSummary = useCallback(async () => {
    const nextSummary = await getSummary();
    setSummary(nextSummary);
  }, []);

  const loadCells = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getCells({
        search: search.trim() || undefined,
        status: statusFilter,
        trainingBin: binFilter,
        flag: flagFilter || undefined,
        numericFilterField: numericFilterValue.trim() ? numericFilterField : undefined,
        numericFilterOp,
        numericFilterValue: numericFilterValue.trim() || undefined,
        sortBy,
        sortDir: sortBy === 'review_priority' || sortBy === 'eccentricity' ? 'asc' : 'desc',
        offset: pageOffset,
        limit: PAGE_SIZE,
      });
      setCellsResponse(response);
      setSelectedCell((current) => {
        if (response.items.length === 0) {
          return null;
        }
        if (!current) {
          return response.items[0];
        }
        return response.items.find((cell) => cell.id === current.id) ?? response.items[0];
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load cells');
    } finally {
      setIsLoading(false);
    }
  }, [binFilter, flagFilter, numericFilterField, numericFilterOp, numericFilterValue, pageOffset, search, sortBy, statusFilter]);

  useEffect(() => {
    getConfig()
      .then((currentConfig) => {
        setConfigState(currentConfig);
        setOutputDir(currentConfig.output_dir ?? '');
        setMaskChannelIndex(currentConfig.mask_channel_index ?? 1);
        setShowSetup(!currentConfig.is_loaded);
      })
      .then(() => loadSummary())
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load configuration');
        setShowSetup(true);
      });
  }, [loadSummary]);

  useEffect(() => {
    if (config?.is_loaded) {
      const timer = window.setTimeout(() => {
        void loadCells();
      }, 0);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [config?.is_loaded, loadCells]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDraftNote(selectedCell?.note ?? '');
      setSelectedFrame(0);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selectedCell?.id, selectedCell?.note]);

  const inspectCurrentDataset = useCallback(async () => {
    if (!outputDir.trim()) {
      setError('Output directory is required.');
      return;
    }
    setIsInspecting(true);
    setError(null);
    try {
      const result = await inspectDataset({
        output_dir: outputDir.trim(),
      });
      setInspectResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to inspect dataset');
    } finally {
      setIsInspecting(false);
    }
  }, [outputDir]);

  async function applyDataset() {
    if (!outputDir.trim()) {
      setError('Output directory is required.');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const nextConfig = await setConfig({
        output_dir: outputDir.trim(),
        mask_channel_index: maskChannelIndex,
      });
      setConfigState(nextConfig);
      setShowSetup(false);
      await loadSummary();
      await loadCells();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dataset');
    } finally {
      setIsLoading(false);
    }
  }

  const loadDemo = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      await loadDemoDataset();
      const nextConfig = await getConfig();
      setConfigState(nextConfig);
      setOutputDir(nextConfig.output_dir ?? '');
      setMaskChannelIndex(nextConfig.mask_channel_index ?? 1);
      setShowSetup(false);
      await loadSummary();
      await loadCells();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load demo dataset');
    } finally {
      setIsLoading(false);
    }
  }, [loadCells, loadSummary]);

  const updateAnnotation = useCallback(
    async (status: ReviewStatus, trainingBin: TrainingBin = selectedCell?.training_bin ?? 'none') => {
      if (!selectedCell) return;
      setIsSaving(true);
      setError(null);
      try {
        const updated = await saveAnnotation(selectedCell.id, {
          status,
          training_bin: trainingBin,
          note: draftNote,
        });
        setSelectedCell(updated);
        setCellsResponse((current) => {
          if (!current) return current;
          return {
            ...current,
            items: current.items.map((item) => (item.id === updated.id ? updated : item)),
          };
        });
        await loadSummary();
        await loadCells();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to save annotation');
      } finally {
        setIsSaving(false);
      }
    },
    [draftNote, loadCells, loadSummary, selectedCell],
  );

  const updateBin = useCallback(
    async (trainingBin: TrainingBin) => {
      if (!selectedCell) return;
      const nextStatus =
        trainingBin !== 'none' && selectedCell.status === 'unreviewed'
          ? 'training_candidate'
          : selectedCell.status;
      await updateAnnotation(nextStatus, trainingBin);
    },
    [selectedCell, updateAnnotation],
  );

  const bulkApplyBin = useCallback(async () => {
    const targetCount = cellsResponse?.total ?? 0;
    if (targetCount === 0) return;
    const binLabel = binOptions.find((option) => option.value === bulkBin)?.label ?? bulkBin;
    const statusTargetLabel = statusOptions.find((option) => option.value === bulkStatus)?.label ?? bulkStatus;
    const confirmed = window.confirm(`Apply ${statusTargetLabel} / ${binLabel} to ${formatCount(targetCount)} matching cells?`);
    if (!confirmed) return;
    const parsedNumericFilterValue = Number(numericFilterValue);
    setIsBulkSaving(true);
    setError(null);
    try {
      await saveBulkAnnotations({
        search: search.trim() || null,
        status_filter: statusFilter,
        training_bin_filter: binFilter,
        flag: flagFilter || null,
        eccentricity_max: null,
        numeric_filter_field: numericFilterValue.trim() ? numericFilterField : null,
        numeric_filter_op: numericFilterOp,
        numeric_filter_value:
          numericFilterValue.trim() && Number.isFinite(parsedNumericFilterValue)
            ? parsedNumericFilterValue
            : null,
        status: bulkStatus,
        training_bin: bulkBin,
        note: bulkNote,
      });
      await loadSummary();
      await loadCells();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply bulk label');
    } finally {
      setIsBulkSaving(false);
    }
  }, [binFilter, bulkBin, bulkNote, bulkStatus, cellsResponse?.total, flagFilter, loadCells, loadSummary, numericFilterField, numericFilterOp, numericFilterValue, search, statusFilter]);

  const exportCsv = useCallback(async () => {
    setError(null);
    try {
      await downloadAnnotations();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to export annotations');
    }
  }, []);

  const selectedMetrics = useMemo(() => {
    if (!selectedCell) return [];
    return Object.entries(selectedCell.metrics).sort(([left], [right]) => left.localeCompare(right));
  }, [selectedCell]);

  const selectedMetadata = useMemo(() => {
    if (!selectedCell) return [];
    return Object.entries(selectedCell.image_metadata)
      .filter(([key]) => key !== 'channels')
      .sort(([left], [right]) => left.localeCompare(right));
  }, [selectedCell]);

  const maskChannelOptions = useMemo(() => {
    const names =
      inspectResult?.channel_names.length
        ? inspectResult.channel_names
        : selectedCell?.channel_names.length
          ? selectedCell.channel_names
          : [];
    const count = Math.max(names.length, selectedCell?.channel_count ?? 0, maskChannelIndex + 1, 4);
    return Array.from({ length: count }, (_, index) => ({
      value: index,
      label: `${index + 1}${names[index] ? ` - ${names[index]}` : ''}`,
    }));
  }, [inspectResult, maskChannelIndex, selectedCell]);

  const selectRelativeCell = useCallback(
    (step: number) => {
      if (!cellsResponse?.items.length || !selectedCell) return;
      const index = cellsResponse.items.findIndex((cell) => cell.id === selectedCell.id);
      const nextIndex = Math.max(0, Math.min(cellsResponse.items.length - 1, index + step));
      setSelectedCell(cellsResponse.items[nextIndex]);
    },
    [cellsResponse, selectedCell],
  );

  const pageStart = cellsResponse && cellsResponse.total > 0 ? pageOffset + 1 : 0;
  const pageEnd = cellsResponse ? Math.min(pageOffset + cellsResponse.shown, cellsResponse.total) : 0;
  const hasPreviousPage = pageOffset > 0;
  const hasNextPage = cellsResponse ? pageOffset + cellsResponse.shown < cellsResponse.total : false;
  const selectedMaskLabel =
    selectedCell?.mask_channel_name ??
    (selectedCell?.mask_channel_index !== null && selectedCell?.mask_channel_index !== undefined
      ? `Channel ${selectedCell.mask_channel_index + 1}`
      : 'Mask');
  const customMetricOptions = useMemo(() => {
    const preferred = ['eccentricity', 'confidence', 'unet_confidence', 'area', 'area_px'];
    return Array.from(new Set([...preferred, ...metricKeys])).filter(Boolean);
  }, [metricKeys]);
  const quickReviewActions: Array<{
    key: string;
    label: string;
    status: ReviewStatus;
    trainingBin: TrainingBin;
    className: string;
    icon: ReactNode;
  }> = [
    {
      key: 'accept',
      label: 'Accept',
      status: 'accepted',
      trainingBin: 'none',
      className: 'accept',
      icon: <CheckCircle2 size={16} />,
    },
    {
      key: 'v_snap',
      label: 'V-snap',
      status: 'training_candidate',
      trainingBin: 'v_snap',
      className: 'vsnap',
      icon: <Tag size={16} />,
    },
    {
      key: 'out_of_focus',
      label: 'Out of focus',
      status: 'rejected',
      trainingBin: 'out_of_focus',
      className: 'focus',
      icon: <EyeOff size={16} />,
    },
    {
      key: 'reject',
      label: 'Reject',
      status: 'rejected',
      trainingBin: 'hard_negative',
      className: 'reject',
      icon: <Ban size={16} />,
    },
  ];

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-block">
          <div className="brand-logo">SC</div>
          <div className="brand-copy">
            <div className="brand-title">
              <h1>Segmentation Checker</h1>
              <span className="brand-version">v{APP_VERSION}</span>
            </div>
            <div className="brand-status">{compactPath(summary.loaded_output_dir ?? summary.loaded_measurements_path)}</div>
          </div>
        </div>
        <div className="header-actions">
          <button className="icon-button" type="button" onClick={() => setActiveView('docs')}>
            <BookOpen size={16} />
            <span>Docs</span>
          </button>
          <button className="icon-button" type="button" onClick={() => setActiveView('bulk')}>
            <ListChecks size={16} />
            <span>Bulk review</span>
          </button>
          <button className="icon-button" type="button" onClick={() => setShowSetup((value) => !value)}>
            <Settings size={16} />
            <span>Dataset</span>
          </button>
          <button className="icon-button" type="button" onClick={() => void loadCells()} disabled={!config?.is_loaded || isLoading}>
            {isLoading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
            <span>Refresh</span>
          </button>
          <button className="icon-button" type="button" onClick={() => void exportCsv()} disabled={!config?.is_loaded}>
            <Download size={16} />
            <span>Export</span>
          </button>
        </div>
      </header>

      <section className={`setup-panel ${showSetup ? 'is-open' : ''}`}>
        <div className="setup-grid">
          <label>
            <span>Output directory</span>
            <input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} placeholder="/path/to/output_dir" />
          </label>
          <label>
            <span>Fallback mask channel</span>
            <select value={maskChannelIndex} onChange={(event) => setMaskChannelIndex(Number(event.target.value))}>
              {maskChannelOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <div className="setup-actions">
            <button className="secondary-button" type="button" onClick={() => void inspectCurrentDataset()} disabled={isInspecting}>
              {isInspecting ? <Loader2 size={16} className="spin" /> : <FolderOpen size={16} />}
              <span>Inspect</span>
            </button>
            <button className="primary-button" type="button" onClick={() => void applyDataset()} disabled={isLoading}>
              <Database size={16} />
              <span>Load</span>
            </button>
            <button className="secondary-button" type="button" onClick={() => void loadDemo()} disabled={isLoading}>
              <ImageIcon size={16} />
              <span>Demo</span>
            </button>
          </div>
        </div>

        {inspectResult && (
          <div className="inspect-strip">
            <span>{formatCount(inspectResult.crop_count)} local crops</span>
            <span>{formatCount(inspectResult.total_rows)} table cells</span>
            <span>{formatCount(inspectResult.mask_count)} masks</span>
            <span>{formatCount(inspectResult.low_eccentricity_count)} low-eccentricity</span>
            <span>{inspectResult.channel_names.length || 'auto'} channels</span>
            <span>metadata mask preferred</span>
            <span>{inspectResult.numeric_columns.length} numeric columns</span>
          </div>
        )}
      </section>

      {error && (
        <div className="error-banner">
          <XCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      <main className="app-main">
        <section className="summary-row">
          <StatCard label="Cells" value={summary.total_cells} icon={<Database size={17} />} />
          <StatCard label="Reviewed" value={summary.reviewed_cells} icon={<CheckCircle2 size={17} />} />
          <StatCard label="Remaining" value={summary.remaining_cells} icon={<ChevronRight size={17} />} />
          <StatCard label="V-snap queue" value={summary.low_eccentricity_cells} icon={<Filter size={17} />} />
          <StatCard label="Training" value={summary.training_candidates} icon={<FlaskConical size={17} />} />
        </section>

        <section className="workbench">
          <aside className="browser-pane">
            <div className="filter-bar">
              <label className="search-field">
                <Search size={15} />
                <input
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setPageOffset(0);
                  }}
                  placeholder="Search cells"
                />
              </label>
              <select
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(event.target.value as ReviewStatus | 'all');
                  setPageOffset(0);
                }}
              >
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <select
                value={binFilter}
                onChange={(event) => {
                  setBinFilter(event.target.value as TrainingBin | 'all');
                  setPageOffset(0);
                }}
              >
                {binOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <select
                value={sortBy}
                onChange={(event) => {
                  setSortBy(event.target.value);
                  setPageOffset(0);
                }}
              >
                <option value="review_priority">Priority</option>
                <option value="eccentricity">Eccentricity</option>
                <option value="confidence">Confidence</option>
                <option value="unet_confidence">U-Net confidence</option>
                <option value="area">Area</option>
                <option value="area_px">Area px</option>
                <option value="id">Cell ID</option>
                {metricKeys.map((metric) => (
                  <option key={metric} value={metric}>
                    {metric}
                  </option>
                ))}
              </select>
            </div>

            <div className="quick-filters">
              <button
                className={flagFilter === 'possible_v_snap' ? 'chip is-active' : 'chip'}
                type="button"
                onClick={() => {
                  const enabling =
                    flagFilter !== 'possible_v_snap' ||
                    numericFilterField !== 'eccentricity' ||
                    numericFilterOp !== 'lte' ||
                    numericFilterValue !== '0.85';
                  setFlagFilter(enabling ? 'possible_v_snap' : '');
                  setNumericFilterField('eccentricity');
                  setNumericFilterOp('lte');
                  setNumericFilterValue(enabling ? '0.85' : '');
                  setPageOffset(0);
                }}
              >
                <Filter size={14} />
                <span>V-snap</span>
              </button>
              <div className="custom-filter">
                <select
                  value={numericFilterField}
                  onChange={(event) => {
                    setNumericFilterField(event.target.value);
                    setPageOffset(0);
                  }}
                >
                  {customMetricOptions.map((metric) => (
                    <option key={metric} value={metric}>
                      {metric}
                    </option>
                  ))}
                </select>
                <select
                  value={numericFilterOp}
                  onChange={(event) => {
                    setNumericFilterOp(event.target.value as 'lte' | 'gte');
                    setPageOffset(0);
                  }}
                >
                  <option value="lte">&lt;=</option>
                  <option value="gte">&gt;=</option>
                </select>
                <input
                  value={numericFilterValue}
                  onChange={(event) => {
                    setNumericFilterValue(event.target.value);
                    setPageOffset(0);
                  }}
                  placeholder="value"
                />
              </div>
              <button
                className="chip"
                type="button"
                onClick={() => {
                  setFlagFilter('');
                  setNumericFilterField('eccentricity');
                  setNumericFilterOp('lte');
                  setNumericFilterValue('');
                  setPageOffset(0);
                }}
              >
                <XCircle size={14} />
                <span>Clear</span>
              </button>
            </div>

            <div className="browser-count">
              <span>{formatCount(cellsResponse?.total ?? 0)} matching</span>
              <span>
                {formatCount(pageStart)}-{formatCount(pageEnd)}
              </span>
              <span>{formatCount(cellsResponse?.low_eccentricity_total ?? 0)} flagged</span>
            </div>

            <div className="pager-row">
              <button
                className="secondary-button"
                type="button"
                onClick={() => setPageOffset((value) => Math.max(0, value - PAGE_SIZE))}
                disabled={!hasPreviousPage || isLoading}
              >
                <ChevronLeft size={15} />
                <span>Previous</span>
              </button>
              <button
                className="secondary-button"
                type="button"
                onClick={() => setPageOffset((value) => value + PAGE_SIZE)}
                disabled={!hasNextPage || isLoading}
              >
                <span>Next</span>
                <ChevronRight size={15} />
              </button>
            </div>

            <div className="cell-grid">
              {!config?.is_loaded && (
                <div className="empty-state">
                  <ImageIcon size={28} />
                  <strong>No dataset</strong>
                  <span>Load an output directory or demo data.</span>
                </div>
              )}
              {config?.is_loaded && cellsResponse?.items.length === 0 && (
                <div className="empty-state">
                  <Filter size={28} />
                  <strong>No matches</strong>
                  <span>Adjust filters.</span>
                </div>
              )}
              {cellsResponse?.items.map((cell) => (
                <button
                  key={cell.id}
                  type="button"
                  className={`cell-card ${selectedCell?.id === cell.id ? 'is-selected' : ''}`}
                  onClick={() => {
                    setSelectedCell(cell);
                    setActiveView('single');
                  }}
                >
                  <div className="cell-card__body">
                    <div className="cell-card__heading">
                      <span className="cell-card__id">{cell.id}</span>
                      <span className={`status-pill status-${cell.status}`}>{statusLabel(cell.status)}</span>
                    </div>
                    <div className="cell-card__metrics">
                      {cell.metrics.eccentricity !== undefined && <span>ecc {formatMetric(cell.metrics.eccentricity)}</span>}
                      {cell.metrics.confidence !== undefined && <span>conf {formatMetric(cell.metrics.confidence)}</span>}
                      {cell.metrics.area !== undefined && <span>area {formatMetric(cell.metrics.area)}</span>}
                      {cell.metrics.area_px !== undefined && <span>area {formatMetric(cell.metrics.area_px)}</span>}
                    </div>
                    {cell.flags.length > 0 && <span className="flag-pill">{flagLabel(cell.flags[0])}</span>}
                  </div>
                </button>
              ))}
            </div>
          </aside>

          <section className="detail-pane">
            {activeView === 'docs' ? (
              <div className="docs-page">
                <div className="detail-header">
                  <div>
                    <h2>Docs</h2>
                    <span>Review labels, filters, buttons, and metadata</span>
                  </div>
                  <span className="status-pill">Reference</span>
                </div>

                <section className="panel-section">
                  <div className="section-title">
                    <BookOpen size={15} />
                    <span>Review actions</span>
                  </div>
                  <div className="doc-grid">
                    {reviewGuide.map(([label, description]) => (
                      <div key={label}>
                        <strong>{label}</strong>
                        <span>{description}</span>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="panel-section">
                  <div className="section-title">
                    <Filter size={15} />
                    <span>Filters</span>
                  </div>
                  <div className="doc-grid">
                    {filterGuide.map(([label, description]) => (
                      <div key={label}>
                        <strong>{label}</strong>
                        <span>{description}</span>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="panel-section">
                  <div className="section-title">
                    <Settings size={15} />
                    <span>Buttons</span>
                  </div>
                  <div className="doc-grid">
                    {buttonGuide.map(([label, description]) => (
                      <div key={label}>
                        <strong>{label}</strong>
                        <span>{description}</span>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="panel-section">
                  <div className="section-title">
                    <Database size={15} />
                    <span>Metadata</span>
                  </div>
                  <div className="doc-grid">
                    <div>
                      <strong>Channels</strong>
                      <span>Crop TIFF channel labels come from ImageJ Labels and JSON Info metadata.</span>
                    </div>
                    <div>
                      <strong>Mask plane</strong>
                      <span>The app prefers Info.channels entries with kind=mask, then a channel named Mask, then the fallback setting.</span>
                    </div>
                    <div>
                      <strong>Resume file</strong>
                      <span>Review state is saved as segmentation_checker_reviews.json beside the loaded output directory.</span>
                    </div>
                  </div>
                </section>
              </div>
            ) : activeView === 'bulk' ? (
              <div className="bulk-review-page">
                <div className="detail-header">
                  <div>
                    <h2>Bulk Review</h2>
                    <span>{formatCount(cellsResponse?.total ?? 0)} matching active filters</span>
                  </div>
                  <span className="status-pill status-training_candidate">Filtered group</span>
                </div>

                <div className="bulk-summary-grid">
                  <div>
                    <span>Matching</span>
                    <strong>{formatCount(cellsResponse?.total ?? 0)}</strong>
                  </div>
                  <div>
                    <span>Reviewed in filter</span>
                    <strong>{formatCount(cellsResponse?.reviewed_total ?? 0)}</strong>
                  </div>
                  <div>
                    <span>Flagged in filter</span>
                    <strong>{formatCount(cellsResponse?.low_eccentricity_total ?? 0)}</strong>
                  </div>
                  <div>
                    <span>Page size</span>
                    <strong>{formatCount(cellsResponse?.shown ?? 0)}</strong>
                  </div>
                </div>

                <section className="panel-section bulk-review-controls">
                  <div className="section-title">
                    <ListChecks size={15} />
                    <span>Apply annotation</span>
                  </div>
                  <div className="bulk-control-grid">
                    <label>
                      <span>Review status</span>
                      <select value={bulkStatus} onChange={(event) => setBulkStatus(event.target.value as ReviewStatus)}>
                        {statusOptions
                          .filter((option) => option.value !== 'all' && option.value !== 'unreviewed')
                          .map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label>
                      <span>Training bin</span>
                      <select value={bulkBin} onChange={(event) => setBulkBin(event.target.value as TrainingBin)}>
                        {binOptions
                          .filter((option) => option.value !== 'all')
                          .map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                      </select>
                    </label>
                  </div>
                  <textarea value={bulkNote} onChange={(event) => setBulkNote(event.target.value)} placeholder="Bulk note" />
                  <button
                    className="primary-button full-width"
                    type="button"
                    onClick={() => void bulkApplyBin()}
                    disabled={!config?.is_loaded || isBulkSaving || (cellsResponse?.total ?? 0) === 0}
                  >
                    {isBulkSaving ? <Loader2 size={16} className="spin" /> : <ListChecks size={16} />}
                    <span>Apply to matching cells</span>
                  </button>
                </section>

                <section className="panel-section">
                  <div className="section-title">
                    <BookOpen size={15} />
                    <span>Review actions</span>
                  </div>
                  <div className="doc-grid">
                    {reviewGuide.map(([label, description]) => (
                      <div key={label}>
                        <strong>{label}</strong>
                        <span>{description}</span>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="panel-section">
                  <div className="section-title">
                    <BookOpen size={15} />
                    <span>Buttons</span>
                  </div>
                  <div className="doc-grid">
                    {buttonGuide.map(([label, description]) => (
                      <div key={label}>
                        <strong>{label}</strong>
                        <span>{description}</span>
                      </div>
                    ))}
                  </div>
                </section>
              </div>
            ) : selectedCell ? (
              <>
                <div className="detail-header">
                  <div>
                    <h2>{selectedCell.id}</h2>
                    <span>{selectedCell.source_path ? compactPath(selectedCell.source_path) : 'No crop path'}</span>
                  </div>
                  <span className={`status-pill status-${selectedCell.status}`}>{statusLabel(selectedCell.status)}</span>
                </div>

                <div className="image-pair">
                  <figure>
                    <img src={`${selectedCell.crop_url}&frame=${selectedFrame}`} alt="" />
                    <figcaption>{selectedCell.channel_names[selectedFrame] ?? `Frame ${selectedFrame + 1}`}</figcaption>
                  </figure>
                  <figure className={!selectedCell.mask_url ? 'is-muted' : ''}>
                    {selectedCell.mask_url ? <img src={selectedCell.mask_url} alt="" /> : <div className="missing-mask">No mask</div>}
                    <figcaption>{selectedCell.mask_path ? 'Mask file' : selectedMaskLabel}</figcaption>
                  </figure>
                </div>

                {selectedCell.channel_count > 1 && (
                  <div className="channel-strip">
                    {Array.from({ length: selectedCell.channel_count }, (_, index) => (
                      <button
                        key={index}
                        type="button"
                        className={selectedFrame === index ? 'channel-button is-active' : 'channel-button'}
                        onClick={() => setSelectedFrame(index)}
                      >
                        <img src={`${selectedCell.crop_url}&frame=${index}`} alt="" />
                        <span>{selectedCell.channel_names[index] ?? `Frame ${index + 1}`}</span>
                      </button>
                    ))}
                  </div>
                )}

                <div className="action-row">
                  {quickReviewActions.map((action) => (
                    <button
                      key={action.key}
                      className={`action-button ${action.className}`}
                      type="button"
                      onClick={() => void updateAnnotation(action.status, action.trainingBin)}
                      disabled={isSaving}
                    >
                      {action.icon}
                      <span>{action.label}</span>
                    </button>
                  ))}
                  <button className="action-button next" type="button" onClick={() => selectRelativeCell(1)} disabled={isSaving}>
                    <ChevronRight size={16} />
                    <span>Next</span>
                  </button>
                </div>

                <div className="detail-grid">
                  <section className="panel-section">
                    <div className="section-title">
                      <Tag size={15} />
                      <span>Training bin</span>
                    </div>
                    <select value={selectedCell.training_bin} onChange={(event) => void updateBin(event.target.value as TrainingBin)}>
                      {binOptions
                        .filter((option) => option.value !== 'all')
                        .map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                    </select>
                    <div className="flag-list">
                      {selectedCell.flags.length === 0 ? (
                        <span className="muted">No morphology flags</span>
                      ) : (
                        selectedCell.flags.map((flag) => <span key={flag}>{flagLabel(flag)}</span>)
                      )}
                    </div>
                    <textarea value={draftNote} onChange={(event) => setDraftNote(event.target.value)} placeholder="Reviewer note" />
                    <button className="secondary-button full-width" type="button" onClick={() => void updateAnnotation(selectedCell.status, selectedCell.training_bin)} disabled={isSaving}>
                      {isSaving ? <Loader2 size={16} className="spin" /> : <CheckCircle2 size={16} />}
                      <span>Save note</span>
                    </button>
                  </section>

                  <section className="panel-section">
                    <div className="section-title">
                      <Filter size={15} />
                      <span>Morphology</span>
                    </div>
                    <div className="metric-table">
                      {selectedMetrics.map(([key, value]) => (
                        <div key={key}>
                          <span>{key}</span>
                          <strong>{formatMetric(value)}</strong>
                        </div>
                      ))}
                    </div>
                  </section>

                  <section className="panel-section metadata-section">
                    <div className="section-title">
                      <Database size={15} />
                      <span>Image metadata</span>
                    </div>
                    <div className="channel-meta-list">
                      {selectedCell.channel_metadata.length > 0 ? (
                        selectedCell.channel_metadata.map((channel, index) => (
                          <div key={`${channel.label ?? index}`}>
                            <strong>{String(channel.label ?? selectedCell.channel_names[index] ?? `Frame ${index + 1}`)}</strong>
                            <span>{String(channel.kind ?? 'image')}</span>
                            {channel.path && <em>{formatMetadataValue(channel.path)}</em>}
                          </div>
                        ))
                      ) : (
                        selectedCell.channel_names.map((name, index) => (
                          <div key={`${name}-${index}`}>
                            <strong>{name}</strong>
                            <span>{index === selectedCell.mask_channel_index ? 'mask' : 'image'}</span>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="metadata-table">
                      {selectedMetadata.length === 0 ? (
                        <div>
                          <span>metadata</span>
                          <strong>Not found</strong>
                        </div>
                      ) : (
                        selectedMetadata.map(([key, value]) => (
                          <div key={key}>
                            <span>{key}</span>
                            <strong>{formatMetadataValue(value)}</strong>
                          </div>
                        ))
                      )}
                    </div>
                  </section>
                </div>
              </>
            ) : (
              <div className="detail-empty">
                <ImageIcon size={42} />
                <strong>Select a cell</strong>
              </div>
            )}
          </section>
        </section>
      </main>
    </div>
  );
}

function StatCard({ label, value, icon }: { label: string; value: number; icon: ReactNode }) {
  return (
    <div className="stat-card">
      <div className="stat-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{formatCount(value)}</strong>
      </div>
    </div>
  );
}

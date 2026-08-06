const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8731";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export interface Drive {
  id: number;
  letter: string;
  volume_name: string;
  filesystem: string;
  drive_type: string;
  capacity_bytes: number;
  used_bytes: number;
  free_bytes: number;
  health: "ok" | "warning" | "critical" | "unknown";
}

export interface Statistics {
  total_files: number;
  total_bytes: number;
  duplicate_reclaimable_bytes: number;
  vault_bytes: number;
  drives: Drive[];
}

export interface DuplicateGroup {
  id: number;
  sha256: string;
  file_count: number;
  total_size_bytes: number;
  reclaimable_bytes: number;
  status: string;
}

export interface DuplicateMember {
  id: number;
  full_path: string;
  filename: string;
  size_bytes: number;
  is_survivor: number;
  selection_reason: string;
}

export interface VaultEntry {
  id: number;
  cleanup_history_id: number;
  vault_path: string;
  original_path: string;
  size_bytes: number;
  moved_at: string;
  expires_at: string;
  restored: number;
}

export interface WatchedFolder {
  id: number;
  path: string;
  label: string | null;
  enabled: number;
  added_at: string;
  last_scanned_at: string | null;
  last_scan_status: string | null;
}

export interface FolderMonitorStatus {
  active: boolean;
  id?: number;
  path?: string;
  enabled?: boolean;
  paused?: boolean;
  status?: string;
  scan_interval_seconds?: number;
  notifications_enabled?: boolean;
  last_scan_at?: string | null;
  next_scan_at?: string | null;
  last_scan_status?: string;
  total_files?: number;
  duplicate_groups?: number;
  duplicate_files?: number;
  reclaimable_bytes?: number;
  recovered_bytes?: number;
  vault_entries?: number;
  vault_bytes?: number;
}

export interface AppNotification {
  id: number;
  message: string;
  level: "info" | "success" | "warning" | "error";
  source: string;
  created_at: string;
  read: number;
}

export interface VersionCleanupStatus {
  active: boolean;
  id?: number;
  path?: string;
  enabled?: boolean;
  paused?: boolean;
  status?: string;
  scan_interval_seconds?: number;
  automatic_cleanup?: boolean;
  move_to_safe_vault?: boolean;
  notifications_enabled?: boolean;
  last_scan_at?: string | null;
  next_scan_at?: string | null;
  last_scan_status?: string;
  version_groups_pending?: number;
  version_groups_needing_confirmation?: number;
  version_groups_cleaned?: number;
  storage_saved_bytes?: number;
}

export interface VersionGroup {
  id: number;
  base_name: string;
  member_count: number;
  kept_member_path: string | null;
  storage_saved_bytes: number;
  status: string;
  decision_reason: string | null;
  detected_at: string;
}

export interface VersionGroupMember {
  id: number;
  full_path: string;
  is_folder: number;
  version_label: string;
  version_number: number | null;
  size_bytes: number;
  modified_time: string;
  is_kept: number;
  move_status: string;
}

export interface TieBreakSuggestion {
  suggested_full_path: string;
  confidence: number;
  reason: string;
}

export interface ScanFilterCategory {
  id: string;
  extensions: string[];
}

export interface ScanFilterSettings {
  enabled_categories: string[];
  ignored_folder_names: string[];
  minimum_file_size_bytes: number;
  available_categories: ScanFilterCategory[];
}

export interface CleanupHistoryEntry {
  id: number;
  file_id: number | null;
  group_id: number | null;
  original_path: string;
  vault_path: string | null;
  action: string;
  size_bytes: number;
  reason: string | null;
  performed_at: string;
  restored_at: string | null;
  is_restorable: number;
}

export const api = {
  getDrives: () => request<Drive[]>("/drives"),
  refreshDrives: () => request<Drive[]>("/drives/refresh", { method: "POST" }),
  getStatistics: () => request<Statistics>("/statistics"),
  getCleanupHistory: (limit = 100) =>
    request<CleanupHistoryEntry[]>(`/cleanup/history?limit=${limit}`),
  getScanFilterSettings: () => request<ScanFilterSettings>("/settings/scan-filter"),
  updateScanFilterSettings: (updates: Partial<{
    enabled_categories: string[];
    ignored_folder_names: string[];
    minimum_file_size_bytes: number;
  }>) =>
    request<ScanFilterSettings>("/settings/scan-filter", {
      method: "POST",
      body: JSON.stringify(updates),
    }),
  getVersionCleanupStatus: () => request<VersionCleanupStatus>("/version-cleanup"),
  setVersionCleanupFolder: (path: string, scan_interval_seconds = 120) =>
    request<VersionCleanupStatus>("/version-cleanup", {
      method: "POST",
      body: JSON.stringify({ path, scan_interval_seconds, automatic_cleanup: true, move_to_safe_vault: true }),
    }),
  removeVersionCleanupFolder: () => request<{ active: boolean }>("/version-cleanup", { method: "DELETE" }),
  scanVersionCleanupNow: () => request<Record<string, unknown>>("/version-cleanup/scan", { method: "POST" }),
  pauseVersionCleanup: () => request<VersionCleanupStatus>("/version-cleanup/pause", { method: "POST" }),
  resumeVersionCleanup: () => request<VersionCleanupStatus>("/version-cleanup/resume", { method: "POST" }),
  getVersionGroups: (status?: string) =>
    request<VersionGroup[]>(`/version-cleanup/groups${status ? `?status=${status}` : ""}`),
  getVersionGroupDetail: (id: number) =>
    request<{ group: VersionGroup; members: VersionGroupMember[]; suggestion: TieBreakSuggestion | null }>(`/version-cleanup/groups/${id}`),
  confirmVersionGroup: (id: number, kept_full_path: string) =>
    request<VersionCleanupStatus>(`/version-cleanup/groups/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ kept_full_path }),
    }),
  getDismissedRecommendations: () =>
    request<{ dismissed: { category: string; expires_at: string | null }[] }>("/recommendations/dismissed"),
  dismissRecommendation: (category: string, snooze_days?: number) =>
    request<{ dismissed: boolean; category: string }>("/recommendations/dismiss", {
      method: "POST",
      body: JSON.stringify({ category, snooze_days: snooze_days ?? null }),
    }),
  getFolderMonitorStatus: () => request<FolderMonitorStatus>("/folder-monitor"),
  setMonitoredFolder: (path: string, scan_interval_seconds = 120) =>
    request<FolderMonitorStatus>("/folder-monitor", {
      method: "POST",
      body: JSON.stringify({ path, scan_interval_seconds }),
    }),
  removeMonitoredFolder: () => request<{ active: boolean }>("/folder-monitor", { method: "DELETE" }),
  scanMonitoredFolderNow: () =>
    request<Record<string, unknown>>("/folder-monitor/scan", { method: "POST" }),
  pauseFolderMonitor: () => request<FolderMonitorStatus>("/folder-monitor/pause", { method: "POST" }),
  resumeFolderMonitor: () => request<FolderMonitorStatus>("/folder-monitor/resume", { method: "POST" }),
  getNotifications: (limit = 30) =>
    request<{ notifications: AppNotification[]; unread_count: number }>(`/notifications?limit=${limit}`),
  markAllNotificationsRead: () =>
    request<{ marked_all_read: boolean }>("/notifications/read-all", { method: "POST" }),
  getFolders: () => request<WatchedFolder[]>("/folders"),
  addFolder: (path: string, label?: string) =>
    request<WatchedFolder>("/folders", {
      method: "POST",
      body: JSON.stringify({ path, label: label ?? null, enabled: true }),
    }),
  removeFolder: (id: number) => request<{ removed: number }>(`/folders/${id}`, { method: "DELETE" }),
  scanFolder: (id: number) =>
    request<Record<string, unknown>>(`/folders/${id}/scan`, { method: "POST" }),
  getDuplicateGroups: (status?: string) =>
    request<DuplicateGroup[]>(`/duplicates${status ? `?status=${status}` : ""}`),
  getDuplicateGroup: (id: number) =>
    request<{ group: DuplicateGroup; members: DuplicateMember[] }>(`/duplicates/${id}`),
  triggerScan: (scan_type: "full" | "incremental" = "full") =>
    request<Record<string, number>>("/scan", {
      method: "POST",
      body: JSON.stringify({ scan_type }),
    }),
  cleanupGroups: (group_ids?: number[]) =>
    request<{ moved: unknown[]; skipped: unknown[]; bytes_reclaimed: number }>("/cleanup", {
      method: "POST",
      body: JSON.stringify({ group_ids: group_ids ?? null }),
    }),
  restore: (cleanup_id?: number) =>
    request<Record<string, unknown>>("/restore", {
      method: "POST",
      body: JSON.stringify({ cleanup_id: cleanup_id ?? null }),
    }),
  getVault: () => request<VaultEntry[]>("/cleanup/vault"),
  ask: (question: string, group_id?: number) =>
    request<{ question: string; answer: string; data: Record<string, unknown> }>(
      `/statistics/ask?question=${encodeURIComponent(question)}${group_id ? `&group_id=${group_id}` : ""}`
    ),
};

export interface ProxyKey {
  id: number;
  maskedApiKey: string;
  display: string;
  remainingUses: number;
  reservedUses: number;
  status: 'ready' | 'waiting' | 'error' | 'starting';
  lastError: string | null;
  ipExpiresAt: string | null;
  endpoint: {
    host: string;
    port: number;
    username: string | null;
    password: string | null;
    display: string;
    expiresAt: string | null;
  } | null;
  currentProxy: string;
}

export interface ProxyConfig {
  kiotAuthToken: string;
  apiKeys: string[];
  getNewProxyUrl: string;
  getCurrentProxyUrl: string;
  usesPerProxy: number;
  timeout: number;
  retryCount: number;
}

export interface ProxyStatusData {
  id: number;
  apiKey: string;
  maskedApiKey: string;
  currentProxy: string;
  remainingUses: number;
  reservedUses: number;
  status: 'ready' | 'waiting' | 'error' | 'starting' | 'Đang chạy';
  ipExpiresAt: string | null;
  lastError: string | null;
  display: string;
  endpoint: {
    host: string;
    port: number;
    display: string;
    expiresAt: string | null;
  } | null;
}

export interface SettingsData {
  interactionThreads: number;
  postsPerUid: number;
  delayMinSeconds: number;
  delayMaxSeconds: number;
  delayEveryRounds: number;
  usesPerProxy: number;
  proxyCheckInterval: number;
  getNewUrlTemplate: string;
  getCurrentUrlTemplate: string;
  kiotAuthTokenMasked: string;
}

export interface ProfileRow {
  uid: string;
  token: string;
  tokenStatus: StatusValue;
  taskCount: number;
  lastError: string | null;
}

export interface TaskStats {
  total: number;
  processed: number;
  success: number;
  failed: number;
  waitingProxy: number;
}

export type LogLevel = 'info' | 'success' | 'error' | 'warning';

export interface LogEntry {
  index: number;
  uid: string;
  link: string;
  action: string;
  proxy: string;
  status: string;
  error: string;
  timestamp: number;
}

export type ProfileTokenStatus = 'live' | 'die' | 'checkpoint' | 'unknown';
export type LogStatusValue = 'Thành công' | 'Thất bại' | 'Đang chạy' | 'Đang chờ proxy' | 'Đã dừng' | string;
export type ProxyRunStatus = 'Đang chạy' | 'Đang chờ' | 'Đang khởi động';

export type StatusValue = ProfileTokenStatus | LogStatusValue;
export type ProxyStatusValue = 'ready' | 'waiting' | 'error' | 'starting' | ProxyRunStatus;

export interface AppSettings {
  kiotAuthToken: string;
  kiotAuthTokenMasked: string;
  proxyApiKeys: string;
  getNewProxyUrl: string;
  getCurrentProxyUrl: string;
  usesPerProxy: number;
  checkInterval: number;
  interactionThreads: number;
  postsPerUid: number;
  delayMin: number;
  delayMax: number;
  delayEveryRounds: number;
}

export interface TaskConfig {
  threads: number;
  uids: string;
  links: string;
  content: string;
  imagePath: string;
  delayMin: number;
  delayMax: number;
  delayEveryRounds: number;
  action: 'edit' | 'delete' | 'new_comment';
}

// ─── Rental (Đăng trọ tự động) ──────────────────────────────────────────────

export interface GoogleSheetConnection {
  id: string;
  name: string;
  spreadsheet_id: string;
  spreadsheet_url: string;
  sheet_name: string;
  service_account_email: string;
  poll_interval_seconds: number;
  timezone: string;
  status: string;
  last_synced_at: string | null;
  last_error: string | null;
  created_at: string | null;
}

export interface FacebookPostTarget {
  id: string;
  type: 'page' | 'personal' | 'group';
  name: string;
  status: string;
  available: boolean;
  reason?: string;
  page_id?: string;
  group_id?: string;
  url?: string;
  uid?: string;
}

export type SheetScheduleMode = 'NOW' | 'EXACT' | 'AUTO';

export interface SheetCampaign {
  id: string;
  connection_id: string;
  name: string;
  default_targets: string[];
  default_schedule_mode: SheetScheduleMode;
  schedule_slots: string[];
  active_weekdays: number[];
  timezone: string;
  max_posts_per_day: number;
  min_post_gap_seconds: number;
  late_policy: 'publish_now' | 'miss';
  max_retries: number;
  enabled: boolean;
  status: string;
  last_synced_at: string | null;
  last_error: string | null;
}

export interface SheetCampaignInput {
  connection_id: string;
  name: string;
  default_targets: string[];
  default_schedule_mode: SheetScheduleMode;
  schedule_slots: string[];
  active_weekdays: number[];
  timezone: string;
  max_posts_per_day: number;
  min_post_gap_seconds: number;
  late_policy: 'publish_now' | 'miss';
  max_retries: number;
  enabled: boolean;
}

export interface SheetSourceItem {
  id: string;
  campaign_id: string;
  external_id: string;
  sheet_row_number: number;
  content: string;
  media_urls: string[];
  targets: string[];
  schedule_mode: string;
  scheduled_at: string | null;
  source_version: number;
  status: string;
  validation_error: string | null;
  queued_at: string | null;
  completed_at: string | null;
}

export interface PublicationJob {
  id: string;
  source_item_id: string | null;
  source_version: number;
  target_type: string;
  target_id: string;
  status: string;
  attempt_count: number;
  scheduled_at: string;
  facebook_url: string | null;
  error: string | null;
}

export interface PublicationHealth {
  publication_jobs: Record<string, number>;
  stale_jobs: number;
  sheet_campaign_errors: number;
  rental_config_errors: number;
}

export interface RentalConfig {
  id: string;
  name: string;
  source_type: string;
  province_code: string;
  province_name: string;
  district_code: string;
  district_name: string;
  ward_code: string | null;
  ward_name: string | null;
  auto_post: boolean;
  post_spacing_seconds: number;
  post_delay_seconds: number;
  caption_template: string;
  contact_phone: string;
  group_match_level: string;
  poll_interval_seconds: number;
  timezone: string;
  google_sheet_connection_id: string | null;
  status: string;
  last_synced_at: string | null;
  last_sync_attempt_at: string | null;
  last_post_at: string | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface RentalRoom {
  id: string;
  config_id: string;
  external_room_id: string;
  title: string;
  price: string;
  area_text: string;
  address: string;
  district: string | null;
  ward: string | null;
  description: string;
  images: string[];
  caption: string;
  matched_group_ids: string[];
  status: string;
  post_urls: Record<string, string>;
  posted_at: string | null;
  retry_count: number;
  error: string | null;
  source_status: string;
  last_seen_at: string | null;
  media_paths: string[];
  mirror_status: string | null;
  mirror_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface RentalPublicationJob {
  id: string;
  rental_room_id: string;
  target_type: string;
  target_id: string;
  target_external_id: string | null;
  status: string;
  attempt_count: number;
  max_attempts: number;
  scheduled_at: string | null;
  next_retry_at: string | null;
  facebook_url: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RentalConfigInput {
  name: string;
  credentials?: { username: string; password: string };
  province_code: string;
  province_name: string;
  district_code: string;
  district_name: string;
  ward_code?: string | null;
  ward_name?: string | null;
  caption_template?: string;
  contact_phone?: string;
  post_spacing_seconds?: number;
  post_delay_seconds?: number;
  poll_interval_seconds?: number;
  auto_post?: boolean;
  google_sheet_connection_id?: string | null;
  timezone?: string;
}

export function maskToken(token: string): string {
  if (token.length <= 4) return '****';
  if (token.length <= 8) return `${token.slice(0, 2)}****${token.slice(-2)}`;
  return `${token.slice(0, 4)}****${token.slice(-4)}`;
}

export function statusToVariant(status: string): 'success' | 'warning' | 'danger' | 'info' | 'default' {
  const s = status.toLowerCase();
  if (s === 'live' || s === 'thành công' || s === 'thanh cong' || s === 'ready') return 'success';
  if (s === 'checkpoint' || s === 'token out' || s === 'thất bại' || s === 'that bai' || s === 'error') return 'danger';
  if (s === 'đang chờ proxy' || s === 'dang cho proxy' || s === 'waiting') return 'warning';
  if (s === 'đang chạy' || s === 'dang chay') return 'info';
  return 'default';
}

export function logLevelFromStatus(status: string): LogLevel {
  const s = status.toLowerCase();
  if (s.includes('thành công') || s.includes('thanh cong') || s === 'live' || s === 'ready') return 'success';
  if (s.includes('thất bại') || s.includes('that bai') || s.includes('checkpoint') || s.includes('token out') || s === 'error') return 'error';
  if (s.includes('đang chờ') || s.includes('dang cho') || s.includes('waiting')) return 'warning';
  if (s.includes('đang chạy') || s.includes('dang chay')) return 'info';
  return 'info';
}

export function taskStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    'cho chay': 'Chờ chạy',
    'dang chay': 'Đang chạy',
    'dang cho proxy': 'Đang chờ proxy',
    'thanh cong': 'Thành công',
    'that bai': 'Thất bại',
    'dung': 'Dừng',
    'dung profile': 'Dừng hồ sơ',
    'cho duyet': 'Chờ duyệt',
  };
  return labels[status.trim().toLowerCase()] ?? status;
}

// Backward-compat alias (used by existing proxy page/Grid)
export type ProxyKeyState = ProxyStatusData;

export function proxyStatusLabel(status: string): string {
  const s = status.toLowerCase();
  if (s === 'ready' || s === 'live') return 'Sẵn sàng';
  if (s === 'starting') return 'Đang khởi động';
  if (s === 'Đang chạy') return 'Đang chạy';
  if (s === 'waiting') return 'Đang chờ';
  if (s === 'error') return 'Lỗi';
  return status;
}

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

export function maskToken(token: string): string {
  if (token.length <= 4) return '****';
  if (token.length <= 8) return `${token.slice(0, 2)}****${token.slice(-2)}`;
  return `${token.slice(0, 4)}****${token.slice(-4)}`;
}

export function statusToVariant(status: string): 'success' | 'warning' | 'danger' | 'info' | 'default' {
  const s = status.toLowerCase();
  if (s === 'live' || s === 'thành công' || s === 'ready') return 'success';
  if (s === 'checkpoint' || s === 'token out' || s === 'thất bại' || s === 'error') return 'danger';
  if (s === 'đang chờ proxy' || s === 'waiting') return 'warning';
  if (s === 'đang chạy' || s === 'Đang chạy') return 'info';
  return 'default';
}

export function logLevelFromStatus(status: string): LogLevel {
  const s = status.toLowerCase();
  if (s.includes('thành công') || s === 'live' || s === 'ready') return 'success';
  if (s.includes('thất bại') || s.includes('checkpoint') || s.includes('token out') || s === 'error') return 'error';
  if (s.includes('đang chờ') || s.includes('waiting')) return 'warning';
  if (s.includes('đang chạy') || s.includes('đang chờ proxy')) return 'info';
  return 'info';
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

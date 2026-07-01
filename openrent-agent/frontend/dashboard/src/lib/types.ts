export type LeadStatus =
  | "INITIAL_MESSAGE_SENT"
  | "NEW_REPLY"
  | "AI_REPLIED"
  | "PHONE_ACQUIRED"
  | "AI_FAILED"
  | "REPLY_DISABLED"
  | "AGENT_SKIPPED"
  | "SKIPPED"
  | "DUPLICATE_LEAD"
  | "VIEWING_CANCELLED"
  | "INACTIVE_NO_REPLY"
  | "SHORT_TERM_PROPERTY"
  | "CLOSED"
  | "WHATSAPP_SHARED";

export type ConversationStage =
  | "NEW_LEAD"
  | "VIEWING_DISCUSSION"
  | "VIEWING_BOOKED"
  | "PRE_VIEWING"
  | "CONTACT_REQUESTED"
  | "HANDOFF_COMPLETE"
  | "VIEWING_CANCELLED"
  | "SHORT_TERM_PROPERTY"
  | "CLOSED";

export type SessionStatus =
  | "active"
  | "expired"
  | "logging_in"
  | "login_failed"
  | "captcha_suspected"
  | "error";
export type WorkerStatus =
  | "queued"
  | "running"
  | "stopping"
  | "paused"
  | "idle"
  | "completed"
  | "stopped"
  | "retrying"
  | "proxy_error"
  | "login_error"
  | "error";
export type ProxyStatus = "ok" | "degraded" | "down" | "not_configured" | "unknown";
export type ProxyType = "static" | "rotating";

export interface Proxy {
  id: string;
  name: string;
  host: string;
  port: number;
  username?: string;
  isActive: boolean;
  proxyType: ProxyType;
  createdAt: string;
  accountCount: number;
}

export interface Account {
  id: string;
  email: string;
  sessionFile?: string;
  initialMessage?: string;
  active: boolean;
  proxyId?: string;
  proxyName?: string;
  sessionStatus: SessionStatus;
  workerStatus: WorkerStatus;
  dailyMessageLimit: number;
  messagesSentToday: number;
  proxyServer?: string;
  proxyUsername?: string;
  proxyPassword?: string;
  proxyStatus: ProxyStatus;
  aiEnabled: boolean;
  outreachEnabled: boolean;
  lastLoginAt: string;
  personaName?: string;
  personaPartnerName?: string;
  personaJob?: string;
  personaPartnerJob?: string;
  homeCity?: string;
  mobileNumber?: string;
  phoneFetchingType?: string;
  messageStrategy?: string;
  escalationBehavior?: string;
  conversationGoal?: string;
  conversationStyle?: string;
  currentWorkerPhase?: string;
  workerJobId?: string;
  workerStartedAt?: string;
  workerLastCompletedAt?: string;
  lastRunAt?: string;
  cooldownUntil?: string;
  nextRunAt?: string;
  workerLastHeartbeat?: string;
  workerLastError?: string;
  sessionLastChecked?: string;
  sessionLastError?: string;
  sessionAuthFailures: number;
  sessionCaptchaTriggers: number;
  proxyIp?: string;
  proxyLatency?: number;
  proxyLastChecked?: string;
  proxyLastError?: string;
  proxyFailures: number;
  retryCount: number;
  retryLimit: number;
  retryReason?: string;
  retryNextAt?: string;
  permanentlyFailed: boolean;
}

export interface SearchProfile {
  id: string;
  accountId: string;
  accountEmail?: string;
  location: string;
  area: number;
  priceMin: number;
  priceMax: number;
  bedroomsMin: number;
  bedroomsMax: number;
  petsAllowed: boolean;
  active: boolean;
}

export interface Message {
  id: string;
  threadId: string;
  sender: "landlord" | "ai" | "operator";
  text: string;
  createdAt: string;
}

export interface Lead {
  id: string;
  conversationId?: string;
  listingPk?: string;
  listingId?: string;
  landlordId?: string;
  accountId: string;
  searchProfileId: string;
  propertyLink: string;
  messageLink?: string;
  propertyTitle: string;
  propertyAddress?: string;
  rent: number;
  priceMin?: number;
  priceMax?: number;
  bedrooms: number;
  bathrooms?: number;
  bedroomsMin?: number;
  bedroomsMax?: number;
  area: string;
  threadId: string;
  landlordName: string;
  metadataCapturedAt?: string;
  status: LeadStatus;
  conversationStage: ConversationStage;
  phoneNumber?: string;
  viewingDatetime?: string;
  viewingConfirmed: boolean;
  viewingConfirmationSource?: "banner" | "ai";
  viewingCancelled: boolean;
  cancelRequired: boolean;
  cancellationSentAt?: string;
  phoneRequestedAt?: string;
  phoneFoundAt?: string;
  phoneNumberSharedAt?: string;
  ourNumberSharedAt?: string;
  landlordAskedPhoneAt?: string;
  landlordAttitude?: string;
  conversationStyle?: string;
  lastStageChange?: string;
  personaName?: string;
  personaPartnerName?: string;
  personaJob?: string;
  personaPartnerJob?: string;
  homeCity?: string;
  mobileNumber?: string;
  phoneFetchingType?: string;
  messageStrategy?: string;
  escalationBehavior?: string;
  conversationGoal?: string;
  lastLandlordMessage?: string;
  lastAiReply?: string;
  initialMessageSentAt: string;
  lastUpdatedAt: string;
}

export interface MetricsSeriesPoint {
  date: string;
  leads: number;
  replies: number;
  phones: number;
  failures: number;
}

export interface AutomationMetrics {
  total_leads: number;
  total_phones: number;
  phones_today: number;
  new_outreach_today: number;
  daily_phone_target: number;
  active_accounts: number;
  our_whatsapp_shared: number;
  series: MetricsSeriesPoint[];
}

export interface LogEntry {
  id: string;
  level: "info" | "warn" | "error";
  category: "worker" | "ai" | "login" | "retry" | "agent_skip" | "whatsapp";
  accountId?: string;
  message: string;
  context?: Record<string, unknown>;
  createdAt: string;
}

export interface HealthStatus {
  status: string;
}

export interface ProxyTestResult {
  account_id: number;
  status: ProxyStatus | "failed";
  ok: boolean;
  detail?: string;
  healthy?: boolean;
  ip?: string;
  latency?: number;
  status_code?: number;
  error?: string;
}

export interface ProxyHealthRow {
  account_id: number;
  account_email: string;
  proxy_server?: string;
  proxy_status: ProxyStatus;
  proxy_ip?: string;
  proxy_latency?: number;
  proxy_last_checked?: string;
  proxy_last_error?: string;
  proxy_failures: number;
}

export interface WorkerSummary {
  id: string;
  account_id: number;
  account_email: string;
  status: WorkerStatus;
  phase: string;
  last_heartbeat?: string;
  started_at?: string;
  last_completed_at?: string;
  job_id?: string;
  retry_count: number;
  retry_next_at?: string;
  last_error?: string;
  active: boolean;
  stale: boolean;
}

export interface WorkersStatus {
  total: number;
  running: number;
  paused: number;
  errored: number;
  queue: string;
  active_tasks: number;
}

export interface CapacityStatus {
  accounts_running: number;
  accounts_queued: number;
  accounts_in_flight: number;
  healthy_proxies: number;
  failed_proxies: number;
  total_proxies: number;
  max_parallel_workers: number;
  worker_capacity: number;
}

export interface Location {
  id: number;
  name: string;
  termValue: string;
  active: boolean;
  createdAt?: string;
}

export interface FailedAccount {
  id: string;
  email: string;
  proxyName?: string;
  proxyServer?: string;
  failed: boolean;
  failedAt?: string;
  failureReason?: string;
  lastRunAt?: string;
  messagesSet?: number;
  repliesReceived?: number;
  active: boolean;
}

export interface DeletedAccount {
  id: string;
  email: string;
  proxyName?: string;
  proxyServer?: string;
  deletedAt: string;
  messagesSent?: number;
  phonesCaptured?: number;
  createdAt?: string;
}

export type WhatsAppContactStatus =
  | "NEW_CONTACT"
  | "AWAITING_NAME"
  | "AWAITING_PROPERTY"
  | "PHONE_ACQUIRED";

export interface WhatsAppContact {
  id: number;
  phone_number: string;
  name?: string;
  landlord_id?: number;
  listing_id?: number;
  property_address?: string;
  thread_id?: string;
  first_message?: string;
  last_message?: string;
  last_received_at?: string;
  status: WhatsAppContactStatus;
  confidence?: number;
  is_manual?: boolean;
  reply_scheduled_at?: string;
  created_at?: string;
  updated_at?: string;
}

export interface AutomationSettings {
  openai_model: string;
  auto_send: boolean;
  worker_concurrency: number;
  min_delay_seconds: number;
  max_delay_seconds: number;
  retry_limit: number;
  daily_message_limit: number;
  backend_status: string;
  redis_status: string;
  api_status: string;
}

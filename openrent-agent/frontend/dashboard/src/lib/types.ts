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
  | "CLOSED";

export type ConversationStage =
  | "NEW_LEAD"
  | "VIEWING_DISCUSSION"
  | "VIEWING_BOOKED"
  | "PRE_VIEWING"
  | "CONTACT_REQUESTED"
  | "VIEWING_CANCELLED"
  | "CLOSED";

export type SessionStatus = "active" | "expired" | "logging_in" | "error";
export type WorkerStatus = "running" | "stopping" | "paused" | "idle" | "error";
export type ProxyStatus = "ok" | "degraded" | "down" | "not_configured" | "unknown";

export interface Account {
  id: string;
  email: string;
  sessionFile?: string;
  initialMessage?: string;
  active: boolean;
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
  workerLastHeartbeat?: string;
  workerLastError?: string;
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
  accountId: string;
  searchProfileId: string;
  propertyLink: string;
  propertyTitle: string;
  rent: number;
  priceMin?: number;
  priceMax?: number;
  bedrooms: number;
  bedroomsMin?: number;
  bedroomsMax?: number;
  area: string;
  threadId: string;
  landlordName: string;
  status: LeadStatus;
  conversationStage: ConversationStage;
  phoneNumber?: string;
  viewingDatetime?: string;
  viewingConfirmed: boolean;
  viewingCancelled: boolean;
  cancelRequired: boolean;
  cancellationSentAt?: string;
  phoneRequestedAt?: string;
  phoneFoundAt?: string;
  phoneNumberSharedAt?: string;
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
  daily_phone_target: number;
  active_accounts: number;
  series: MetricsSeriesPoint[];
}

export interface LogEntry {
  id: string;
  level: "info" | "warn" | "error";
  category: "worker" | "ai" | "login" | "retry" | "agent_skip";
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
}

export interface WorkerSummary {
  id: string;
  account_id: number;
  account_email: string;
  status: WorkerStatus;
  phase: string;
  last_heartbeat?: string;
  last_error?: string;
  active: boolean;
}

export interface WorkersStatus {
  total: number;
  running: number;
  paused: number;
  errored: number;
  queue: string;
  active_tasks: number;
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

import { del, get, patch, post } from "./client";
import type {
  Account,
  AutomationMetrics,
  AutomationSettings,
  ConversationStage,
  HealthStatus,
  Lead,
  LeadStatus,
  LogEntry,
  Message,
  ProxyHealthRow,
  ProxyTestResult,
  SearchProfile,
  SessionStatus,
  ProxyStatus,
  WorkerStatus,
  WorkersStatus,
  WorkerSummary,
} from "@/lib/types";

const VALID_LEAD_STATUSES: LeadStatus[] = [
  "INITIAL_MESSAGE_SENT",
  "NEW_REPLY",
  "AI_REPLIED",
  "PHONE_ACQUIRED",
  "AI_FAILED",
  "REPLY_DISABLED",
  "AGENT_SKIPPED",
  "SKIPPED",
  "DUPLICATE_LEAD",
  "VIEWING_CANCELLED",
  "CLOSED",
];

const VALID_STAGES: ConversationStage[] = [
  "NEW_LEAD",
  "VIEWING_DISCUSSION",
  "VIEWING_BOOKED",
  "PRE_VIEWING",
  "CONTACT_REQUESTED",
  "VIEWING_CANCELLED",
  "CLOSED",
];

type BackendAccount = {
  id: number | string;
  email: string;
  session_file?: string;
  initial_message?: string;
  proxy_server?: string;
  proxy_username?: string;
  proxy_password?: string;
  daily_limit?: number;
  messages_sent_today?: number;
  active?: boolean;
  created_at?: string;
  persona_name?: string;
  persona_partner_name?: string;
  persona_job?: string;
  persona_partner_job?: string;
  home_city?: string;
  mobile_number?: string;
  phone_fetching_type?: string;
  message_strategy?: string;
  escalation_behavior?: string;
  conversation_goal?: string;
  conversation_style?: string;
  worker_status?: string;
  worker_job_id?: string;
  worker_started_at?: string;
  worker_last_heartbeat?: string;
  worker_error?: string;
  worker_last_error?: string;
  worker_last_completed_at?: string;
  current_worker_phase?: string;
  last_login_at?: string;
  session_status?: string;
  session_last_checked?: string;
  session_last_error?: string;
  session_auth_failures?: number;
  session_captcha_triggers?: number;
  proxy_status?: string;
  proxy_ip?: string;
  proxy_latency?: number;
  proxy_last_checked?: string;
  proxy_last_error?: string;
  proxy_failures?: number;
  retry_count?: number;
  retry_limit?: number;
  retry_reason?: string;
  retry_next_at?: string;
  permanently_failed?: boolean;
};

type BackendLead = {
  thread_id?: string;
  listing_id?: string;
  property_url?: string;
  account_id?: number | string;
  account_email?: string;
  search_profile_id?: number | string;
  location?: string;
  price_min?: number;
  price_max?: number;
  bedrooms_min?: number;
  bedrooms_max?: number;
  area?: number;
  pets_allowed?: boolean;
  status?: string;
  conversation_stage?: string;
  viewing_datetime?: string;
  viewing_confirmed?: boolean;
  viewing_cancelled?: boolean;
  cancel_required?: boolean;
  cancellation_sent_at?: string;
  phone_requested_at?: string;
  phone_found_at?: string;
  phone_number_shared_at?: string;
  landlord_asked_phone_at?: string;
  landlord_attitude?: string;
  conversation_style?: string;
  last_stage_change?: string;
  phone?: string;
  phone_number?: string;
  persona_name?: string;
  persona_partner_name?: string;
  persona_job?: string;
  persona_partner_job?: string;
  home_city?: string;
  mobile_number?: string;
  phone_fetching_type?: string;
  message_strategy?: string;
  escalation_behavior?: string;
  conversation_goal?: string;
  last_processed_message?: string;
  last_ai_reply?: string;
  created_at?: string;
  last_message_at?: string;
};

type BackendMessage = {
  id: number | string;
  thread_id?: string;
  direction?: string;
  content?: string;
  created_at?: string;
};

type BackendSearchProfile = {
  id: number | string;
  account_id: number | string;
  account_email?: string;
  location: string;
  price_min?: number;
  price_max?: number;
  bedrooms_min?: number;
  bedrooms_max?: number;
  area?: number;
  pets_allowed?: boolean;
  active?: boolean;
};

function asDate(value?: string): string {
  return value || new Date().toISOString();
}

function asLeadStatus(value?: string): LeadStatus {
  return VALID_LEAD_STATUSES.includes(value as LeadStatus) ? (value as LeadStatus) : "NEW_REPLY";
}

function asStage(value?: string): ConversationStage {
  return VALID_STAGES.includes(value as ConversationStage)
    ? (value as ConversationStage)
    : "NEW_LEAD";
}

function asWorkerStatus(value?: string, active?: boolean): WorkerStatus {
  if (
    value === "queued" ||
    value === "running" ||
    value === "stopping" ||
    value === "completed" ||
    value === "stopped" ||
    value === "retrying" ||
    value === "proxy_error" ||
    value === "login_error" ||
    value === "paused" ||
    value === "idle" ||
    value === "error"
  ) {
    return value;
  }
  return active === false ? "paused" : "idle";
}

function asSessionStatus(value?: string, workerStatus?: WorkerStatus): SessionStatus {
  if (
    value === "active" ||
    value === "expired" ||
    value === "logging_in" ||
    value === "login_failed" ||
    value === "captcha_suspected" ||
    value === "error"
  ) {
    return value;
  }
  if (workerStatus === "login_error") return "login_failed";
  return "expired";
}

function asProxyStatus(value?: string, hasProxy?: boolean): ProxyStatus {
  if (
    value === "ok" ||
    value === "degraded" ||
    value === "down" ||
    value === "not_configured" ||
    value === "unknown"
  ) {
    return value;
  }
  return hasProxy ? "unknown" : "not_configured";
}

function mapAccount(account: BackendAccount): Account {
  const active = account.active ?? true;
  const workerStatus = asWorkerStatus(account.worker_status, active);
  const hasProxy = Boolean(account.proxy_server);

  return {
    id: String(account.id),
    email: account.email,
    sessionFile: account.session_file,
    initialMessage: account.initial_message,
    active,
    sessionStatus: asSessionStatus(account.session_status, workerStatus),
    workerStatus,
    dailyMessageLimit: account.daily_limit ?? 0,
    messagesSentToday: account.messages_sent_today ?? 0,
    proxyServer: account.proxy_server,
    proxyUsername: account.proxy_username,
    proxyPassword: account.proxy_password,
    proxyStatus: asProxyStatus(account.proxy_status, hasProxy),
    aiEnabled: active,
    outreachEnabled: active,
    lastLoginAt: asDate(account.last_login_at || account.created_at),
    personaName: account.persona_name,
    personaPartnerName: account.persona_partner_name,
    personaJob: account.persona_job,
    personaPartnerJob: account.persona_partner_job,
    homeCity: account.home_city,
    mobileNumber: account.mobile_number,
    phoneFetchingType: account.phone_fetching_type,
    messageStrategy: account.message_strategy,
    escalationBehavior: account.escalation_behavior,
    conversationGoal: account.conversation_goal,
    conversationStyle: account.conversation_style,
    currentWorkerPhase: account.current_worker_phase,
    workerJobId: account.worker_job_id,
    workerStartedAt: account.worker_started_at,
    workerLastCompletedAt: account.worker_last_completed_at,
    workerLastHeartbeat: account.worker_last_heartbeat,
    workerLastError: account.worker_last_error || account.worker_error,
    sessionLastChecked: account.session_last_checked,
    sessionLastError: account.session_last_error,
    sessionAuthFailures: account.session_auth_failures ?? 0,
    sessionCaptchaTriggers: account.session_captcha_triggers ?? 0,
    proxyIp: account.proxy_ip,
    proxyLatency: account.proxy_latency,
    proxyLastChecked: account.proxy_last_checked,
    proxyLastError: account.proxy_last_error,
    proxyFailures: account.proxy_failures ?? 0,
    retryCount: account.retry_count ?? 0,
    retryLimit: account.retry_limit ?? 3,
    retryReason: account.retry_reason,
    retryNextAt: account.retry_next_at,
    permanentlyFailed: account.permanently_failed ?? false,
  };
}

function mapLead(lead: BackendLead): Lead {
  const id = lead.thread_id || lead.listing_id || crypto.randomUUID();
  const propertyUrl = lead.property_url || "";
  const listingName = lead.listing_id ? `Listing ${lead.listing_id}` : "OpenRent property";
  const bedroomsMin = lead.bedrooms_min ?? 0;
  const bedroomsMax = lead.bedrooms_max ?? bedroomsMin;

  return {
    id,
    accountId: lead.account_id ? String(lead.account_id) : "unknown",
    searchProfileId: lead.search_profile_id ? String(lead.search_profile_id) : "unknown",
    propertyLink: propertyUrl,
    propertyTitle: listingName,
    rent: 0,
    priceMin: lead.price_min,
    priceMax: lead.price_max,
    bedrooms: bedroomsMax,
    bedroomsMin,
    bedroomsMax,
    area: lead.location || "OpenRent",
    threadId: lead.thread_id || id,
    landlordName: lead.account_email || "OpenRent lead",
    status: asLeadStatus(lead.status),
    conversationStage: asStage(lead.conversation_stage),
    phoneNumber: lead.phone_number || lead.phone || undefined,
    viewingDatetime: lead.viewing_datetime,
    viewingConfirmed: lead.viewing_confirmed ?? false,
    viewingCancelled: lead.viewing_cancelled ?? false,
    cancelRequired: lead.cancel_required ?? false,
    cancellationSentAt: lead.cancellation_sent_at,
    phoneRequestedAt: lead.phone_requested_at,
    phoneFoundAt: lead.phone_found_at,
    phoneNumberSharedAt: lead.phone_number_shared_at,
    landlordAskedPhoneAt: lead.landlord_asked_phone_at,
    landlordAttitude: lead.landlord_attitude,
    conversationStyle: lead.conversation_style,
    lastStageChange: lead.last_stage_change,
    personaName: lead.persona_name,
    personaPartnerName: lead.persona_partner_name,
    personaJob: lead.persona_job,
    personaPartnerJob: lead.persona_partner_job,
    homeCity: lead.home_city,
    mobileNumber: lead.mobile_number,
    phoneFetchingType: lead.phone_fetching_type,
    messageStrategy: lead.message_strategy,
    escalationBehavior: lead.escalation_behavior,
    conversationGoal: lead.conversation_goal,
    lastLandlordMessage: lead.last_processed_message || undefined,
    lastAiReply: lead.last_ai_reply || undefined,
    initialMessageSentAt: asDate(lead.created_at),
    lastUpdatedAt: asDate(lead.last_message_at || lead.created_at),
  };
}

function mapSearchProfile(profile: BackendSearchProfile): SearchProfile {
  return {
    id: String(profile.id),
    accountId: String(profile.account_id),
    accountEmail: profile.account_email,
    location: profile.location,
    area: profile.area ?? 0,
    priceMin: profile.price_min ?? 0,
    priceMax: profile.price_max ?? 0,
    bedroomsMin: profile.bedrooms_min ?? 0,
    bedroomsMax: profile.bedrooms_max ?? 0,
    petsAllowed: profile.pets_allowed ?? false,
    active: profile.active ?? true,
  };
}

function searchProfilePayload(profile: Partial<SearchProfile>) {
  return {
    account_id: Number(profile.accountId),
    location: profile.location || "Unspecified",
    price_min: profile.priceMin ?? 0,
    price_max: profile.priceMax ?? 0,
    bedrooms_min: profile.bedroomsMin ?? 0,
    bedrooms_max: profile.bedroomsMax ?? 0,
    area: profile.area ?? 0,
    pets_allowed: profile.petsAllowed ?? false,
    active: profile.active ?? true,
  };
}

function accountPayload(account: Partial<Account> & { password?: string }) {
  const payload: Record<string, unknown> = {};
  if (account.email !== undefined) payload.email = account.email;
  if (account.password) payload.password = account.password;
  if (account.sessionFile !== undefined) payload.session_file = account.sessionFile;
  if (account.initialMessage !== undefined) payload.initial_message = account.initialMessage;
  if (account.proxyServer !== undefined) payload.proxy_server = account.proxyServer || "";
  if (account.proxyUsername !== undefined) payload.proxy_username = account.proxyUsername || "";
  if (account.proxyPassword !== undefined) payload.proxy_password = account.proxyPassword || "";
  if (account.dailyMessageLimit !== undefined) payload.daily_limit = account.dailyMessageLimit;
  if (account.active !== undefined) payload.active = account.active;
  if (account.mobileNumber !== undefined) payload.mobile_number = account.mobileNumber || "";
  if (account.phoneFetchingType !== undefined)
    payload.phone_fetching_type = account.phoneFetchingType || "";
  if (account.messageStrategy !== undefined)
    payload.message_strategy = account.messageStrategy || "";
  if (account.escalationBehavior !== undefined)
    payload.escalation_behavior = account.escalationBehavior || "";
  if (account.conversationGoal !== undefined)
    payload.conversation_goal = account.conversationGoal || "";
  if (account.conversationStyle !== undefined)
    payload.conversation_style = account.conversationStyle || "";
  return payload;
}

export function getHealth(): Promise<HealthStatus> {
  return get<HealthStatus>("/health");
}

export async function getLeads(status?: LeadStatus | "all"): Promise<Lead[]> {
  const query = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : "";
  const leads = await get<BackendLead[]>(`/leads${query}`);
  return leads.map(mapLead);
}

export async function getLead(threadId: string): Promise<Lead | undefined> {
  const leads = await getLeads();
  return leads.find((lead) => lead.id === threadId || lead.threadId === threadId);
}

export async function getConversationMessages(threadId: string): Promise<Message[]> {
  const rows = await get<BackendMessage[]>(
    `/conversations/${encodeURIComponent(threadId)}/messages`,
  );

  return rows.map((row) => ({
    id: String(row.id),
    threadId: row.thread_id || threadId,
    sender: row.direction === "inbound" ? "landlord" : "operator",
    text: row.content || "",
    createdAt: asDate(row.created_at),
  }));
}

export async function getAccounts(): Promise<Account[]> {
  const accounts = await get<BackendAccount[]>("/accounts");
  return accounts.map(mapAccount);
}

export async function createAccount(
  account: Partial<Account> & { password?: string },
): Promise<Account> {
  const created = await post<BackendAccount>("/accounts", accountPayload(account));
  return mapAccount(created);
}

export async function updateAccount(
  account: Partial<Account> & { id: string; password?: string },
): Promise<Account> {
  const updated = await patch<BackendAccount>(`/accounts/${account.id}`, accountPayload(account));
  return mapAccount(updated);
}

export async function deleteAccount(
  accountId: string,
): Promise<{ account_id: number; deleted: boolean }> {
  return del(`/accounts/${accountId}`);
}

export async function controlAccountWorker(input: {
  accountId: string;
  action: "start" | "stop" | "pause" | "resume";
}): Promise<Account> {
  const updated = await post<BackendAccount>(`/accounts/${input.accountId}/${input.action}`);
  return mapAccount(updated);
}

export async function testAccountProxy(accountId: string): Promise<ProxyTestResult> {
  return post<ProxyTestResult>(`/accounts/${accountId}/check-proxy`);
}

export function getProxyHealth(): Promise<ProxyHealthRow[]> {
  return get<ProxyHealthRow[]>("/proxy-health");
}

export async function refreshAccountSession(accountId: string): Promise<Account> {
  const updated = await post<BackendAccount>(`/accounts/${accountId}/refresh-session`);
  return mapAccount(updated);
}

export async function invalidateAccountSession(accountId: string): Promise<Account> {
  const updated = await post<BackendAccount>(`/accounts/${accountId}/invalidate-session`);
  return mapAccount(updated);
}

export async function getSearchProfiles(): Promise<SearchProfile[]> {
  const profiles = await get<BackendSearchProfile[]>("/search-profiles");
  return profiles.map(mapSearchProfile);
}

export async function createSearchProfile(profile: Partial<SearchProfile>): Promise<SearchProfile> {
  const created = await post<BackendSearchProfile>(
    "/search-profiles",
    searchProfilePayload(profile),
  );
  return mapSearchProfile(created);
}

export async function updateSearchProfile(profile: SearchProfile): Promise<SearchProfile> {
  const updated = await patch<BackendSearchProfile>(
    `/search-profiles/${profile.id}`,
    searchProfilePayload(profile),
  );
  return mapSearchProfile(updated);
}

export async function deleteSearchProfile(profileId: string): Promise<SearchProfile> {
  const deleted = await del<BackendSearchProfile>(`/search-profiles/${profileId}`);
  return mapSearchProfile(deleted);
}

export function getMetrics(): Promise<AutomationMetrics> {
  return get<AutomationMetrics>("/metrics");
}

export async function getLogs(limit = 250): Promise<LogEntry[]> {
  const rows = await get<Array<Omit<LogEntry, "createdAt"> & { created_at?: string }>>(
    `/logs?limit=${limit}`,
  );
  return rows.map((row) => {
    const level = row.level === "warn" || row.level === "error" ? row.level : "info";
    return {
      ...row,
      level,
      createdAt: row.created_at || new Date().toISOString(),
    };
  });
}

export function getWorkers(): Promise<WorkerSummary[]> {
  return get<WorkerSummary[]>("/workers");
}

export function getWorkersStatus(): Promise<WorkersStatus> {
  return get<WorkersStatus>("/workers/status");
}

export function getSettings(): Promise<AutomationSettings> {
  return get<AutomationSettings>("/settings");
}

export function updateSettings(settings: Partial<AutomationSettings>): Promise<AutomationSettings> {
  return patch<AutomationSettings>("/settings", settings);
}

export async function completeLead(threadId: string): Promise<void> {
  await post(`/leads/${threadId}/complete`);
}

export async function skipLead(threadId: string): Promise<void> {
  await post(`/leads/${threadId}/skip`);
}

export function messagesForLead(lead: Lead): Message[] {
  const messages: Message[] = [];

  if (lead.lastLandlordMessage) {
    messages.push({
      id: `landlord-${lead.id}`,
      threadId: lead.threadId,
      sender: "landlord",
      text: lead.lastLandlordMessage,
      createdAt: lead.lastUpdatedAt,
    });
  }

  if (lead.lastAiReply) {
    messages.push({
      id: `ai-${lead.id}`,
      threadId: lead.threadId,
      sender: "ai",
      text: lead.lastAiReply,
      createdAt: lead.lastUpdatedAt,
    });
  }

  return messages;
}

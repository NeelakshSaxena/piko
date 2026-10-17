/** Wire types. They mirror backend/app/api/schemas.py; the server remains the authority for everything. */

export type Role = 'parent' | 'family_admin' | 'guardian' | 'child'
export type InvitableRole = 'parent' | 'family_admin' | 'guardian'
export type Freshness = 'fresh' | 'stale' | 'unknown'
export type DeviceStatus = 'online' | 'offline' | 'unknown'

export interface FamilyRole {
  id: string
  name: string
  role: Role
}

export interface SessionResponse {
  access_token: string
  refresh_token: string
  expires_in: number
  user_id: string
  family_id: string
  role: Role
  families: FamilyRole[]
}

export interface RefreshResponse {
  access_token: string
  refresh_token: string
  expires_in: number
}

export interface FamilySummary {
  id: string
  name: string
  created_at: string
  member_count: number
  device_count: number
  my_role: Role
  status: string
}

export interface Member {
  id: string
  email: string | null
  name: string | null
  role: Role
  joined_at: string
  status: 'active' | 'pending' | 'revoked'
}

export interface FamilyDevice {
  id: string
  name: string
  device_type: 'android'
  owner_member_id: string
  paired_at: string
  last_seen: string | null
  status: 'active' | 'inactive' | 'revoked'
}

export interface FamilyDetail {
  id: string
  name: string
  created_at: string
  my_role: Role
  members: Member[]
  devices: FamilyDevice[]
}

export interface DeviceDetail {
  id: string
  family_id: string
  name: string
  owner_member_id: string
  device_model: string | null
  android_version: string | null
  app_version: string | null
  paired_at: string
  last_activity: string | null
  connectivity_status: DeviceStatus
  battery_percent: number | null
  battery_updated_at: string | null
  battery_is_charging: boolean | null
  network_type: string | null
  network_updated_at: string | null
  status: string
}

export interface MemberLocation {
  member_id: string
  device_id: string | null
  available: boolean
  freshness: Freshness
  freshness_seconds: number | null
  device_status: DeviceStatus
  coordinates?: { latitude: number; longitude: number }
  accuracy_meters?: number
  occurred_at?: string
  received_at?: string
}

export interface HistoryItem {
  event_id: string
  occurred_at: string
  received_at: string
  event_type: 'location' | 'battery' | 'connectivity'
  freshness: Freshness
  data: Record<string, unknown>
}

export interface HistoryPage {
  member_id: string
  device_status: DeviceStatus
  history: HistoryItem[]
  total_count: number
  has_more: boolean
}

export interface PairingCode {
  pairing_code: string
  expires_at: string
  expires_in_seconds: number
}

export interface InviteResult {
  invitation_id: string
  email: string
  role: InvitableRole
  status: 'pending'
  invite_code: string
  expires_at: string
}

export interface AcceptResult {
  user_id: string
  family_id: string
  membership_id: string
  role: Role
}

/** Error codes the API can return (backend/app/core/errors.py). */
export type ErrorCode =
  | 'AUTH_REQUIRED'
  | 'AUTH_INVALID'
  | 'FORBIDDEN'
  | 'NOT_FOUND_OR_NOT_VISIBLE'
  | 'VALIDATION_ERROR'
  | 'RATE_LIMIT'
  | 'CONFLICT'
  | 'SERVICE_UNAVAILABLE'
  | 'INTERNAL_ERROR'

// ---- SOS and messages (Phase 6, ADR-022) ----
/** Server states. "open" means the server stored it and no parent has acknowledged it yet. */
export type SosStatus = 'open' | 'acknowledged' | 'resolved'

export interface SosLocation {
  latitude: number
  longitude: number
  accuracy_meters: number | null
  /** When the position was measured. */
  captured_at: string
  /** True: the last position the server knew, not one sent with the SOS. */
  is_latest_known: boolean
}

export interface Incident {
  incident_id: string
  device_id: string
  family_id: string
  status: SosStatus
  /** The phone's claim of when the SOS was raised. */
  triggered_at: string
  /** When the server stored it. */
  received_at: string
  message: string | null
  location: SosLocation | null
  acknowledged_at: string | null
  resolved_at: string | null
  parent_notes: string | null
}

export interface IncidentPage {
  incidents: Incident[]
  total_count: number
  has_more: boolean
}

export interface ChatMessage {
  message_id: string
  device_id: string
  sender: 'device' | 'parent'
  body: string
  sent_at: string
  received_at: string
  /** delivered: stored by the server. acknowledged: the other side pressed "seen". */
  status: 'delivered' | 'acknowledged'
  acknowledged_at: string | null
}

export interface MessagePage {
  messages: ChatMessage[]
  total_count: number
  has_more: boolean
}

// ---- push (ADR-023) ----
export interface PushConfig {
  web_push_enabled: boolean
  vapid_public_key: string | null
}

export interface WebPushSubscriptionBody {
  endpoint: string
  keys: { p256dh: string; auth: string }
}

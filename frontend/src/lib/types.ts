export interface User {
  id: string
  email: string
  full_name: string
  role: 'customer' | 'admin'
  mfa_enabled: boolean
  created_at: string
}
export interface Account {
  id: string
  account_number: string
  currency: string
  balance_cents: number
}
export interface LedgerEntry {
  id: number
  transaction_id: string
  kind: 'transfer' | 'deposit'
  direction: 'debit' | 'credit'
  amount_cents: number
  balance_after_cents: number
  description: string
  counterparty: string
  created_at: string
}
export interface LedgerPage {
  items: LedgerEntry[]
  next_cursor: number | null
}
export interface Meta {
  step_up_threshold_cents: number
  max_transfer_cents: number
  demo_funding_enabled: boolean
  demo_funding_max_cents: number
}
export interface Transaction {
  id: string
  kind: string
  amount_cents: number
  currency: string
  description: string
  from_account: string
  to_account: string
  created_at: string
}
export interface AuditEvent {
  seq: number
  ts: string
  action: string
  outcome: 'success' | 'failure' | 'denied'
  ip: string | null
}
export type LoginResult = { kind: 'ok' } | { kind: 'mfa'; mfaToken: string }

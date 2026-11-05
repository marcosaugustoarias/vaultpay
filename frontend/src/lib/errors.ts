import { ApiError } from './api'

/** Stable server error codes -> Spanish copy. Unknown codes fall back to a generic text
 *  (never render raw server strings that could contain internals). */
const MESSAGES: Record<string, string> = {
  invalid_credentials: 'Credenciales inválidas o cuenta bloqueada temporalmente.',
  invalid_code: 'Código de verificación inválido.',
  invalid_otp: 'Código de verificación inválido o ya utilizado.',
  otp_required: 'Este monto requiere tu código de verificación 2FA.',
  mfa_required: 'Para enviar este monto activá la verificación en dos pasos (Seguridad).',
  insufficient_funds: 'Fondos insuficientes.',
  limit_exceeded: 'El monto supera el límite por operación.',
  daily_limit_exceeded: 'Superaste tu límite diario de envíos.',
  velocity_exceeded: 'Hiciste demasiadas transferencias seguidas. Esperá unos minutos.',
  destination_not_found: 'La cuenta destino no existe.',
  invalid_account_number: 'El número de cuenta no es válido.',
  same_account: 'No podés transferirte a la misma cuenta.',
  idempotency_key_reused: 'Esta operación ya fue enviada con otros datos. Revisá y volvé a intentar.',
  weak_password: 'La contraseña no cumple la política de seguridad.',
  account_locked: 'Cuenta bloqueada temporalmente por intentos fallidos.',
  rate_limited: 'Demasiados intentos. Esperá un momento.',
  validation_error: 'Revisá los datos ingresados.',
  mfa_already_enabled: 'La verificación en dos pasos ya está activa.',
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'rate_limited') return err.message
    return MESSAGES[err.code] ?? 'Ocurrió un error. Intentá nuevamente.'
  }
  return 'No se pudo conectar con el servidor.'
}

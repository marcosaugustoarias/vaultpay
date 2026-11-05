/**
 * Client-side password feedback only. The SERVER is the authority (SEC-AUTH-02);
 * this just saves the user a round trip. Mirrors the NIST 800-63B approach:
 * length matters, composition rules don't.
 */
export interface Strength {
  score: 0 | 1 | 2 | 3
  label: string
  problems: string[]
}

const COMMON = ['password', 'qwerty', '123456', 'letmein', 'welcome', 'vaultpay', 'iloveyou']

export function checkPassword(pw: string, email = '', name = ''): Strength {
  const problems: string[] = []
  if (pw.length < 12) problems.push('Mínimo 12 caracteres')
  if (pw.length > 128) problems.push('Máximo 128 caracteres')
  const lower = pw.toLowerCase()
  if (COMMON.some((c) => lower.includes(c)) || new Set(lower).size <= 2) problems.push('Es una contraseña común o repetitiva')
  const local = email.split('@')[0]?.toLowerCase() ?? ''
  if (local.length >= 4 && lower.includes(local)) problems.push('No incluyas tu correo')
  if (name.toLowerCase().split(/\s+/).some((p) => p.length >= 4 && lower.includes(p))) problems.push('No incluyas tu nombre')

  let score: Strength['score'] = 0
  if (problems.length === 0) score = pw.length >= 20 ? 3 : pw.length >= 16 ? 2 : 1
  return { score, label: ['Débil', 'Aceptable', 'Buena', 'Excelente'][score] as string, problems }
}

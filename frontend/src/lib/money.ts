/** Money is handled as integer cents end-to-end (SEC-DATA-02): no floats in the logic. */

export function formatCents(cents: number, currency = 'USD'): string {
  const sign = cents < 0 ? '-' : ''
  const abs = Math.abs(cents)
  const units = Math.floor(abs / 100)
  const rem = String(abs % 100).padStart(2, '0')
  const grouped = new Intl.NumberFormat('en-US').format(units)
  const symbol = currency === 'USD' ? '$' : `${currency} `
  return `${sign}${symbol}${grouped}.${rem}`
}

/** "1,234.5" -> 123450. Returns null for anything that is not a positive amount with <= 2 decimals. */
export function parseToCents(input: string): number | null {
  const cleaned = input.trim().replace(/,/g, '')
  if (!/^\d{1,9}(\.\d{1,2})?$/.test(cleaned)) return null
  const [units = '0', frac = ''] = cleaned.split('.')
  const cents = Number(units) * 100 + Number(frac.padEnd(2, '0'))
  return cents > 0 ? cents : null
}

/** Luhn check, mirrors the server (typo protection on account numbers). */
export function luhnValid(num: string): boolean {
  if (!/^\d{12}$/.test(num)) return false
  let total = 0
  for (let i = 0; i < num.length - 1; i++) {
    let d = Number(num[num.length - 2 - i])
    if (i % 2 === 0) {
      d *= 2
      if (d > 9) d -= 9
    }
    total += d
  }
  return String((10 - (total % 10)) % 10) === num[num.length - 1]
}

export const maskNumber = (n: string) => `••••${n.slice(-4)}`

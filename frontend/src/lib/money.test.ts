import { describe, expect, it } from 'vitest'
import { formatCents, luhnValid, maskNumber, parseToCents } from './money'
import { checkPassword } from './password'

describe('money (integer cents, no floats)', () => {
  it('parses decimal strings exactly', () => {
    expect(parseToCents('0.1')).toBe(10)
    expect(parseToCents('0.29')).toBe(29) // 0.29 * 100 = 28.999999999999996 with floats
    expect(parseToCents('1,234.56')).toBe(123456)
    expect(parseToCents('10')).toBe(1000)
  })
  it('rejects invalid, negative, zero and over-precise amounts', () => {
    for (const bad of ['', '-5', '0', '0.00', '1.234', 'abc', '1e3', '1.2.3', ' . ']) expect(parseToCents(bad)).toBeNull()
  })
  it('formats cents', () => {
    expect(formatCents(123456)).toBe('$1,234.56')
    expect(formatCents(5)).toBe('$0.05')
    expect(formatCents(-250)).toBe('-$2.50')
  })
  it('validates account numbers with Luhn and masks them', () => {
    expect(luhnValid('000000000000')).toBe(true)
    expect(luhnValid('000000000001')).toBe(false)
    expect(luhnValid('79927398713')).toBe(false) // wrong length
    expect(maskNumber('123456789012')).toBe('••••9012')
  })
})

describe('password feedback', () => {
  it('follows length-first policy', () => {
    expect(checkPassword('short').problems).toContain('Mínimo 12 caracteres')
    expect(checkPassword('mypassword-is-long').problems.length).toBeGreaterThan(0) // contains "password"
    expect(checkPassword('alice-rocks-forever', 'alice@example.com').problems).toContain('No incluyas tu correo')
    expect(checkPassword('tangerine-orbit-maple-42').problems).toEqual([])
  })
})

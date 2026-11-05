import { randomUUID } from 'node:crypto'
import { expect, type Page, test } from '@playwright/test'

/**
 * Functional end-to-end test: a real browser against the real Docker stack
 * (nginx -> FastAPI -> PostgreSQL). Nothing is mocked.
 *
 * Note: the API allows 5 registrations per IP per hour (SEC-RATE). Each run of this
 * file registers 2 customers; `docker compose restart backend` resets the limiter.
 */

const PASSWORD = `e2e-${randomUUID()}` // >= 12 chars, not in the common-password list
const run = Date.now().toString(36)

async function register(page: Page, name: string, email: string) {
  await page.goto('/register')
  await page.getByLabel('Nombre completo').fill(name)
  await page.getByLabel('Correo electrónico').fill(email)
  await page.getByLabel('Contraseña', { exact: true }).fill(PASSWORD)
  await page.getByLabel('Repetir contraseña').fill(PASSWORD)
  await page.getByRole('button', { name: 'Crear cuenta' }).click()
  await expect(page).toHaveURL(/\/login$/)
}

async function login(page: Page, email: string) {
  await page.getByLabel('Correo electrónico').fill(email)
  await page.getByLabel('Contraseña').fill(PASSWORD)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Hola')
}

test('sin sesión, las rutas privadas redirigen al login', async ({ page }) => {
  await page.goto('/transfer')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Iniciar sesión' })).toBeVisible()
})

test('alta de dos clientes, fondos de prueba y transferencia entre ellos', async ({ browser }) => {
  const ana = { name: 'Ana E2E', email: `ana-${run}@example.com` }
  const bruno = { name: 'Bruno E2E', email: `bruno-${run}@example.com` }

  // --- Bruno: registro, login y número de cuenta (contexto de navegador separado)
  const brunoPage = await (await browser.newContext()).newPage()
  await register(brunoPage, bruno.name, bruno.email)
  await login(brunoPage, bruno.email)
  await expect(brunoPage.getByTestId('balance')).toHaveText('$0.00')
  await brunoPage.getByRole('button', { name: 'Mostrar número' }).click()
  const brunoNumber = (await brunoPage.getByText(/^\d{12}$/).textContent())!.trim()

  // --- Ana: registro, login y fondos de prueba
  const anaPage = await (await browser.newContext()).newPage()
  await register(anaPage, ana.name, ana.email)
  await login(anaPage, ana.email)
  await anaPage.getByRole('button', { name: '+ $100.00' }).click()
  await expect(anaPage.getByTestId('balance')).toHaveText('$100.00')
  await expect(anaPage.getByText('Sandbox funding').first()).toBeVisible()

  // --- Ana transfiere: primero un número mal tecleado (Luhn), luego el correcto
  await anaPage.getByRole('link', { name: 'Transferir', exact: true }).click()
  const destination = anaPage.getByLabel('Cuenta destino')
  const typo = brunoNumber.slice(0, 11) + ((Number(brunoNumber[11]) + 1) % 10)
  await destination.fill(typo)
  await expect(anaPage.getByText('Número de cuenta inválido (dígito verificador)')).toBeVisible()
  await destination.fill(brunoNumber)
  await anaPage.getByLabel('Monto (USD)').fill('25.50')
  await anaPage.getByLabel('Concepto (opcional)').fill('Cena E2E')
  await anaPage.getByRole('button', { name: 'Continuar' }).click()
  await expect(anaPage.getByText('Revisá la operación')).toBeVisible()
  await anaPage.getByRole('button', { name: 'Confirmar envío' }).click()
  await expect(anaPage.getByText('Transferencia enviada')).toBeVisible()
  await expect(anaPage.getByText(`$25.50 a ••••${brunoNumber.slice(-4)}`)).toBeVisible()

  // --- Saldos finales en ambos lados (Bruno recarga: la sesión se reanuda por cookie)
  await anaPage.getByRole('link', { name: 'Ir al inicio' }).click()
  await expect(anaPage.getByTestId('balance')).toHaveText('$74.50')
  await brunoPage.reload()
  await expect(brunoPage.getByTestId('balance')).toHaveText('$25.50')
  await expect(brunoPage.getByText('Cena E2E')).toBeVisible()
})

# VaultPay

Billetera fintech de referencia con **seguridad por diseño**. Backend **FastAPI** y frontend
**React + TypeScript + Tailwind CSS**. Cada decisión de seguridad tiene un ID (`SEC-…`) que se
puede seguir desde la documentación hasta el código y el test que la demuestra.

> Sandbox educativo: no usar con dinero ni datos reales.

## Qué hace

- Registro, login con **MFA TOTP**, sesiones con **rotación de refresh tokens y detección de robo**.
- Cuenta con saldo, **transferencias** entre usuarios por número de cuenta (con dígito Luhn) y extracto paginado.
- **Autenticación reforzada (step-up)** para montos ≥ $500, más límites por operación, diarios y de velocidad.
- Página de **Seguridad**: activar o desactivar 2FA, cambiar la contraseña (cierra todas las sesiones) y ver tu actividad.
- Panel de administración: verificación de integridad del **log de auditoría encadenado por hash**.

## Cómo quedan evidenciados los conceptos

| Concepto | Dónde verlo |
|---|---|
| Arquitectura en capas, flujos, decisiones | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Modelo de amenazas STRIDE y abuso de lógica de negocio | [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) |
| **33 controles** → estándar (OWASP ASVS / API Top 10, PCI DSS, NIST) → archivo → test | [`docs/SECURITY_CONTROLS.md`](docs/SECURITY_CONTROLS.md) |
| Checklist de producción y **limitaciones honestas** | [`SECURITY.md`](SECURITY.md) |
| Trazabilidad automática docs ↔ código | `python3 scripts/check_controls.py` |
| Pipeline DevSecOps | [`.github/workflows/ci.yml`](.github/workflows/ci.yml) |

**Pruebas:** 105 tests de backend (100 sobre SQLite y 5 de integración sobre PostgreSQL real:
doble gasto concurrente, ausencia de deadlocks, triggers y cadena de auditoría con escritores
concurrentes), con **96 % de cobertura**, más 14 tests de frontend (Vitest + Testing Library).

## Estructura

```
backend/     FastAPI · SQLAlchemy 2 · Argon2id · PyJWT · AES-GCM · pyotp
  app/security/   primitivas (passwords, tokens, totp, crypto, rate limit, middleware)
  app/services/   dominio (auth, ledger de doble entrada, riesgo, auditoría)
  app/routers/    capa HTTP
  tests/          un test por control, más la integración con PostgreSQL
frontend/    React 19 · Vite · Tailwind 4 · React Router
  nginx/          CSP estricta y cabeceras (producción)
  scripts/        guard que prohíbe innerHTML/eval/Web Storage
docs/        arquitectura, amenazas, matriz de controles
```

## Ejecutar en local (desarrollo)

Requisitos: Python 3.12+ y Node 22+.

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
```

```bash
uvicorn app.main:app --reload --port 8000
```

En otra terminal:

```bash
cd frontend && npm install && npm run dev
```

Abrí http://localhost:5173. Vite hace de proxy de `/api` hacia `:8000` (mismo origen, como en
producción). Creá una cuenta, cargá **fondos de prueba** desde el inicio, activá 2FA en *Seguridad*
y transferí a una segunda cuenta.

Crear un administrador (la contraseña se pide por consola y nunca va como argumento):

```bash
cd backend && python -m app.cli create-admin admin@example.com
```

## Stack tipo producción (Docker)

```bash
cp .env.example .env && ./scripts/gen-secrets.sh >> .env
```

```bash
docker compose up --build
```

Queda disponible en http://localhost:8080. El compose **no arranca sin secretos**. Los contenedores
corren como no-root, con FS de solo lectura y `cap_drop: ALL`, y la BD vive en una red interna.

## Tests y análisis

```bash
cd backend && pytest --cov && ruff check . && bandit -r app -c pyproject.toml && pip-audit -r requirements.txt
```

Para incluir la integración con PostgreSQL:

```bash
VAULTPAY_TEST_POSTGRES_URL=postgresql+psycopg://user:pass@localhost:5432/vaultpay_test pytest
```

```bash
cd frontend && npm run lint:security && npm run typecheck && npm test && npm run build
```

## API (resumen)

| Método | Ruta | Auth | Notas |
|---|---|---|---|
| POST | `/api/auth/register` | — | Respuesta idéntica aunque el e-mail ya exista |
| POST | `/api/auth/login` | — | Devuelve el token, o `mfa_required` + `mfa_token` |
| POST | `/api/auth/mfa/verify` | `mfa_token` | Completa el login |
| POST | `/api/auth/refresh` · `/logout` | cookie + `X-Requested-With` | Rotación / revocación |
| POST | `/api/auth/change-password` | Bearer | Revoca todas las sesiones |
| POST | `/api/mfa/setup` · `/enable` · `/disable` | Bearer | Para desactivar se piden contraseña y OTP |
| GET | `/api/accounts` · `/api/accounts/{id}/transactions` | Bearer | Solo cuentas propias |
| POST | `/api/transfers` | Bearer + `Idempotency-Key` | OTP si el monto ≥ umbral |
| GET | `/api/audit/me` | Bearer | Tu actividad de seguridad |
| GET | `/api/admin/audit/verify` | Bearer (admin) | Integridad de la cadena (`?anchor=`) |

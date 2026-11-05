# Instrucciones para GitHub Copilot (y otros asistentes)

Mismas reglas que [`CLAUDE.md`](../CLAUDE.md). Resumen para el chat y las sugerencias inline:

- **Backend FastAPI por capas DDD**: `routers/` (HTTP) → `services/` (aplicación) → `domain/`
  (reglas puras). `app/domain` solo importa la stdlib; nada de SQLAlchemy ni FastAPI ahí.
- Errores de negocio: `BusinessRuleViolation(code, message)` en el dominio; el código HTTP se
  asigna en `services/errors.RULE_STATUS`. Cada `code` nuevo también va en `frontend/src/lib/errors.ts`.
- Dinero en **centavos enteros** (`Money`). Números de cuenta con `AccountNumber` (Luhn).
- Frontend React + TS + Tailwind: sin `innerHTML`, `dangerouslySetInnerHTML`, `eval` ni
  `localStorage`/`sessionStorage` para tokens. Componentes accesibles (`label`, `aria-*`).
- Toda regla nueva con test: unitario en `backend/tests/unit/`, funcional en `backend/tests/`,
  de componente en `frontend/src/**/*.test.tsx`, y E2E en `e2e/tests/` si es un flujo de usuario.
- Nunca sugieras secretos, contraseñas ni claves en el código; usa variables de entorno.

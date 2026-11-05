# CLAUDE.md — guía para asistentes de IA en VaultPay

Este archivo lo leen Claude Code y otros agentes al trabajar en el repo. Es el "contrato" que
hace que el código generado por IA respete la arquitectura. Ver también
[`docs/AI_WORKFLOW.md`](docs/AI_WORKFLOW.md) y [`docs/DDD.md`](docs/DDD.md).

## Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2, PostgreSQL (SQLite en tests). Carpeta `backend/`.
- Frontend: React 19 + TypeScript + Vite + Tailwind 4. Carpeta `frontend/`.
- E2E: Playwright en `e2e/`, contra el stack de Docker.

## Arquitectura (no romper)

```
routers/   -> interfaz HTTP fina: schemas, auth, mapeo de errores
services/  -> capa de aplicación: unidad de trabajo, orquestación, SQL
domain/    -> reglas de negocio PURAS (solo stdlib). Contexto Ledger: Money, AccountNumber,
              check_transfer, assess_risk
models.py  -> persistencia (ORM, CHECKs, triggers)
```

1. **`app/domain` no importa nada fuera de la stdlib y de `app.domain`.** Lo verifica
   `tests/unit/test_domain_purity.py`. Una regla de negocio nueva va al dominio, no al router.
2. El dominio lanza `BusinessRuleViolation(code, message)` **sin código HTTP**. Si añades un
   `code`, regístralo en `services/errors.RULE_STATUS` **y** en `frontend/src/lib/errors.ts`.
3. Dinero siempre en **centavos enteros** (`Money`), nunca `float`.
4. La invariante de saldo se hace cumplir en SQL atómico (`UPDATE … WHERE balance >= :m`); no
   la reimplementes en memoria (ver "Agregado Account y concurrencia" en `docs/DDD.md`).
5. Lenguaje ubicuo: usa los términos de `docs/DDD.md` §2 en nombres, tests y mensajes.

## Seguridad (obligatorio)

- Cada control tiene un ID `SEC-…` documentado en `docs/SECURITY_CONTROLS.md`; si cambias uno,
  actualiza la matriz (`python3 scripts/check_controls.py` lo verifica en CI).
- Frontend: prohibido `innerHTML`, `dangerouslySetInnerHTML`, `eval` y Web Storage para tokens
  (`npm run lint:security`). El access token vive solo en memoria.
- Nunca escribas secretos en el repo. `.env` está ignorado; se genera con `scripts/gen-secrets.sh`.

## Cómo verificar un cambio (antes de darlo por terminado)

Sin Python/Node locales, todo corre en contenedores:

```bash
docker compose -f docker-compose.test.yml run --rm backend-tests    # ruff + bandit + pytest (SQLite + PostgreSQL)
docker compose -f docker-compose.test.yml run --rm frontend-tests   # guard + tsc + vitest + build
docker compose up -d --build && docker compose -f docker-compose.test.yml --profile e2e run --rm e2e
```

Con herramientas locales: `cd backend && pytest --cov && ruff check .` y
`cd frontend && npm run lint:security && npm run typecheck && npm test`.

## Reglas de trabajo para la IA

- Toda regla nueva lleva **test unitario** (dominio) y, si cruza HTTP, **test funcional** (API).
- Cambios pequeños y commits separados por intención (refactor ≠ feature ≠ docs).
- No borres ni debilites tests para que pasen; si un test es incorrecto, explica por qué.
- Registra en `docs/AI_WORKFLOW.md` las decisiones relevantes y los errores de la IA detectados.

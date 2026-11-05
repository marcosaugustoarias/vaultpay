# Matriz de controles de seguridad

Cada control tiene un **ID estable** que aparece como comentario en el código (`SEC-…`), en esta
tabla y, cuando aplica, en los tests que lo demuestran. `scripts/check_controls.py` (ejecutado en CI)
falla si un control documentado no está en el código o si el código usa un ID no documentado.

Referencias: **ASVS** = OWASP ASVS 4.0.3 · **API** = OWASP API Security Top 10 (2023) ·
**PCI** = PCI DSS v4.0 · **NIST** = SP 800-63B.

## Autenticación y sesión

| ID | Control | Amenaza mitigada | Referencia | Implementación | Evidencia (tests) |
|---|---|---|---|---|---|
| SEC-AUTH-01 | Hash de contraseñas con **Argon2id** (RFC 9106), re-hash transparente al subir parámetros | Robo de BD → crackeo offline | ASVS 2.4.1, PCI 8.3.2 | `backend/app/security/passwords.py` | `test_password_stored_as_argon2id_not_plaintext` |
| SEC-AUTH-02 | Política NIST: ≥12 caracteres, máx. 128, lista de bloqueo, sin datos personales, sin reglas de composición | Contraseñas débiles / *hash DoS* | NIST 800-63B §5.1.1, ASVS 2.1 | `passwords.validate_password_policy`, `frontend/src/lib/password.ts` | `test_weak_passwords_rejected` |
| SEC-AUTH-03 | **Bloqueo de cuenta** tras N fallos (contraseña *o* OTP), con expiración | Fuerza bruta dirigida | ASVS 2.2.1, PCI 8.3.4 | `backend/app/services/mfa.py`, `services/auth.py` | `test_account_lockout_after_repeated_failures`, `test_wrong_code_rejected_and_counts_toward_lockout`, `test_lockout_expires` |
| SEC-AUTH-04 | **Anti-enumeración**: mismo mensaje y tiempo para usuario inexistente / contraseña errónea / bloqueo; registro con respuesta idéntica | Enumeración de cuentas | OWASP Authentication Cheat Sheet (respuestas genéricas), API2 | `services/auth.py` (`verify_dummy`) | `test_login_failures_are_indistinguishable`, `test_registration_does_not_reveal_existing_emails`, `test_dummy_verification_is_used_for_unknown_users` |
| SEC-AUTH-05 | JWT de acceso de **15 min**, algoritmo fijado (HS256), `iss`/`aud`/`exp`/`iat`/`sub`/`jti` obligatorios, claim `use`; invalidación por cambio de contraseña | `alg:none`, confusión de algoritmo, *token replay* entre propósitos | ASVS 3.5.3, API2 | `backend/app/security/tokens.py`, `deps.get_current_user` | `test_alg_none_token_rejected`, `test_token_signed_with_other_secret_rejected`, `test_expired_token_rejected`, `test_mfa_pending_token_cannot_be_used_as_access_token` |
| SEC-AUTH-06 | Refresh token **opaco de 256 bits**, guardado solo como SHA-256, **rotación** en cada uso y **detección de reutilización** (revoca toda la familia) | Robo de refresh token | OAuth 2.0 Security BCP (RFC 9700) §4.14 | `services/auth.rotate_refresh_token` | `test_refresh_rotates_and_issues_working_access_token`, `test_refresh_token_reuse_revokes_whole_family`, `test_refresh_token_stored_only_as_hash` |
| SEC-AUTH-07 | Cookie de refresh `HttpOnly; SameSite=Strict; Path=/api/auth` (+`Secure` en prod) y **guardia CSRF** (cabecera custom + validación de `Origin`) | XSS robando sesión, CSRF | ASVS 3.4, 4.2.2 | `routers/auth.py`, `deps.csrf_guard` | `test_refresh_cookie_flags`, `test_refresh_requires_csrf_header_and_allowed_origin` |
| SEC-AUTH-08 | **MFA TOTP** (RFC 6238): secreto cifrado, comparación en tiempo constante, ventana ±1, **anti-replay** de pasos | Credenciales filtradas / phishing reutilizado | ASVS 2.8, PCI 8.4 | `security/totp.py`, `routers/mfa.py` | `test_login_with_mfa_requires_second_factor`, `test_totp_code_cannot_be_replayed`, `test_totp_unit_replay_and_window`, `test_disable_requires_password_and_code` |
| SEC-AUTH-09 | **Autenticación reforzada (step-up)**: transferencias ≥ umbral exigen un OTP *nuevo* | Sesión secuestrada vaciando la cuenta | RFC 9470 (step-up), PSD2 SCA (inspiración) | `services/ledger.transfer`, `services/risk.py` | `test_high_value_transfer_step_up`, `test_high_value_transfer_needs_mfa_enrolment`, `test_business_401_is_distinguishable_from_auth_failure` |

## Autorización

| ID | Control | Amenaza mitigada | Referencia | Implementación | Evidencia |
|---|---|---|---|---|---|
| SEC-AUTHZ-01 | **Autorización a nivel de objeto**: toda consulta se filtra por propietario; recurso ajeno ⇒ 404 idéntico a inexistente | **BOLA/IDOR** | **API1**, ASVS 4.2.1 | `routers/accounts.owned_account`, `services/ledger.transfer` | `test_cannot_spend_from_someone_elses_account`, `test_cannot_read_someone_elses_statement`, `test_cannot_fund_someone_elses_account` |
| SEC-AUTHZ-02 | **RBAC** en servidor (`customer`/`admin`); el rol no es asignable por el cliente | Escalada de privilegios | API5, ASVS 4.1 | `deps.require_admin`, `routers/audit.py` | `test_admin_endpoint_forbidden_for_customers`, `test_role_cannot_be_self_assigned`, `test_admin_can_verify_audit_chain` |

## Datos e integridad financiera

| ID | Control | Amenaza mitigada | Referencia | Implementación | Evidencia |
|---|---|---|---|---|---|
| SEC-DATA-01 | **Cifrado a nivel de campo** AES-256-GCM (teléfono, secreto TOTP), nonce aleatorio, propósito como AAD, **keyring con rotación** | Fuga de BD / backups | ASVS 6.2, PCI 3.5 | `security/crypto.py` (`EncryptedString`) | `test_phone_is_encrypted_in_database`, `test_secret_is_encrypted_at_rest`, `test_ciphertext_bound_to_its_column`, `test_tampered_ciphertext_detected`, `test_key_rotation_keeps_old_data_readable` |
| SEC-DATA-02 | Dinero **siempre en enteros (centavos)**; `StrictInt` en la API; `CHECK` en BD (no sobregiro, montos > 0) | Errores de redondeo, montos negativos | ASVS 5.1.3 | `models.py`, `schemas.py`, `frontend/src/lib/money.ts` | `test_money_amounts_must_be_positive_integers`, `test_negative_amount_cannot_pull_money_from_victim`, `test_database_blocks_overdraft_and_nonpositive_amounts` |
| SEC-DATA-03 | **Libro mayor y auditoría append-only**: triggers en BD (SQLite y PostgreSQL) + guardia ORM | Manipulación del historial | PCI 10.3.2 | `database.install_immutability_guards`, `models.py` | `test_ledger_is_append_only_at_db_level`, `test_ledger_and_audit_are_append_only_in_orm`, `test_append_only_triggers` (PostgreSQL) |
| SEC-DATA-04 | **Doble entrada** + movimiento atómico: débito condicional (`WHERE balance >= monto`), orden de bloqueo determinista, todo en una transacción | **Doble gasto / race conditions**, deadlocks | API6 (flujos de negocio) | `services/ledger._move` | `test_concurrent_transfers_cannot_double_spend` (SQLite y PostgreSQL), `test_opposite_direction_transfers_do_not_deadlock`, `test_transfer_moves_money_and_keeps_ledger_balanced` |
| SEC-DATA-05 | **Idempotency-Key obligatoria**; reintento ⇒ mismo resultado; misma clave con otro payload ⇒ 422 | Pagos duplicados por reintentos / doble clic | Stripe-style idempotency | `routers/transfers.py`, `services/ledger._find_existing`, `TransferPage.tsx` | `test_idempotent_retry_moves_money_once`, `test_idempotency_key_reuse_with_other_payload_rejected`, `test_concurrent_identical_requests_are_idempotent` |

## Auditoría y logging

| ID | Control | Amenaza mitigada | Referencia | Implementación | Evidencia |
|---|---|---|---|---|---|
| SEC-AUDIT-01 | Log de auditoría **encadenado por hash** (SHA-256), escrito en la misma transacción que el cambio; verificación + **ancla externa** para detectar truncado | Repudio, borrado de rastros | PCI 10.2 / 10.3, ASVS 7.3 | `services/audit.py`, `GET /api/admin/audit/verify` | `test_audit_chain_valid_and_detects_tampering`, `test_audit_chain_detects_deleted_row`, `test_audit_truncation_is_caught_by_external_anchor`, `test_audit_chain_survives_concurrent_writers` (PostgreSQL) |
| SEC-AUDIT-02 | Logs estructurados JSON **con redacción** (tokens, contraseñas, PAN, e-mails); access log sin cuerpos ni query strings; request-id | Fuga de secretos en logs | ASVS 7.1, PCI 3.3 | `logging_config.py`, `security/middleware.py` | `test_log_redaction`, `test_access_log_contains_no_secrets` |

## Superficie HTTP / API

| ID | Control | Amenaza mitigada | Referencia | Implementación | Evidencia |
|---|---|---|---|---|---|
| SEC-API-01 | Validación estricta: `extra="forbid"` (mass assignment), tipos estrictos, longitudes, patrones, sin caracteres de control | Inyección, mass assignment | API3, ASVS 5.1 | `schemas.py` | `test_mass_assignment_is_rejected`, `test_description_rejects_control_characters` |
| SEC-API-02 | **Rate limiting** por IP (login, registro, MFA, transferencias); `X-Forwarded-For` solo detrás de N proxies de confianza | Credential stuffing, abuso | **API4** | `security/rate_limit.py` | `test_login_rate_limit_per_ip`, `test_spoofed_x_forwarded_for_cannot_bypass_rate_limit`, `test_sliding_window_limiter` |
| SEC-API-03 | Cabeceras de seguridad (CSP, HSTS, XFO, nosniff, Referrer/Permissions-Policy, COOP/CORP, `Cache-Control: no-store`) | Clickjacking, sniffing, caché de datos sensibles | ASVS 14.4 | `security/middleware.py` | `test_security_headers_present`, `test_hsts_outside_development` |
| SEC-API-04 | **CORS** con lista explícita (nunca `*` con credenciales) + validación de `Host` | Lectura cross-origin, host header injection | API8, ASVS 14.5 | `main.py` | `test_cors_only_allows_configured_origins`, `test_host_header_attack_rejected` |
| SEC-API-05 | Límite de tamaño de body (por `Content-Length` **y** por bytes en streaming) | DoS por payloads | API4 | `security/middleware.BodySizeLimitMiddleware` | `test_oversized_body_rejected_by_content_length`, `test_oversized_streamed_body_rejected` |
| SEC-API-06 | Errores saneados: 422 **sin eco del input** (no refleja contraseñas), 500 genérico con request-id | Fuga de información | ASVS 7.4 | `errors.py` | `test_validation_errors_never_echo_submitted_values`, `test_unhandled_errors_do_not_leak_internals` |

## Riesgo, configuración, frontend, cadena de suministro e infraestructura

| ID | Control | Amenaza mitigada | Referencia | Implementación | Evidencia |
|---|---|---|---|---|---|
| SEC-RISK-01 | Motor de reglas: límite por operación, **límite diario**, **velocidad** (transferencias/hora), umbral de step-up | Fraude, cuenta comprometida | API6 | `services/risk.py` | `test_per_transfer_limit`, `test_daily_limit`, `test_velocity_limit` |
| SEC-CFG-01 | **Fail-fast**: en producción la app no arranca con secretos por defecto, cookies inseguras, CORS `*`, docs públicas, SQLite o fondeo demo | Despliegue mal configurado | ASVS 14.1, API8 | `config.py` | `test_insecure_production_config_refuses_to_start` (10 casos), `test_docs_disabled_when_configured` |
| SEC-FE-01 | Access token **solo en memoria** (nunca Web Storage); refresh en cookie HttpOnly | XSS exfiltrando tokens | ASVS 3.2.3 | `frontend/src/lib/api.ts` | `api.test.ts › never persists tokens in Web Storage`, E2E |
| SEC-FE-02 | **CSP estricta** sin `unsafe-inline`/`eval`; prohibición automática de `innerHTML`/`eval`/Web Storage en el código | XSS | ASVS 5.3, 14.4.3 | `frontend/nginx/*.conf`, `frontend/scripts/check-security.mjs` | `npm run lint:security`, E2E (0 violaciones CSP, payload `<script>` renderizado como texto) |
| SEC-FE-03 | Cierre de sesión por **inactividad** (5 min con aviso a los 30 s) | Sesión abandonada | PCI 8.2.8 | `frontend/src/auth/useIdleTimeout.ts` | Revisión manual / E2E |
| SEC-FE-04 | Una Idempotency-Key por operación lógica, paso de revisión, botón deshabilitado durante el envío | Doble envío | — | `frontend/src/pages/TransferPage.tsx` | E2E |
| SEC-FE-05 | Refresh **single-flight** (y entre pestañas con Web Locks); solo se refresca ante `not_authenticated`, nunca ante 401 de negocio | Falsos positivos de reutilización; reenvío de POST monetarios | — | `frontend/src/lib/api.ts` | `api.test.ts › concurrent refreshes are coalesced`, `› does NOT refresh or replay on business 401s` |
| SEC-SUP-01 | CI con ruff+bandit (SAST), pip-audit / npm audit, gitleaks, tests en PostgreSQL real, Dependabot, dependencias fijadas, token de CI de solo lectura | Dependencias vulnerables, secretos en git | PCI 6.3, SLSA (parcial) | `.github/workflows/ci.yml`, `.github/dependabot.yml` | Pipeline |
| SEC-INF-01 | Contenedores **no-root**, multi-stage, FS de solo lectura, `cap_drop: ALL`, `no-new-privileges`, red interna sin salida a Internet, BD no publicada, secretos obligatorios | Escape / movimiento lateral | CIS Docker Benchmark | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` | `docker compose config` falla sin secretos |

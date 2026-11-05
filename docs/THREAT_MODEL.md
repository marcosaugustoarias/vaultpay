# Modelo de amenazas (STRIDE)

## Activos

| Activo | Por qué importa |
|---|---|
| Saldos y libro mayor | Pérdida financiera directa |
| Credenciales, secretos TOTP, refresh tokens | Toma de cuentas |
| PII (nombre, e-mail, teléfono) | Privacidad / regulación |
| Log de auditoría | Evidencia forense, no repudio |
| `JWT_SECRET`, `ENCRYPTION_KEY` | Comprometen todo lo anterior |

## Atacantes considerados

- **Externo anónimo**: credential stuffing, enumeración, fuzzing de la API.
- **Cliente malicioso autenticado**: IDOR/BOLA, montos negativos, condiciones de carrera, mass assignment.
- **Atacante con XSS** en el navegador de la víctima.
- **Ladrón de sesión** (token/cookie robados, malware).
- **Insider / atacante con acceso a la BD** (lectura de backups, edición de filas).

## STRIDE

| Categoría | Amenaza concreta | Mitigación (control) | Riesgo residual |
|---|---|---|---|
| **S**poofing | Fuerza bruta / credential stuffing | Argon2id, bloqueo, rate limit, MFA (SEC-AUTH-01/03/08, SEC-API-02) | Rate limit por proceso (ver Limitaciones) |
| | Token falsificado (`alg:none`, otra clave) | Algoritmo fijado, claims obligatorios (SEC-AUTH-05) | Clave simétrica compartida |
| | Robo de refresh token | Rotación + detección de reuso, HttpOnly/SameSite (SEC-AUTH-06/07) | Ventana hasta el primer reuso |
| | Phishing del OTP | Anti-replay, step-up por operación (SEC-AUTH-08/09) | TOTP no es resistente a phishing en tiempo real (WebAuthn en roadmap) |
| **T**ampering | Monto negativo / float / campos extra | Tipos estrictos, `extra=forbid`, CHECKs (SEC-API-01, SEC-DATA-02) | — |
| | Doble gasto por concurrencia | Débito condicional, orden de bloqueo (SEC-DATA-04) | — (probado en PostgreSQL) |
| | Editar historial en BD | Triggers append-only + cadena de hashes + ancla (SEC-DATA-03, SEC-AUDIT-01) | Superusuario de BD puede quitar triggers: se detecta, no se impide |
| | Modificar ciphertext / moverlo de columna | AES-GCM autenticado con AAD (SEC-DATA-01) | — |
| **R**epudiation | "Yo no hice esa transferencia" | Auditoría encadenada con IP, `amr`, step-up registrado (SEC-AUDIT-01) | — |
| **I**nformation disclosure | Enumeración de usuarios | Respuestas y tiempos idénticos (SEC-AUTH-04) | Enumeración de *números de cuenta* (necesaria para UX), mitigada con Luhn + rate limit |
| | IDOR en cuentas/movimientos | Filtro por propietario, 404 uniforme (SEC-AUTHZ-01) | — |
| | Secretos en logs / respuestas 422 | Redacción, 422 sin `input` (SEC-AUDIT-02, SEC-API-06) | — |
| | Fuga de BD | Hash de contraseñas/tokens, cifrado de PII/TOTP (SEC-AUTH-01/06, SEC-DATA-01) | e-mail y nombre en claro (necesarios para login/UI) |
| | XSS roba datos | CSP estricta, React escapa, guard de APIs peligrosas (SEC-FE-02) | — |
| **D**enial of service | Payloads enormes | Límite de body (SEC-API-05), longitudes máximas | DoS volumétrico ⇒ WAF/CDN |
| | Hash-DoS con contraseñas largas | Máx. 128 caracteres (SEC-AUTH-02) | — |
| | Bloquear cuentas ajenas a propósito | Bloqueo temporal (15 min), no permanente | Trade-off conocido |
| **E**levation of privilege | Auto-asignarse `role=admin` | `extra=forbid`, RBAC en servidor (SEC-AUTHZ-02) | — |
| | Desactivar MFA con un token robado | Requiere contraseña **y** OTP | — |
| | Configuración insegura en prod | Fail-fast (SEC-CFG-01) | — |

## Abuso de lógica de negocio (OWASP API6)

| Escenario | Defensa |
|---|---|
| Reintentar un POST para cobrar dos veces | Idempotency-Key obligatoria (SEC-DATA-05) |
| Vaciar la cuenta con una sesión robada | Límites diario/velocidad + step-up (SEC-RISK-01, SEC-AUTH-09) |
| Fondeo infinito en sandbox | Tope por operación, rate limit, deshabilitado en prod (SEC-CFG-01) |
| Cliente reenvía un OTP inválido tras refresh automático | El cliente solo refresca ante `not_authenticated` (SEC-FE-05). Regresión encontrada en E2E y cubierta por tests |

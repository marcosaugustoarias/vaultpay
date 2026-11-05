# Política de seguridad

## Reportar una vulnerabilidad

No abras un issue público. Usá **GitHub → Security → Report a vulnerability** (aviso privado).
Incluí pasos de reproducción e impacto. Objetivo: acuse en 72 h, corrección de severidad alta en 30 días.
Por favor, no accedas a datos de otros usuarios ni degrades el servicio durante las pruebas.

## Ejecutar los controles localmente

```bash
cd backend && ruff check . && bandit -r app -c pyproject.toml && pip-audit -r requirements.txt && pytest --cov
cd frontend && npm run lint:security && npm run typecheck && npm test && npm audit --omit=dev
python3 scripts/check_controls.py
```

## Operación segura (checklist de producción)

- [ ] `VAULTPAY_ENV=production`: la app **se niega a arrancar** si algo de lo siguiente falta.
- [ ] `VAULTPAY_JWT_SECRET` (≥ 32 bytes aleatorios) y `VAULTPAY_ENCRYPTION_KEY` (32 bytes, base64) desde un gestor de secretos (Vault, AWS Secrets Manager, GCP Secret Manager), nunca en el repositorio.
- [ ] TLS terminado delante de nginx, `VAULTPAY_COOKIE_SECURE=true`, orígenes `https://` explícitos.
- [ ] `VAULTPAY_TRUSTED_PROXY_COUNT` igual al número **real** de proxies delante de la API.
- [ ] Usuario de BD de la aplicación **sin** permisos `DROP`/`ALTER`/`TRIGGER`. Los triggers append-only los crea un rol de migración separado.
- [ ] Publicar periódicamente `head_hash` de `/api/admin/audit/verify` en almacenamiento WORM (ancla).
- [ ] Rotación de la clave de cifrado: nueva clave en `ENCRYPTION_KEY` y la anterior en `ENCRYPTION_KEYS_PREVIOUS`; re-cifrar y luego retirar la vieja.

## Limitaciones conocidas y roadmap

Este proyecto es una implementación de referencia. Estas son sus limitaciones actuales, sin maquillar:

| Limitación | Impacto | Siguiente paso |
|---|---|---|
| Rate limiter en memoria por proceso | Con N réplicas, el límite efectivo es N× | Backend Redis (la interfaz `RateLimiter.hit` ya lo permite) |
| JWT HS256 con secreto compartido | Cualquiera con el secreto puede emitir tokens | EdDSA/RS256 con clave en KMS y `kid` para rotación |
| Claves en variables de entorno | Exposición vía `/proc` o volcado del entorno | KMS / envelope encryption |
| Sin migraciones versionadas (se usa `create_all`) | Cambios de esquema manuales | Alembic, con los triggers en una migración |
| Sin verificación de e-mail ni recuperación de cuenta | El registro con e-mail ajeno no se notifica al dueño | Flujo de verificación y notificación por e-mail |
| Sin códigos de recuperación de MFA | Perder el dispositivo bloquea el step-up | Códigos de un solo uso (hasheados) |
| TOTP no es resistente a phishing | Phishing en tiempo real (AitM) | WebAuthn / passkeys |
| Sin chequeo contra contraseñas filtradas | Contraseñas expuestas en brechas | HIBP k-anonymity (opcional) |
| La auditoría serializa todas las escrituras (advisory lock) | Cuello de botella a gran escala | Particionar la cadena por día/tenant, o un escritor único vía outbox |
| Una sola moneda, sin FX ni contracargos | Alcance funcional | — |
| Imágenes Docker no construidas en el entorno de desarrollo de este repo (sin daemon) | El compose está validado con `docker compose config`, y nginx y la API se probaron fuera de contenedores | El job de CI puede agregar `docker build` + Trivy |

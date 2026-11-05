#!/usr/bin/env sh
# Prints fresh random secrets in .env format. Never commit the output.
set -eu
rand() { python3 -c "import secrets,base64,sys; print(base64.b64encode(secrets.token_bytes(int(sys.argv[1]))).decode())" "$1"; }
echo "POSTGRES_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
echo "VAULTPAY_JWT_SECRET=$(rand 48)"
echo "VAULTPAY_ENCRYPTION_KEY=$(rand 32)"

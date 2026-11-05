"""Money transfers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.deps import DB, CurrentUser, ip_of
from app.errors import domain_to_http
from app.schemas import IDEMPOTENCY_KEY_PATTERN, TransactionOut, TransferIn
from app.security.rate_limit import rate_limit
from app.services import ledger
from app.services.errors import DomainError

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


@router.post(
    "", response_model=TransactionOut, status_code=201,
    dependencies=[Depends(rate_limit("transfer", "rate_limit_transfer_per_minute", 60))],
)
def create_transfer(
    body: TransferIn,
    request: Request,
    user: CurrentUser,
    db: DB,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    # SEC-DATA-05: mandatory idempotency key for every money-moving call.
    if not idempotency_key or not IDEMPOTENCY_KEY_PATTERN.match(idempotency_key):
        raise domain_to_http(
            DomainError(400, "idempotency_key_required", "A valid Idempotency-Key header is required.")
        )
    try:
        tx, src, dst = ledger.transfer(
            db, user=user, from_account_id=body.from_account_id,
            to_account_number=body.to_account_number, amount_cents=body.amount_cents,
            description=body.description, idempotency_key=idempotency_key,
            otp_code=body.otp_code, ip=ip_of(request),
        )
    except DomainError as err:
        raise domain_to_http(err) from None
    return TransactionOut(
        id=tx.id, kind=tx.kind, amount_cents=tx.amount_cents, currency=tx.currency,
        description=tx.description, from_account=ledger.mask(src.account_number),
        to_account=ledger.mask(dst.account_number), created_at=tx.created_at,
    )

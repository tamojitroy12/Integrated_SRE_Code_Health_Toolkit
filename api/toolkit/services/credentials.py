"""Encrypted credential storage. Plaintext exists only in memory for the duration of use."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from toolkit.core.crypto import Sealed, get_keyring
from toolkit.db.models import Credential


def store_token(db: Session, token: str, created_by: uuid.UUID | None) -> Credential:
    cred_id = uuid.uuid4()
    sealed = get_keyring().encrypt(token, aad=f"credential:{cred_id}")
    cred = Credential(
        id=cred_id,
        kind="github_pat",
        ciphertext=sealed.ciphertext,
        nonce=sealed.nonce,
        key_id=sealed.key_id,
        created_by=created_by,
    )
    db.add(cred)
    return cred


def load_token(db: Session, credential_id: uuid.UUID | None) -> str | None:
    if credential_id is None:
        return None
    cred = db.get(Credential, credential_id)
    if cred is None:
        return None
    return get_keyring().decrypt(Sealed(cred.ciphertext, cred.nonce, cred.key_id), aad=f"credential:{cred.id}")

"""InviteCode model for closed-beta registration gate."""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class InviteCode(Base):
    """A single invite code that grants access to registration during closed beta.

    Fields
    ------
    code       Unique, human-readable string shown to invitees (e.g. "FICBETA-XXXX").
    is_enabled Toggle to disable a code without deleting it.
    max_uses   None = unlimited; any positive int = hard cap on registrations.
    use_count  Incremented atomically on each successful registration.
    note       Internal label (e.g. "batch-1", "alice's referral").
    """

    __tablename__ = "invite_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False, server_default="true")
    max_uses = Column(Integer, nullable=True)   # NULL = unlimited
    use_count = Column(Integer, default=0, nullable=False, server_default="0")
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

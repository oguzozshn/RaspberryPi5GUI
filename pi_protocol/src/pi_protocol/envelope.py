from __future__ import annotations

import time
import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from pi_protocol.constants import MessageType

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class Envelope(BaseModel, Generic[PayloadT]):
    """Wire format for every WS message: {"type", "id", "ts", "payload"}."""

    type: MessageType
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = Field(default_factory=time.time)
    payload: PayloadT


class ErrorPayload(BaseModel):
    code: str
    message: str

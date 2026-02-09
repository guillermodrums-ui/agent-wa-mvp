from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class ChannelType(str, Enum):
    SIMULATOR = "simulator"
    WHATSAPP = "whatsapp"
    # Future: INSTAGRAM = "instagram", TELEGRAM = "telegram"


@dataclass
class IncomingMessage:
    channel: ChannelType
    phone_number: str       # "5491166662222" (no @s.whatsapp.net)
    sender_name: str
    text: str
    timestamp: int
    message_id: str = ""
    raw_payload: dict | None = field(default=None, repr=False)


@dataclass
class OutgoingMessage:
    channel: ChannelType
    phone_number: str
    text: str


class BaseChannel(ABC):
    channel_type: ChannelType

    @abstractmethod
    async def send_message(self, message: OutgoingMessage) -> bool:
        ...

    @abstractmethod
    async def get_status(self) -> dict:
        ...

    @abstractmethod
    async def connect(self) -> dict:
        ...

    @abstractmethod
    async def disconnect(self) -> bool:
        ...

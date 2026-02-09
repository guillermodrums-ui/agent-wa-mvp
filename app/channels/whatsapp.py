import logging

import httpx

from app.channels.base import BaseChannel, ChannelType, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)


class WhatsAppChannel(BaseChannel):
    channel_type = ChannelType.WHATSAPP

    def __init__(self, api_url: str, api_key: str, instance_name: str = "laformula"):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.instance_name = instance_name
        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={"apikey": self.api_key},
            timeout=30.0,
        )

    async def connect(self) -> dict:
        """Create instance + get QR code for pairing."""
        # Create instance (idempotent — if it already exists, Evolution API returns it)
        try:
            create_resp = await self._client.post(
                "/instance/create",
                json={
                    "instanceName": self.instance_name,
                    "integration": "WHATSAPP-BAILEYS",
                    "qrcode": True,
                },
            )
            create_data = create_resp.json()
            logger.info("Instance create response: %s", create_resp.status_code)

            # If instance already exists, try to connect it
            if create_resp.status_code == 403 or (
                isinstance(create_data, dict) and "error" in create_data
            ):
                logger.info("Instance may already exist, trying to connect...")
        except Exception as e:
            logger.error("Error creating instance: %s", e)

        # Get QR code
        try:
            qr_resp = await self._client.get(
                f"/instance/connect/{self.instance_name}",
            )
            qr_data = qr_resp.json()
            return {
                "ok": True,
                "qr_base64": qr_data.get("base64", ""),
                "qr_code": qr_data.get("code", ""),
                "status": "connecting",
            }
        except Exception as e:
            logger.error("Error getting QR: %s", e)
            return {"ok": False, "error": str(e)}

    async def send_message(self, message: OutgoingMessage) -> bool:
        try:
            resp = await self._client.post(
                f"/message/sendText/{self.instance_name}",
                json={
                    "number": message.phone_number,
                    "text": message.text,
                },
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error("Error sending message to %s: %s", message.phone_number, e)
            return False

    async def get_status(self) -> dict:
        try:
            resp = await self._client.get(
                f"/instance/connectionState/{self.instance_name}",
            )
            data = resp.json()
            # Evolution API returns {"instance": {...}, "state": "open"/"close"/"connecting"}
            state = data.get("state", data.get("instance", {}).get("state", "unknown"))
            connected = state == "open"
            return {
                "connected": connected,
                "state": state,
                "instance_name": self.instance_name,
            }
        except httpx.ConnectError:
            return {"connected": False, "state": "evolution_api_unreachable", "instance_name": self.instance_name}
        except Exception as e:
            logger.error("Error getting status: %s", e)
            return {"connected": False, "state": "error", "error": str(e), "instance_name": self.instance_name}

    async def disconnect(self) -> bool:
        try:
            resp = await self._client.delete(
                f"/instance/logout/{self.instance_name}",
            )
            logger.info("Logout response: %s", resp.status_code)
            return True
        except Exception as e:
            logger.error("Error disconnecting: %s", e)
            return False

    def parse_webhook(self, payload: dict) -> IncomingMessage | None:
        """Parse Evolution API webhook payload into IncomingMessage.

        Returns None for events we don't handle (groups, own messages, non-text, etc.)
        """
        event = payload.get("event")

        # Only handle message upserts
        if event != "messages.upsert":
            return None

        data = payload.get("data", {})
        key = data.get("key", {})

        # Skip our own messages (avoid infinite loop)
        if key.get("fromMe", False):
            return None

        remote_jid = key.get("remoteJid", "")

        # Skip group messages
        if "@g.us" in remote_jid:
            return None

        # Extract phone number (remove @s.whatsapp.net)
        phone = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid

        # Extract message text
        message_data = data.get("message", {})
        text = (
            message_data.get("conversation")
            or message_data.get("extendedTextMessage", {}).get("text")
        )

        # Skip non-text messages (images, stickers, audio, etc.)
        if not text:
            return None

        # Extract sender name
        sender_name = data.get("pushName", "")

        # Message ID for deduplication
        message_id = key.get("id", "")

        # Timestamp
        timestamp = data.get("messageTimestamp", 0)
        if isinstance(timestamp, str):
            try:
                timestamp = int(timestamp)
            except ValueError:
                timestamp = 0

        return IncomingMessage(
            channel=ChannelType.WHATSAPP,
            phone_number=phone,
            sender_name=sender_name,
            text=text,
            timestamp=timestamp,
            message_id=message_id,
            raw_payload=payload,
        )

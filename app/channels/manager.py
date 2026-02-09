from app.channels.base import BaseChannel, ChannelType


class ChannelManager:
    """Registry and orchestration for communication channels."""

    def __init__(self):
        self._channels: dict[ChannelType, BaseChannel] = {}

    def register(self, channel: BaseChannel):
        self._channels[channel.channel_type] = channel

    def get(self, channel_type: ChannelType) -> BaseChannel | None:
        return self._channels.get(channel_type)

    async def get_all_statuses(self) -> dict[str, dict]:
        statuses = {}
        for ctype, channel in self._channels.items():
            statuses[ctype.value] = await channel.get_status()
        return statuses

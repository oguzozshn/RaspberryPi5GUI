from enum import Enum

PROTOCOL_VERSION = 1


class MessageType(str, Enum):
    """Wire values for Envelope.type. Extended as later phases add features."""

    AUTH_REQUEST = "auth.request"
    AUTH_OK = "auth.ok"
    AUTH_REJECTED = "auth.rejected"
    ERROR = "error"

    STATS_UPDATE = "stats.update"

    PROCESS_LIST = "process.list"
    PROCESS_LIST_RESULT = "process.list.result"

    FILES_LIST = "files.list"
    FILES_LIST_RESULT = "files.list.result"

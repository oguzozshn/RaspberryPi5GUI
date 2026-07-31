from enum import Enum

PROTOCOL_VERSION = 2


class MessageType(str, Enum):
    """Wire values for Envelope.type. Extended as later phases add features."""

    AUTH_REQUEST = "auth.request"
    AUTH_OK = "auth.ok"
    AUTH_REJECTED = "auth.rejected"
    ERROR = "error"

    STATS_UPDATE = "stats.update"

    PROCESS_LIST = "process.list"
    PROCESS_LIST_RESULT = "process.list.result"
    PROCESS_KILL = "process.kill"
    PROCESS_KILL_RESULT = "process.kill.result"

    FILES_LIST = "files.list"
    FILES_LIST_RESULT = "files.list.result"

    CHAT_SEND = "chat.send"
    CHAT_MESSAGE = "chat.message"
    CLIPBOARD_PULL = "clipboard.pull"

    SERVICE_LIST = "service.list"
    SERVICE_LIST_RESULT = "service.list.result"
    SERVICE_ACTION = "service.action"
    SERVICE_ACTION_RESULT = "service.action.result"
    SERVICE_LOGS = "service.logs"
    SERVICE_LOGS_RESULT = "service.logs.result"

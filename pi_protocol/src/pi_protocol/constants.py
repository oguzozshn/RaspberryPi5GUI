from enum import Enum

PROTOCOL_VERSION = 5


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

    POWER_ACTION = "power.action"
    POWER_ACTION_RESULT = "power.action.result"

    GPIO_LIST = "gpio.list"
    GPIO_LIST_RESULT = "gpio.list.result"
    GPIO_WRITE = "gpio.write"
    GPIO_WRITE_RESULT = "gpio.write.result"
    GPIO_RELEASE = "gpio.release"
    GPIO_RELEASE_RESULT = "gpio.release.result"

    DOCKER_LIST = "docker.list"
    DOCKER_LIST_RESULT = "docker.list.result"
    DOCKER_ACTION = "docker.action"
    DOCKER_ACTION_RESULT = "docker.action.result"
    DOCKER_LOGS = "docker.logs"
    DOCKER_LOGS_RESULT = "docker.logs.result"

    NETWORK_INFO = "network.info"
    NETWORK_INFO_RESULT = "network.info.result"

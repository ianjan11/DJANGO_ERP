import logging

from core.events.bus import EventBus

logger = logging.getLogger("core.events.system")


_event_bus = EventBus()


def register(event_type, handler):
    return _event_bus.register(event_type, handler)


def dispatch(event):

    logger.info(f"Dispatching event: {event.type}")

    return _event_bus.dispatch(event)


def get_bus():
    return _event_bus
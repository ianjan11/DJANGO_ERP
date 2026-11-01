import logging

logger = logging.getLogger("core.events.handlers")


class EventBus:

    def __init__(self):
        self.handlers = {}

    def register(self, event_type, handler):

        if event_type not in self.handlers:
            self.handlers[event_type] = []

        if handler not in self.handlers[event_type]:
            self.handlers[event_type].append(handler)

    def dispatch(self, event):

        handlers = self.handlers.get(event.type, [])

        results = []

        logger.info(f"Handler pipeline started for: {event.type}")

        if not handlers:
            logger.warning(f"No handlers registered for: {event.type}")
            return []

        for handler in handlers:

            handler_name = handler.__name__

            try:
                logger.info(f"Handler started: {handler_name}")

                result = handler(event)

                logger.info(f"Handler success: {handler_name}")

                results.append({
                    "handler": handler_name,
                    "status": "success",
                    "result": result
                })

            except Exception as e:

                logger.error(
                    f"Handler failed: {handler_name} | event={event.type} | error={e}"
                )

                results.append({
                    "handler": handler_name,
                    "status": "error",
                    "exception": str(e)
                })

        logger.info(f"Handler pipeline finished for: {event.type}")

        return results
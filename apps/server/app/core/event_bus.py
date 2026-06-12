from app.contracts.events import EventEnvelope


class EventBus:
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    def append(self, event: EventEnvelope) -> None:
        self.events.append(event)

    def recent(self, limit: int = 20) -> list[EventEnvelope]:
        return self.events[-limit:]


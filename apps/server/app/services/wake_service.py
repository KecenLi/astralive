from app.core.session_state import SessionState


class WakeService:
    def wake(self, session: SessionState) -> None:
        session.status = "listening"
        session.cost_meter.mode = "low_cost"

    def sleep(self, session: SessionState) -> None:
        session.status = "sleeping"
        session.cost_meter.mode = "sleep"


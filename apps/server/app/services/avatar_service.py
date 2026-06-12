from app.contracts.events import EventEnvelope, make_event


class AvatarService:
    def state_event(
        self,
        session_id: str,
        mode: str,
        expression: str = "neutral",
        subtitle: str = "",
        motion: str = "idle",
        lip_sync: bool = False,
    ) -> EventEnvelope:
        return make_event(
            "assistant.avatar.state",
            session_id,
            {
                "mode": mode,
                "expression": expression,
                "motion": motion,
                "subtitle": subtitle,
                "lip_sync": lip_sync,
            },
        )


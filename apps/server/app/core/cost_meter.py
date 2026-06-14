from pydantic import BaseModel


class CostMeter(BaseModel):
    frame_candidates: int = 0
    frames_uploaded: int = 0
    bytes_uploaded: int = 0
    vision_calls: int = 0
    llm_calls: int = 0
    asr_calls: int = 0
    tts_calls: int = 0
    client_deduped_frames: int = 0
    sleep_blocked_frames: int = 0
    scene_cache_hits: int = 0
    vision_calls_saved: int = 0
    stale_visual_results_discarded: int = 0
    voice_priority_deferred_frames: int = 0
    visual_cooldown_drops: int = 0
    visual_pending_drops: int = 0
    visual_confidence_low_count: int = 0
    focus_requests: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_cost_usd: float | None = 0.0
    estimated_visual_cost_saved_usd: float | None = 0.0
    mode: str = "sleep"
    last_latency_ms: int | None = None

    def add_frame_candidate(self, count: int = 1) -> None:
        self.frame_candidates += max(0, int(count))

    def add_frame(self, encoded_size: int) -> None:
        self.frames_uploaded += 1
        self.bytes_uploaded += encoded_size

    def add_saved_vision_call(self, *, cost_usd: float | None = 0.0, count: int = 1) -> None:
        saved = max(0, int(count))
        self.vision_calls_saved += saved
        if cost_usd is not None and self.estimated_visual_cost_saved_usd is not None:
            self.estimated_visual_cost_saved_usd = round(
                self.estimated_visual_cost_saved_usd + max(0.0, float(cost_usd)) * saved,
                10,
            )

    def add_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float | None = 0.0,
        call_type: str | None = None,
    ) -> None:
        self.estimated_input_tokens += max(0, int(input_tokens))
        self.estimated_output_tokens += max(0, int(output_tokens))
        if cost_usd is not None and self.estimated_cost_usd is not None:
            self.estimated_cost_usd = round(self.estimated_cost_usd + max(0.0, float(cost_usd)), 10)

        if call_type == "vision":
            self.vision_calls += 1
        elif call_type == "llm":
            self.llm_calls += 1
        elif call_type == "asr":
            self.asr_calls += 1
        elif call_type == "tts":
            self.tts_calls += 1

    def add_estimate(self, estimate: object, *, call_type: str | None = None) -> None:
        self.add_usage(
            input_tokens=getattr(estimate, "input_tokens", 0),
            output_tokens=getattr(estimate, "output_tokens", 0),
            cost_usd=getattr(estimate, "cost_usd", None),
            call_type=call_type,
        )

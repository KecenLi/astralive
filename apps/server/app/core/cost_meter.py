from pydantic import BaseModel


class CostMeter(BaseModel):
    frames_uploaded: int = 0
    bytes_uploaded: int = 0
    vision_calls: int = 0
    llm_calls: int = 0
    asr_calls: int = 0
    tts_calls: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_cost_usd: float | None = 0.0
    mode: str = "sleep"
    last_latency_ms: int | None = None

    def add_frame(self, encoded_size: int) -> None:
        self.frames_uploaded += 1
        self.bytes_uploaded += encoded_size


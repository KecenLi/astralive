from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "app": get_settings().app_name}


@router.get("/api/config/public")
async def public_config() -> dict:
    settings = get_settings()
    return {
        "app_name": settings.app_name,
        "wake_word": settings.wake_word,
        "providers": {
            "asr": settings.asr_provider,
            "vision": settings.vision_provider,
            "llm": settings.llm_provider,
            "tts": settings.tts_provider,
        },
        "media": {
            "frame_jpeg_quality": settings.frame_jpeg_quality,
            "max_frame_width": settings.max_frame_width,
            "max_frame_height": settings.max_frame_height,
            "vision_cache_ttl_seconds": settings.vision_cache_ttl_seconds,
            "scene_change_threshold": settings.scene_change_threshold,
        },
    }


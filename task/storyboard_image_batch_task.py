"""Scheduler task for storyboard image batch orchestration."""
import logging

from services.storyboard_agent_cli_service import StoryboardAgentCliService

logger = logging.getLogger(__name__)


def process_storyboard_image_batch_tasks(app=None):
    """Advance storyboard image batch jobs without blocking web request handlers."""
    try:
        service = StoryboardAgentCliService()
        result = service.process_image_batch_jobs()
        processed = int(result.get("processed_count") or 0)
        submitted = int(result.get("submitted_count") or 0)
        if processed or submitted:
            logger.info(
                "Processed storyboard image batch jobs: processed=%s submitted=%s",
                processed,
                submitted,
            )
        return result
    except Exception as exc:
        logger.error("Failed to process storyboard image batch jobs: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}

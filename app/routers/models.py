from fastapi import APIRouter, BackgroundTasks, Query
from app.services.model_retrainer import get_model_status, run_retraining_pipeline, check_and_trigger_async

router = APIRouter(prefix="/api/models", tags=["Quantitative Models"])

@router.get("/status")
def get_status():
    """Retrieve active ML model metadata, accuracy, sample count, and training status."""
    return get_model_status()

@router.post("/retrain")
def trigger_retraining(
    background_tasks: BackgroundTasks,
    force: bool = Query(True, description="Force retrain even if minimal sample threshold not met"),
    min_new_samples: int = Query(5, description="Minimum new resolved samples required to trigger training")
):
    """Trigger background model retraining across all database and CSV signal outcomes."""
    check_and_trigger_async(force=force, min_new_samples=min_new_samples)
    return {
        "status": "QUEUED",
        "message": "Model retraining pipeline initiated in background.",
        "force": force
    }

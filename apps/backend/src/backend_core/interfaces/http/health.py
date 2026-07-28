from backend_core.platform.database import Database
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Database unavailable"}
    },
)
async def ready(request: Request) -> dict[str, str]:
    database: Database = request.app.state.database

    try:
        await database.ping()
    except (SQLAlchemyError, OSError, TimeoutError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from error

    return {"status": "ok"}

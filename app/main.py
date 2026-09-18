import logging
import sys
from pathlib import Path

# Ensure project root directory is in sys.path when executed directly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.models import (
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
    HealthResponse
)
from app.interpreter import interpret_operator_notes
from app.optimizer import solve_energy_schedule
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="LLM-Assisted Smart Campus Energy Optimization API for GridWise Challenge"
)

# Custom exception handler for 400 bad request on validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Request validation error for {request.url}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Malformed request body or schema validation error."}
    )

# Custom exception handler for 500 internal server errors (prevents secret/stack trace leakage)
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled internal server error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error occurred."}
    )

@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint welcoming visitors and directing to /health and /optimize-energy."""
    return {
        "service": settings.APP_NAME,
        "status": "online",
        "health_check": "/health",
        "primary_endpoint": "POST /optimize-energy"
    }

@app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check():
    """Readiness probe endpoint for judging harness."""
    return HealthResponse(status="ok")

@app.post("/optimize-energy", response_model=OptimizeEnergyResponse, status_code=status.HTTP_200_OK)
async def optimize_energy(request: OptimizeEnergyRequest):
    """
    Main energy scheduling & optimization endpoint.
    1. Interprets operator_notes using LLM / Guardrails / Fallback interpreter.
    2. Formulates and solves 24-hour Linear Program for cost minimization.
    3. Returns canonical interpretation and 24-hour hourly plan.
    """
    try:
        # Step 1: LLM Directive Interpretation + Guardrail Engine
        directives = interpret_operator_notes(
            operator_notes=request.operator_notes,
            battery=request.battery
        )

        # Step 2: Linear Programming Optimization
        response = solve_energy_schedule(
            request=request,
            directives=directives
        )

        return response

    except ValueError as ve:
        logger.warning(f"Optimization / input logic error: {ve}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Unexpected error during optimization: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute energy optimization plan."
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)

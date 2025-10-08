"""HTTP API endpoints for strategy optimisation runs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from gateway.config import settings

from ..nautilus_service import svc
from ..strategy_tester import (
    OptimisationDirection,
    StrategyOptimisationPlan,
    StrategyTestRunStatus,
)


router = APIRouter(prefix="/strategy-tests", tags=["strategy-tests"])


class StrategyTestRunRequest(BaseModel):
    name: str = Field(..., max_length=120)
    base_config: Dict[str, Any] = Field(..., alias="baseConfig")
    parameter_space: Dict[str, List[Any]] = Field(..., alias="parameterSpace")
    plan: StrategyOptimisationPlan = StrategyOptimisationPlan.GRID
    sample_count: Optional[int] = Field(None, alias="sampleCount", gt=0)
    max_parallel: Optional[int] = Field(None, alias="maxParallel", gt=0)
    optimisation_metric: Optional[str] = Field(
        default="sharpe_ratio", alias="optimisationMetric", max_length=64
    )
    optimisation_direction: OptimisationDirection = Field(
        default=OptimisationDirection.MAXIMIZE, alias="optimisationDirection"
    )
    random_seed: Optional[int] = Field(None, alias="randomSeed")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("max_parallel")
    @classmethod
    def _validate_parallel(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if value > settings.engine.max_nodes:
            raise ValueError(
                f"maxParallel cannot exceed configured engine limit {settings.engine.max_nodes}"
            )
        return value


class StrategyTestResultResource(BaseModel):
    id: str
    position: int
    parameters: Dict[str, Any]
    metrics: Dict[str, Any] = Field(default_factory=dict)
    optimisation_score: Optional[float] = Field(None, alias="optimisationScore")
    status: StrategyTestRunStatus
    node_id: Optional[str] = Field(None, alias="nodeId")
    error: Optional[str] = None
    started_at: Optional[str] = Field(None, alias="startedAt")
    completed_at: Optional[str] = Field(None, alias="completedAt")

    model_config = ConfigDict(populate_by_name=True)


class StrategyTestRunResource(BaseModel):
    id: str
    name: str
    plan: StrategyOptimisationPlan
    status: StrategyTestRunStatus
    optimisation_metric: Optional[str] = Field(None, alias="optimisationMetric")
    optimisation_direction: Optional[str] = Field(None, alias="optimisationDirection")
    total_jobs: int = Field(..., alias="totalJobs")
    completed_jobs: int = Field(..., alias="completedJobs")
    failed_jobs: int = Field(..., alias="failedJobs")
    running_jobs: int = Field(..., alias="runningJobs")
    progress: float
    created_at: str = Field(..., alias="createdAt")
    updated_at: str = Field(..., alias="updatedAt")
    started_at: Optional[str] = Field(None, alias="startedAt")
    completed_at: Optional[str] = Field(None, alias="completedAt")
    error: Optional[str] = None
    best_result: Optional[StrategyTestResultResource] = Field(
        default=None, alias="bestResult"
    )
    results: Optional[List[StrategyTestResultResource]] = None

    model_config = ConfigDict(populate_by_name=True)


class StrategyTestRunResponse(BaseModel):
    run: StrategyTestRunResource


class StrategyTestRunListResponse(BaseModel):
    runs: List[StrategyTestRunResource]


@router.post("", response_model=StrategyTestRunResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy_test_run(payload: StrategyTestRunRequest) -> StrategyTestRunResponse:
    try:
        run = await svc.strategy_tester.start_run(
            name=payload.name,
            base_config=payload.base_config,
            parameter_space=payload.parameter_space,
            plan=payload.plan,
            sample_count=payload.sample_count,
            max_parallel=payload.max_parallel,
            optimisation_metric=payload.optimisation_metric,
            direction=payload.optimisation_direction,
            random_seed=payload.random_seed,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    snapshot = await svc.strategy_tester.get_run(run.id)
    if snapshot is None:  # pragma: no cover - defensive guard
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Run state unavailable")
    return StrategyTestRunResponse(run=StrategyTestRunResource.model_validate(snapshot))


@router.get("", response_model=StrategyTestRunListResponse)
async def list_strategy_test_runs() -> StrategyTestRunListResponse:
    runs = await svc.strategy_tester.list_runs()
    resources = [StrategyTestRunResource.model_validate(item) for item in runs]
    return StrategyTestRunListResponse(runs=resources)


@router.get("/{run_id}", response_model=StrategyTestRunResponse)
async def get_strategy_test_run(run_id: str) -> StrategyTestRunResponse:
    run = await svc.strategy_tester.get_run(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")
    return StrategyTestRunResponse(run=StrategyTestRunResource.model_validate(run))

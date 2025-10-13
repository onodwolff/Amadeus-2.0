"""Strategy optimisation orchestration for running multiple backtests."""

from __future__ import annotations

import asyncio
import logging
import math
import random
import uuid
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

try:  # pragma: no cover - prefer local backend package in tests
    from backend.gateway.config import settings  # type: ignore
    from backend.gateway.db.base import create_session  # type: ignore
    from backend.gateway.db.models import BacktestRun, BacktestRunStatus  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - production installs
    from gateway.config import settings
    from gateway.db.base import create_session
    from gateway.db.models import BacktestRun, BacktestRunStatus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .nautilus_service import NautilusService


LOGGER = logging.getLogger("gateway.strategy_tester")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StrategyOptimisationPlan(str, Enum):
    GRID = "grid"
    RANDOM = "random"


class OptimisationDirection(str, Enum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class StrategyTestRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StrategyTestResult:
    """In-memory representation of a single optimisation job."""

    id: str
    position: int
    parameters: Dict[str, Any]
    config: Dict[str, Any]
    status: StrategyTestRunStatus = StrategyTestRunStatus.PENDING
    node_id: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    optimisation_score: Optional[float] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class StrategyTestRun:
    """Container tracking the lifecycle of an optimisation request."""

    id: str
    name: str
    plan: StrategyOptimisationPlan
    direction: OptimisationDirection
    optimisation_metric: Optional[str]
    parameter_space: Dict[str, List[Any]]
    base_config: Dict[str, Any]
    max_parallel: int
    sample_count: Optional[int] = None
    random_seed: Optional[int] = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    status: StrategyTestRunStatus = StrategyTestRunStatus.PENDING
    results: List[StrategyTestResult] = field(default_factory=list)
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    running_jobs: int = 0
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None

    @property
    def best_result(self) -> Optional[StrategyTestResult]:
        candidates = [
            result
            for result in self.results
            if result.optimisation_score is not None
            and result.status == StrategyTestRunStatus.COMPLETED
        ]
        if not candidates:
            return None
        reverse = self.direction == OptimisationDirection.MAXIMIZE
        return sorted(
            candidates,
            key=lambda item: item.optimisation_score or (-math.inf if reverse else math.inf),
            reverse=reverse,
        )[0]


class StrategyTester:
    """Coordinate bulk backtest execution for strategy optimisation."""

    def __init__(self, service: "NautilusService") -> None:
        self._service = service
        self._runs: Dict[str, StrategyTestRun] = {}
        self._runs_lock = asyncio.Lock()
        self._max_nodes = settings.engine.max_nodes
        self._poll_interval = 2.0
        self._max_poll_attempts = 60

    async def start_run(
        self,
        *,
        name: str,
        base_config: Dict[str, Any],
        parameter_space: Dict[str, Iterable[Any]],
        plan: StrategyOptimisationPlan,
        sample_count: Optional[int],
        max_parallel: Optional[int],
        optimisation_metric: Optional[str],
        direction: OptimisationDirection,
        random_seed: Optional[int] = None,
    ) -> StrategyTestRun:
        """Create and schedule a new optimisation run."""

        normalised_space: Dict[str, List[Any]] = {}
        for key, values in parameter_space.items():
            candidates = [value for value in values if value is not None]
            if not candidates:
                raise ValueError(f"Parameter '{key}' does not contain any candidates")
            normalised_space[key] = candidates

        run_id = uuid.uuid4().hex
        effective_parallel = min(max_parallel or self._max_nodes, self._max_nodes)
        run = StrategyTestRun(
            id=run_id,
            name=name,
            plan=plan,
            direction=direction,
            optimisation_metric=optimisation_metric,
            parameter_space=normalised_space,
            base_config=deepcopy(base_config),
            max_parallel=max(1, effective_parallel),
            sample_count=sample_count,
            random_seed=random_seed,
        )

        async with self._runs_lock:
            self._runs[run_id] = run

        run.task = asyncio.create_task(self._execute_run(run))
        return run

    async def list_runs(self) -> List[Dict[str, Any]]:
        """Return summaries for active and historical optimisation runs."""

        summaries: Dict[str, Dict[str, Any]] = {}

        async with self._runs_lock:
            for run in self._runs.values():
                summaries[run.id] = self._serialize_run(run, include_results=False)

        async with self._session() as session:
            stmt = (
                select(
                    BacktestRun.run_id,
                    func.max(BacktestRun.name).label("name"),
                    func.max(BacktestRun.plan).label("plan"),
                    func.max(BacktestRun.optimisation_metric).label("metric"),
                    func.max(BacktestRun.optimisation_direction).label("direction"),
                    func.count().label("total"),
                    func.count(
                        case((BacktestRun.status == BacktestRunStatus.COMPLETED, 1))
                    ).label("completed"),
                    func.count(
                        case((BacktestRun.status == BacktestRunStatus.FAILED, 1))
                    ).label("failed"),
                    func.min(BacktestRun.started_at).label("started_at"),
                    func.max(BacktestRun.completed_at).label("completed_at"),
                    func.max(BacktestRun.created_at).label("created_at"),
                    func.max(BacktestRun.updated_at).label("updated_at"),
                )
                .group_by(BacktestRun.run_id)
            )
            result = await session.execute(stmt)
            for row in result:
                run_id = row.run_id
                if run_id in summaries:
                    continue
                summaries[run_id] = {
                    "id": run_id,
                    "name": row.name,
                    "plan": row.plan,
                    "status": (
                        StrategyTestRunStatus.COMPLETED.value
                        if row.completed == row.total
                        else StrategyTestRunStatus.RUNNING.value
                    ),
                    "optimisationMetric": row.metric,
                    "optimisationDirection": row.direction,
                    "totalJobs": row.total,
                    "completedJobs": row.completed,
                    "failedJobs": row.failed,
                    "runningJobs": max(0, row.total - row.completed - row.failed),
                    "createdAt": (row.created_at or _utcnow()).isoformat(),
                    "updatedAt": (row.updated_at or row.created_at or _utcnow()).isoformat(),
                    "startedAt": row.started_at.isoformat() if row.started_at else None,
                    "completedAt": row.completed_at.isoformat()
                    if row.completed_at
                    else None,
                    "progress": (row.completed / row.total) if row.total else 0.0,
                }

            for run_id, payload in summaries.items():
                if payload.get("bestResult"):
                    continue
                direction = str(payload.get("optimisationDirection") or OptimisationDirection.MAXIMIZE.value)
                order_by = BacktestRun.optimisation_score.desc()
                if direction == OptimisationDirection.MINIMIZE.value:
                    order_by = BacktestRun.optimisation_score.asc()
                best_stmt = (
                    select(BacktestRun)
                    .where(
                        BacktestRun.run_id == run_id,
                        BacktestRun.optimisation_score.is_not(None),
                        BacktestRun.status == BacktestRunStatus.COMPLETED,
                    )
                    .order_by(order_by)
                    .limit(1)
                )
                best_result = await session.execute(best_stmt)
                record = best_result.scalars().first()
                if record is None:
                    continue
                payload["bestResult"] = {
                    "id": f"{record.run_id}-{record.position}",
                    "position": record.position,
                    "parameters": record.parameters,
                    "metrics": record.metrics,
                    "optimisationScore": float(record.optimisation_score)
                    if record.optimisation_score is not None
                    else None,
                    "status": record.status.value,
                    "nodeId": record.node_id,
                    "startedAt": record.started_at.isoformat() if record.started_at else None,
                    "completedAt": record.completed_at.isoformat() if record.completed_at else None,
                }

        return sorted(summaries.values(), key=lambda item: item["createdAt"], reverse=True)

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return a detailed view for *run_id* if available."""

        async with self._runs_lock:
            run = self._runs.get(run_id)
            if run is not None:
                return self._serialize_run(run, include_results=True)

        async with self._session() as session:
            stmt = (
                select(BacktestRun)
                .where(BacktestRun.run_id == run_id)
                .order_by(BacktestRun.position.asc())
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            if not records:
                return None

            results_payload = [
                {
                    "id": f"{record.run_id}-{record.position}",
                    "position": record.position,
                    "parameters": record.parameters,
                    "metrics": record.metrics,
                    "status": record.status.value,
                    "optimisationScore": float(record.optimisation_score)
                    if record.optimisation_score is not None
                    else None,
                    "nodeId": record.node_id,
                    "error": record.error,
                    "startedAt": record.started_at.isoformat() if record.started_at else None,
                    "completedAt": record.completed_at.isoformat()
                    if record.completed_at
                    else None,
                }
                for record in records
            ]

            best_result = self._select_best(records)

            return {
                "id": run_id,
                "name": records[0].name,
                "plan": records[0].plan,
                "status": self._aggregate_status(records).value,
                "optimisationMetric": records[0].optimisation_metric,
                "optimisationDirection": records[0].optimisation_direction,
                "totalJobs": len(records),
                "completedJobs": sum(1 for item in records if item.status == BacktestRunStatus.COMPLETED),
                "failedJobs": sum(1 for item in records if item.status == BacktestRunStatus.FAILED),
                "runningJobs": sum(1 for item in records if item.status == BacktestRunStatus.RUNNING),
                "createdAt": records[0].created_at.isoformat() if records[0].created_at else None,
                "updatedAt": records[-1].updated_at.isoformat() if records[-1].updated_at else None,
                "startedAt": records[0].started_at.isoformat() if records[0].started_at else None,
                "completedAt": records[-1].completed_at.isoformat() if records[-1].completed_at else None,
                "progress": (
                    sum(1 for item in records if item.status == BacktestRunStatus.COMPLETED)
                    / len(records)
                    if records
                    else 0.0
                ),
                "bestResult": best_result,
                "results": results_payload,
            }

    async def _execute_run(self, run: StrategyTestRun) -> None:
        try:
            combinations = self._build_combinations(run)
        except Exception as exc:  # pragma: no cover - defensive guard
            LOGGER.exception("strategy_test_combination_generation_failed", extra={"run_id": run.id})
            run.status = StrategyTestRunStatus.FAILED
            run.error = str(exc)
            run.updated_at = _utcnow()
            return

        if not combinations:
            run.status = StrategyTestRunStatus.FAILED
            run.error = "No parameter combinations generated"
            run.updated_at = _utcnow()
            return

        run.total_jobs = len(combinations)
        run.updated_at = _utcnow()

        semaphore = asyncio.Semaphore(run.max_parallel)
        tasks: List[asyncio.Task] = []

        for position, parameters in enumerate(combinations, start=1):
            job = StrategyTestResult(
                id=f"{run.id}-{position}",
                position=position,
                parameters=parameters,
                config=self._apply_parameters(run.base_config, parameters),
            )
            run.results.append(job)

            task = asyncio.create_task(self._execute_job(run, job, semaphore))
            tasks.append(task)

        run.status = StrategyTestRunStatus.RUNNING
        run.updated_at = _utcnow()

        try:
            await asyncio.gather(*tasks)
        except Exception as exc:  # pragma: no cover - defensive guard
            LOGGER.exception("strategy_test_run_failed", extra={"run_id": run.id})
            run.status = StrategyTestRunStatus.FAILED
            run.error = str(exc)
            run.updated_at = _utcnow()
            return

        run.status = StrategyTestRunStatus.COMPLETED
        if run.failed_jobs and run.completed_jobs == 0:
            run.status = StrategyTestRunStatus.FAILED
        run.updated_at = _utcnow()

        async with self._runs_lock:
            # Persist completed runs in memory only while they are active.
            self._runs.pop(run.id, None)

    async def _execute_job(
        self,
        run: StrategyTestRun,
        job: StrategyTestResult,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            job.started_at = _utcnow()
            job.status = StrategyTestRunStatus.RUNNING
            run.running_jobs += 1
            run.updated_at = _utcnow()

            try:
                handle = await asyncio.to_thread(
                    self._service.start_backtest,
                    config=job.config,
                    detail=f"Optimisation run {run.name} [{job.position}]",
                )
                job.node_id = handle.id
                metrics = await self._collect_metrics(handle.id)
                job.metrics = metrics
                job.optimisation_score = self._extract_metric(metrics, run.optimisation_metric)
                job.status = StrategyTestRunStatus.COMPLETED
                job.completed_at = _utcnow()
                run.completed_jobs += 1
            except Exception as exc:  # pragma: no cover - best effort logging
                LOGGER.exception(
                    "strategy_test_job_failed",
                    extra={"run_id": run.id, "position": job.position},
                )
                job.status = StrategyTestRunStatus.FAILED
                job.error = str(exc)
                job.completed_at = _utcnow()
                run.failed_jobs += 1
            finally:
                run.running_jobs = max(0, run.running_jobs - 1)
                run.updated_at = _utcnow()
                await self._persist_job(run, job)

    async def _collect_metrics(self, node_id: str) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        status: Optional[str] = None

        for attempt in range(self._max_poll_attempts):
            try:
                detail = await asyncio.to_thread(self._service.node_detail, node_id)
            except Exception:
                break
            node = detail.get("node") or {}
            status = str(node.get("status") or "").lower()
            metrics = node.get("metrics") or metrics
            if status in {"stopped", "error"}:
                break
            await asyncio.sleep(self._poll_interval)

        try:
            handle = await asyncio.to_thread(self._service.stop_node, node_id)
        except Exception:  # pragma: no cover - defensive guard
            handle = None

        if handle and getattr(handle, "metrics", None):
            metrics = handle.metrics

        if not metrics:
            LOGGER.debug("strategy_test_metrics_missing", extra={"node_id": node_id, "status": status})

        return metrics or {}

    async def _persist_job(self, run: StrategyTestRun, job: StrategyTestResult) -> None:
        async with self._session() as session:
            existing = await session.execute(
                select(BacktestRun).where(
                    BacktestRun.run_id == run.id, BacktestRun.position == job.position
                )
            )
            record = existing.scalars().first()
            if record is None:
                record = BacktestRun(
                    run_id=run.id,
                    name=run.name,
                    plan=run.plan.value,
                    status=BacktestRunStatus(job.status.value),
                    position=job.position,
                    parameters=job.parameters,
                    base_config=job.config,
                    metrics=job.metrics,
                    optimisation_metric=run.optimisation_metric,
                    optimisation_direction=run.direction.value,
                    optimisation_score=self._as_decimal(job.optimisation_score),
                    node_id=job.node_id,
                    error=job.error,
                    started_at=job.started_at,
                    completed_at=job.completed_at,
                )
                session.add(record)
            else:
                record.status = BacktestRunStatus(job.status.value)
                record.parameters = job.parameters
                record.base_config = job.config
                record.metrics = job.metrics
                record.optimisation_metric = run.optimisation_metric
                record.optimisation_direction = run.direction.value
                record.optimisation_score = self._as_decimal(job.optimisation_score)
                record.node_id = job.node_id
                record.error = job.error
                record.started_at = job.started_at
                record.completed_at = job.completed_at
                record.updated_at = _utcnow()
            await session.commit()

    def _build_combinations(self, run: StrategyTestRun) -> List[Dict[str, Any]]:
        keys = sorted(run.parameter_space.keys())
        space = [run.parameter_space[key] for key in keys]

        if run.plan == StrategyOptimisationPlan.GRID:
            return [dict(zip(keys, values)) for values in self._product(*space)]

        population = [dict(zip(keys, values)) for values in self._product(*space)]
        sample_size = run.sample_count or len(population)
        if sample_size >= len(population):
            return population

        rng = random.Random(run.random_seed)
        return rng.sample(population, sample_size)

    def _apply_parameters(
        self, base_config: Dict[str, Any], parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        config = deepcopy(base_config)
        for path, value in parameters.items():
            if path.startswith("strategy.parameters."):
                param_key = path.split(".", 2)[-1]
                self._set_strategy_parameter(config, param_key, value)
            else:
                self._set_nested_value(config, path.split("."), value)
        return config

    def _set_strategy_parameter(self, config: Dict[str, Any], key: str, value: Any) -> None:
        strategy = config.setdefault("strategy", {})
        parameters = strategy.setdefault("parameters", [])
        for entry in parameters:
            if isinstance(entry, dict) and entry.get("key") == key:
                entry["value"] = value
                return
        parameters.append({"key": key, "value": value})

    def _set_nested_value(self, target: Dict[str, Any], path: Iterable[str], value: Any) -> None:
        parts = list(path)
        cursor: Any = target
        for part in parts[:-1]:
            if isinstance(cursor, list):
                index = int(part)
                while len(cursor) <= index:
                    cursor.append({})
                cursor = cursor[index]
            else:
                cursor = cursor.setdefault(part, {})
        final_key = parts[-1]
        if isinstance(cursor, list):
            index = int(final_key)
            while len(cursor) <= index:
                cursor.append(None)
            cursor[index] = value
        else:
            cursor[final_key] = value

    def _extract_metric(
        self, metrics: Dict[str, Any], metric_key: Optional[str]
    ) -> Optional[float]:
        if not metric_key:
            return None
        value = metrics.get(metric_key)
        if value is None and "metrics" in metrics:
            nested = metrics.get("metrics")
            if isinstance(nested, dict):
                value = nested.get(metric_key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _serialize_run(self, run: StrategyTestRun, *, include_results: bool) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": run.id,
            "name": run.name,
            "plan": run.plan.value,
            "status": run.status.value,
            "optimisationMetric": run.optimisation_metric,
            "optimisationDirection": run.direction.value,
            "totalJobs": run.total_jobs,
            "completedJobs": run.completed_jobs,
            "failedJobs": run.failed_jobs,
            "runningJobs": run.running_jobs,
            "createdAt": run.created_at.isoformat(),
            "updatedAt": run.updated_at.isoformat(),
            "progress": (run.completed_jobs / run.total_jobs) if run.total_jobs else 0.0,
            "error": run.error,
        }
        best = run.best_result
        if best is not None:
            payload["bestResult"] = {
                "id": best.id,
                "position": best.position,
                "parameters": best.parameters,
                "metrics": best.metrics,
                "optimisationScore": best.optimisation_score,
                "status": best.status.value,
                "nodeId": best.node_id,
                "startedAt": best.started_at.isoformat() if best.started_at else None,
                "completedAt": best.completed_at.isoformat() if best.completed_at else None,
            }
        if include_results:
            payload["results"] = [
                {
                    "id": result.id,
                    "position": result.position,
                    "parameters": result.parameters,
                    "metrics": result.metrics,
                    "optimisationScore": result.optimisation_score,
                    "status": result.status.value,
                    "nodeId": result.node_id,
                    "error": result.error,
                    "startedAt": result.started_at.isoformat() if result.started_at else None,
                    "completedAt": result.completed_at.isoformat() if result.completed_at else None,
                }
                for result in sorted(run.results, key=lambda item: item.position)
            ]
        return payload

    def _aggregate_status(self, records: Iterable[BacktestRun]) -> StrategyTestRunStatus:
        statuses = {record.status for record in records}
        if BacktestRunStatus.FAILED in statuses and BacktestRunStatus.COMPLETED not in statuses:
            return StrategyTestRunStatus.FAILED
        if BacktestRunStatus.RUNNING in statuses:
            return StrategyTestRunStatus.RUNNING
        if BacktestRunStatus.PENDING in statuses:
            return StrategyTestRunStatus.PENDING
        return StrategyTestRunStatus.COMPLETED

    def _select_best(self, records: List[BacktestRun]) -> Optional[Dict[str, Any]]:
        if not records:
            return None

        metric = records[0].optimisation_metric
        direction = records[0].optimisation_direction or OptimisationDirection.MAXIMIZE.value
        if not metric:
            return None

        completed = [
            record
            for record in records
            if record.status == BacktestRunStatus.COMPLETED and record.optimisation_score is not None
        ]
        if not completed:
            return None

        reverse = direction == OptimisationDirection.MAXIMIZE.value
        selected = sorted(
            completed,
            key=lambda item: float(item.optimisation_score),
            reverse=reverse,
        )[0]

        return {
            "id": f"{selected.run_id}-{selected.position}",
            "position": selected.position,
            "parameters": selected.parameters,
            "metrics": selected.metrics,
            "optimisationScore": float(selected.optimisation_score)
            if selected.optimisation_score is not None
            else None,
            "status": selected.status.value,
            "nodeId": selected.node_id,
            "startedAt": selected.started_at.isoformat() if selected.started_at else None,
            "completedAt": selected.completed_at.isoformat() if selected.completed_at else None,
        }

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        session = create_session()
        try:
            yield session
        finally:
            await session.close()

    @staticmethod
    def _as_decimal(value: Optional[float]) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:  # pragma: no cover - defensive guard
            return None

    @staticmethod
    def _product(*values: Iterable[Any]) -> Iterable[Tuple[Any, ...]]:
        if not values:
            return []
        pools: List[List[Any]] = [list(pool) for pool in values]
        if any(not pool for pool in pools):
            return []
        indices = [0] * len(pools)
        yield tuple(pool[0] for pool in pools)
        while True:
            for idx in reversed(range(len(pools))):
                indices[idx] += 1
                if indices[idx] < len(pools[idx]):
                    yield tuple(pools[i][indices[i]] for i in range(len(pools)))
                    break
                indices[idx] = 0
                if idx == 0:
                    return

import random
from datetime import timedelta

import pytest

from backend.gateway.app.strategy_tester import (
    OptimisationDirection,
    StrategyOptimisationPlan,
    StrategyTestResult,
    StrategyTestRun,
    StrategyTestRunStatus,
    StrategyTester,
    _utcnow,
)


class DummyService:
    """Minimal Nautilus service stub used by the strategy tester tests."""

    def __getattr__(self, name):  # pragma: no cover - defensive guard
        raise AssertionError(f"Unexpected attribute access: {name}")


@pytest.fixture
def tester() -> StrategyTester:
    return StrategyTester(service=DummyService())


def _create_run(**overrides) -> StrategyTestRun:
    defaults = dict(
        id="run-1",
        name="Test run",
        plan=StrategyOptimisationPlan.GRID,
        direction=OptimisationDirection.MAXIMIZE,
        optimisation_metric="sharpe",
        parameter_space={"alpha": [1, 2], "beta": ["x", "y"]},
        base_config={"strategy": {"parameters": []}},
        max_parallel=2,
    )
    defaults.update(overrides)
    return StrategyTestRun(**defaults)


def test_build_combinations_grid_enumerates_cartesian_product(tester: StrategyTester) -> None:
    run = _create_run()

    combinations = tester._build_combinations(run)

    assert combinations == [
        {"alpha": 1, "beta": "x"},
        {"alpha": 1, "beta": "y"},
        {"alpha": 2, "beta": "x"},
        {"alpha": 2, "beta": "y"},
    ]


def test_build_combinations_random_sampling_is_deterministic(tester: StrategyTester) -> None:
    run = _create_run(
        plan=StrategyOptimisationPlan.RANDOM,
        sample_count=3,
        random_seed=7,
    )

    combinations = tester._build_combinations(run)

    # Build the expected sample using the same deterministic RNG configuration.
    keys = sorted(run.parameter_space.keys())
    population = [dict(zip(keys, values)) for values in tester._product(*[run.parameter_space[key] for key in keys])]
    expected = random.Random(run.random_seed).sample(population, 3)

    assert combinations == expected
    # Running the sampler again with the same seed should yield identical results.
    assert combinations == tester._build_combinations(run)


def test_apply_parameters_updates_strategy_and_nested_paths(tester: StrategyTester) -> None:
    base_config = {
        "strategy": {"parameters": [{"key": "ma_window", "value": 10}]},
        "engine": {"risk": {"maxDrawdown": 0.1}},
        "pairs": [
            {"symbol": "BTC/USDT", "enabled": True},
        ],
    }
    parameters = {
        "strategy.parameters.ma_window": 20,
        "strategy.parameters.new_threshold": 0.5,
        "engine.risk.maxDrawdown": 0.2,
        "pairs.0.symbol": "ETH/USDT",
        "pairs.1.enabled": False,
    }

    applied = tester._apply_parameters(base_config, parameters)

    assert applied["strategy"]["parameters"] == [
        {"key": "ma_window", "value": 20},
        {"key": "new_threshold", "value": 0.5},
    ]
    assert applied["engine"]["risk"]["maxDrawdown"] == 0.2
    assert applied["pairs"][0]["symbol"] == "ETH/USDT"
    assert applied["pairs"][1]["enabled"] is False
    # The source configuration must remain untouched by the application process.
    assert base_config["strategy"]["parameters"][0]["value"] == 10
    assert len(base_config["pairs"]) == 1


def test_extract_metric_supports_nested_metrics(tester: StrategyTester) -> None:
    metrics = {"sharpe": "1.234", "metrics": {"drawdown": 0.42}}

    assert tester._extract_metric(metrics, "sharpe") == pytest.approx(1.234)
    assert tester._extract_metric(metrics, "drawdown") == pytest.approx(0.42)
    assert tester._extract_metric(metrics, "unknown") is None
    assert tester._extract_metric(metrics, None) is None


def test_serialize_run_includes_best_result_metadata(tester: StrategyTester) -> None:
    run = _create_run(direction=OptimisationDirection.MINIMIZE)
    first_started = _utcnow() - timedelta(minutes=5)
    first_completed = _utcnow() - timedelta(minutes=4)
    second_started = _utcnow() - timedelta(minutes=3)
    second_completed = _utcnow() - timedelta(minutes=2)
    run.total_jobs = 2
    run.completed_jobs = 2
    run.status = StrategyTestRunStatus.COMPLETED
    run.results = [
        StrategyTestResult(
            id="run-1-1",
            position=1,
            parameters={"alpha": 1, "beta": "x"},
            config={},
            status=StrategyTestRunStatus.COMPLETED,
            metrics={"sharpe": 1.0},
            optimisation_score=1.0,
            started_at=first_started,
            completed_at=first_completed,
        ),
        StrategyTestResult(
            id="run-1-2",
            position=2,
            parameters={"alpha": 2, "beta": "y"},
            config={},
            status=StrategyTestRunStatus.COMPLETED,
            metrics={"sharpe": 0.5},
            optimisation_score=0.5,
            started_at=second_started,
            completed_at=second_completed,
        ),
    ]

    payload = tester._serialize_run(run, include_results=False)

    assert payload["progress"] == 1.0
    assert payload["bestResult"]["optimisationScore"] == 0.5
    assert payload["bestResult"]["position"] == 2
    assert payload["bestResult"]["startedAt"] == second_started.isoformat()
    assert "results" not in payload

    payload_with_results = tester._serialize_run(run, include_results=True)
    positions = [result["position"] for result in payload_with_results["results"]]
    assert positions == [1, 2]

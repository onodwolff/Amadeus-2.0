from __future__ import annotations

import asyncio
import hashlib
import json
import pkgutil
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import itertools
import random
import sys
import threading
import uuid
from typing import Any, Coroutine, Dict, List, Optional, Tuple, Literal

from .nautilus_engine_service import (
    EngineConfigError,
    EngineEventBus,
    EngineMode,
    NautilusEngineService,
    build_engine_service,
)


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _isoformat(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"


def _hash_password(password: str) -> str:
    digest = hashlib.sha256()
    digest.update(password.encode("utf-8"))
    return digest.hexdigest()


def _import_nautilus():
    try:
        import nautilus_trader as nt  # установлен в текущем venv
        return nt
    except Exception:
        # Fallback: импорт из vendor/nautilus_trader (если пакет не установлен)
        root = Path(__file__).resolve().parents[3]  # .../Amadeus-2.0
        vend = root / "vendor" / "nautilus_trader"
        if str(vend) not in sys.path:
            sys.path.insert(0, str(vend))
        import importlib

        nt = importlib.import_module("nautilus_trader")
        return nt


try:
    nt = _import_nautilus()
    NT_VERSION = getattr(nt, "__version__", "unknown")
except Exception:
    nt = None
    NT_VERSION = "unavailable"


@dataclass
class NodeHandle:
    id: str
    mode: str  # "backtest" | "live"
    status: str  # "created" | "running" | "stopped" | "error"
    detail: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class NodeLifecycleEvent:
    timestamp: str
    status: str
    message: str


@dataclass
class NodeLogEntry:
    id: str
    timestamp: str
    level: str
    message: str
    source: str


@dataclass
class NodeMetricsSample:
    timestamp: str
    pnl: float
    latency_ms: float
    cpu_percent: float
    memory_mb: float


@dataclass
class NodeState:
    handle: NodeHandle
    config: Dict[str, Any]
    lifecycle: List[NodeLifecycleEvent]
    logs: List[NodeLogEntry]
    metrics: List[NodeMetricsSample]


@dataclass
class PortfolioBalance:
    account_id: str
    account_name: str
    node_id: str
    venue: str
    currency: str
    total: float
    available: float
    locked: float


@dataclass
class PortfolioPosition:
    position_id: str
    account_id: str
    account_name: str
    node_id: str
    venue: str
    symbol: str
    quantity: float
    average_price: float
    mark_price: float
    unrealized_pnl: float
    realized_pnl: float
    margin_used: float
    updated_at: str


@dataclass
class CashMovement:
    movement_id: str
    account_id: str
    account_name: str
    node_id: str
    venue: str
    currency: str
    amount: float
    type: str
    description: str
    timestamp: str


@dataclass
class UserProfile:
    user_id: str
    name: str
    email: str
    username: str
    password_hash: str
    role: str
    active: bool = True
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)


class UserError(ValueError):
    """Base class for user management errors."""


class UserValidationError(UserError):
    """Raised when user payload validation fails."""


class UserConflictError(UserValidationError):
    """Raised when attempting to create a user with conflicting data."""


class UserNotFoundError(UserError):
    """Raised when a user cannot be located."""


RiskAlertCategory = Literal["limit_breach", "circuit_breaker", "margin_call"]
RiskAlertSeverity = Literal["low", "medium", "high", "critical"]


@dataclass
class RiskAlert:
    alert_id: str
    category: RiskAlertCategory
    title: str
    message: str
    severity: RiskAlertSeverity
    timestamp: str
    context: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    acknowledged_at: Optional[str] = None
    acknowledged_by: Optional[str] = None
    unlockable: bool = False
    locked: bool = False
    escalatable: bool = False
    escalated: bool = False
    escalated_at: Optional[str] = None
    resolved: bool = False
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None


@dataclass
class OrderRecord:
    order_id: str
    client_order_id: Optional[str]
    venue_order_id: Optional[str]
    symbol: str
    venue: str
    side: str
    type: str
    quantity: float
    filled_quantity: float
    price: Optional[float]
    average_price: Optional[float]
    status: str
    time_in_force: Optional[str]
    expire_time: Optional[str] = None
    post_only: Optional[bool] = None
    reduce_only: Optional[bool] = None
    limit_offset: Optional[float] = None
    contingency_type: Optional[str] = None
    order_list_id: Optional[str] = None
    linked_order_ids: Optional[List[str]] = None
    parent_order_id: Optional[str] = None
    instructions: Dict[str, Any] = field(default_factory=dict)
    node_id: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)


@dataclass
class ExecutionRecord:
    execution_id: str
    order_id: str
    symbol: str
    venue: str
    price: float
    quantity: float
    side: str
    liquidity: Optional[str]
    fees: float
    timestamp: str
    node_id: Optional[str]


class MockNautilusService:
    """Mock orchestration layer used when a live Nautilus engine isn't available."""

    def __init__(self, engine: Optional[NautilusEngineService] = None) -> None:
        engine_service = engine or build_engine_service()
        self._engine_service: NautilusEngineService = engine_service
        self._bus: EngineEventBus = self._engine_service.bus
        self._mode = "mock"

        self._nodes: Dict[str, NodeState] = {}
        (
            self._instrument_catalog,
            self._instrument_price_seed,
        ) = self._seed_instrument_catalog()
        self._instrument_index: Dict[str, Dict[str, Any]] = {
            instrument["instrument_id"]: instrument for instrument in self._instrument_catalog
        }
        self._historical_bar_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._watchlist_lock = threading.RLock()
        self._watchlist_path = self._watchlist_store_path()
        self._watchlist_ids: List[str] = self._load_watchlist()
        self._engine = None  # Optional Nautilus engine handle for live integrations
        self._seed_portfolio_state()
        self._orders: Dict[str, OrderRecord] = {}
        self._executions: Dict[str, List[ExecutionRecord]] = {}
        self._order_counter = 0
        self._seed_orders_state()
        self._risk_limits: Dict[str, Any] = self._default_risk_limits()
        self._risk_alerts: Dict[RiskAlertCategory, List[RiskAlert]] = {
            "limit_breach": [],
            "circuit_breaker": [],
            "margin_call": [],
        }
        self._seed_risk_alerts()
        self._users: Dict[str, UserProfile] = {}
        self._seed_users()
        self._publish_portfolio()
        self._publish_orders_snapshot()
        self._publish_risk_snapshot()
        self._background_tasks: List[asyncio.Task] = []
        if not self._bus.external:
            self._schedule_background_jobs()

    # ------------------------------------------------------------------
    # Engine / telemetry helpers
    # ------------------------------------------------------------------

    @property
    def bus(self) -> EngineEventBus:
        return self._bus

    def _publish(self, topic: str, payload: Dict[str, Any]) -> None:
        self._engine_service.publish(topic, payload)

    def _publish_portfolio(self) -> None:
        snapshot = self.portfolio_snapshot()
        self._publish(
            "engine.portfolio",
            {"event": "snapshot", **snapshot},
        )

    def _publish_orders_snapshot(self) -> None:
        self._publish(
            "engine.orders",
            {"event": "snapshot", **self.orders_snapshot()},
        )

    def _publish_risk_snapshot(self) -> None:
        self._publish(
            "engine.risk",
            {"event": "snapshot", **self.risk_snapshot()},
        )

    def _publish_risk_alert(self, action: str, alert: RiskAlert) -> None:
        self._publish(
            "engine.risk.alerts",
            {"event": action, "alert": self._risk_alert_to_dict(alert)},
        )

    def _schedule_background_jobs(self) -> None:
        loop = self._bus.loop

        async def metrics_pump() -> None:
            while True:
                await asyncio.sleep(1.0)
                for node_id in list(self._nodes.keys()):
                    try:
                        self.metrics_series(node_id)
                    except ValueError:
                        continue

        async def orders_pump() -> None:
            while True:
                await asyncio.sleep(1.4)
                self.orders_stream_payload()

        async def portfolio_pump() -> None:
            while True:
                await asyncio.sleep(1.8)
                self.portfolio_balances_stream_payload()

        async def risk_pump() -> None:
            while True:
                await asyncio.sleep(2.2)
                self.risk_limit_breaches_stream_payload()
                self.risk_circuit_breakers_stream_payload()
                self.risk_margin_calls_stream_payload()

        def spawn(coro: Coroutine[Any, Any, None]) -> None:
            def register() -> None:
                task = loop.create_task(coro)
                self._background_tasks.append(task)

            loop.call_soon_threadsafe(register)

        spawn(metrics_pump())
        spawn(orders_pump())
        spawn(portfolio_pump())
        spawn(risk_pump())

    def attach_engine(self, engine: Any) -> None:
        """Attach a real NautilusTrader engine implementation."""

        self._engine = engine

    # ------------------------------------------------------------------
    # Market data helpers
    # ------------------------------------------------------------------

    def _watchlist_store_path(self) -> Path:
        root = Path(__file__).resolve().parents[2] / ".gateway"
        root.mkdir(parents=True, exist_ok=True)
        return root / "watchlist.json"

    def _seed_instrument_catalog(self) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
        now = datetime.utcnow()
        futures_expiry = now + timedelta(days=45)
        alt_expiry = now + timedelta(days=90)

        raw_entries: List[Tuple[Dict[str, Any], float]] = [
            (
                {
                    "instrument_id": "BINANCE:SPOT:BTCUSDT",
                    "symbol": "BTCUSDT",
                    "venue": "BINANCE",
                    "type": "spot",
                    "base_currency": "BTC",
                    "quote_currency": "USDT",
                    "tick_size": 0.1,
                    "lot_size": 0.0001,
                    "min_notional": 10.0,
                },
                38_950.0,
            ),
            (
                {
                    "instrument_id": "BINANCE:SPOT:ETHUSDT",
                    "symbol": "ETHUSDT",
                    "venue": "BINANCE",
                    "type": "spot",
                    "base_currency": "ETH",
                    "quote_currency": "USDT",
                    "tick_size": 0.05,
                    "lot_size": 0.001,
                    "min_notional": 10.0,
                },
                2_205.0,
            ),
            (
                {
                    "instrument_id": "BINANCE:PERP:BTCUSDC",
                    "symbol": "BTCUSDC",
                    "venue": "BINANCE",
                    "type": "perpetual",
                    "base_currency": "BTC",
                    "quote_currency": "USDC",
                    "tick_size": 0.1,
                    "lot_size": 0.001,
                    "contract_size": 1.0,
                },
                38_980.0,
            ),
            (
                {
                    "instrument_id": "COINBASE:SPOT:BTCUSD",
                    "symbol": "BTCUSD",
                    "venue": "COINBASE",
                    "type": "spot",
                    "base_currency": "BTC",
                    "quote_currency": "USD",
                    "tick_size": 0.1,
                    "lot_size": 0.0001,
                },
                38_870.0,
            ),
            (
                {
                    "instrument_id": "COINBASE:SPOT:ETHUSD",
                    "symbol": "ETHUSD",
                    "venue": "COINBASE",
                    "type": "spot",
                    "base_currency": "ETH",
                    "quote_currency": "USD",
                    "tick_size": 0.05,
                    "lot_size": 0.001,
                },
                2_198.0,
            ),
            (
                {
                    "instrument_id": "BINANCE:SPOT:SOLUSDT",
                    "symbol": "SOLUSDT",
                    "venue": "BINANCE",
                    "type": "spot",
                    "base_currency": "SOL",
                    "quote_currency": "USDT",
                    "tick_size": 0.001,
                    "lot_size": 0.01,
                    "min_notional": 5.0,
                },
                95.4,
            ),
            (
                {
                    "instrument_id": "BINANCE:SPOT:ADAUSDT",
                    "symbol": "ADAUSDT",
                    "venue": "BINANCE",
                    "type": "spot",
                    "base_currency": "ADA",
                    "quote_currency": "USDT",
                    "tick_size": 0.0001,
                    "lot_size": 1.0,
                    "min_notional": 5.0,
                },
                0.612,
            ),
            (
                {
                    "instrument_id": "CME:FUT:BTC-QUARTER",
                    "symbol": "BTC-2024Q3",
                    "venue": "CME",
                    "type": "future",
                    "base_currency": "BTC",
                    "quote_currency": "USD",
                    "tick_size": 5.0,
                    "contract_size": 5.0,
                    "expiry": _isoformat(futures_expiry),
                },
                39_200.0,
            ),
            (
                {
                    "instrument_id": "DERIBIT:OPT:BTC-50K-CALL",
                    "symbol": "BTC-50K-C",
                    "venue": "DERIBIT",
                    "type": "option",
                    "base_currency": "BTC",
                    "quote_currency": "USD",
                    "tick_size": 1.0,
                    "contract_size": 1.0,
                    "expiry": _isoformat(alt_expiry),
                },
                2_150.0,
            ),
        ]

        catalog: List[Dict[str, Any]] = []
        seeds: Dict[str, float] = {}
        for payload, price in raw_entries:
            catalog.append(dict(payload))
            seeds[payload["instrument_id"]] = price
        return catalog, seeds

    def _load_watchlist(self) -> List[str]:
        try:
            raw = self._watchlist_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []
        favorites = payload.get("favorites")
        if not isinstance(favorites, list):
            return []
        return self._sanitize_watchlist_ids(favorites)

    def _persist_watchlist(self, favorites: List[str]) -> None:
        payload = {"favorites": favorites, "updated_at": _utcnow_iso()}
        try:
            self._watchlist_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _sanitize_watchlist_ids(values: List[Any]) -> List[str]:
        seen: set[str] = set()
        sanitized: List[str] = []
        for value in values:
            if not isinstance(value, str):
                continue
            if value in seen:
                continue
            seen.add(value)
            sanitized.append(value)
        return sanitized

    @staticmethod
    def _granularity_to_timedelta(granularity: str) -> timedelta:
        if not granularity:
            raise ValueError("Granularity is required")
        unit = granularity[-1]
        try:
            amount = int(granularity[:-1])
        except ValueError as exc:
            raise ValueError(f"Invalid granularity '{granularity}'") from exc
        if amount <= 0:
            raise ValueError("Granularity must be positive")

        if unit == "m":
            return timedelta(minutes=amount)
        if unit == "h":
            return timedelta(hours=amount)
        if unit == "d":
            return timedelta(days=amount)
        if unit == "w":
            return timedelta(weeks=amount)
        raise ValueError(f"Unsupported granularity unit '{unit}'")

    @staticmethod
    def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        if trimmed.endswith("Z"):
            trimmed = trimmed[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(trimmed)
        except ValueError as exc:
            raise ValueError(f"Invalid timestamp '{value}'") from exc
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(tz=None).replace(tzinfo=None)
        return parsed

    def _resolve_instrument(self, instrument_id: str) -> Dict[str, Any]:
        instrument = self._instrument_index.get(instrument_id)
        if instrument is None:
            raise ValueError(f"Instrument '{instrument_id}' not found")
        return instrument

    def _price_seed(self, instrument_id: str) -> float:
        return self._instrument_price_seed.get(instrument_id, 1_000.0)

    def list_instruments(self, venue: Optional[str] = None) -> dict:
        if venue:
            venue_key = venue.upper()
            instruments = [
                deepcopy(instrument)
                for instrument in self._instrument_catalog
                if instrument.get("venue", "").upper() == venue_key
            ]
        else:
            instruments = [deepcopy(instrument) for instrument in self._instrument_catalog]
        return {"instruments": instruments}

    def get_watchlist(self) -> dict:
        with self._watchlist_lock:
            return {"favorites": list(self._watchlist_ids)}

    def update_watchlist(self, favorites: List[str]) -> dict:
        cleaned = self._sanitize_watchlist_ids(favorites)
        with self._watchlist_lock:
            self._watchlist_ids = cleaned
            self._persist_watchlist(cleaned)
            return {"favorites": list(self._watchlist_ids)}

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_email(email: str) -> str:
        return email.strip().lower()

    def _seed_users(self) -> None:
        defaults = [
            {"name": "Operator", "email": "operator@example.com", "role": "admin"},
            {"name": "Risk Analyst", "email": "risk.analyst@example.com", "role": "risk"},
            {"name": "Execution Trader", "email": "trader@example.com", "role": "trader"},
        ]
        for entry in defaults:
            timestamp = _utcnow_iso()
            email = self._normalize_email(entry["email"])
            username = entry.get("username") or email.split("@")[0]
            password = entry.get("password") or "change-me-123"
            user = UserProfile(
                user_id=uuid.uuid4().hex,
                name=entry["name"],
                email=email,
                username=username,
                password_hash=_hash_password(password),
                role=entry["role"],
                active=entry.get("active", True),
                created_at=timestamp,
                updated_at=timestamp,
            )
            self._users[user.user_id] = user

    def _require_user(self, user_id: str) -> UserProfile:
        try:
            return self._users[user_id]
        except KeyError as exc:
            raise UserNotFoundError(f"User '{user_id}' not found") from exc

    @staticmethod
    def _user_to_dict(user: UserProfile) -> Dict[str, Any]:
        payload = asdict(user)
        payload["id"] = payload["user_id"]
        payload.pop("password_hash", None)
        return payload

    def list_users(self) -> dict:
        users = sorted(self._users.values(), key=lambda entry: entry.name.lower())
        return {"users": [self._user_to_dict(user) for user in users]}

    def get_user(self, user_id: str) -> dict:
        user = self._require_user(user_id)
        return {"user": self._user_to_dict(user)}

    def _ensure_unique_email(self, email: str, *, exclude_user_id: Optional[str] = None) -> None:
        normalized = self._normalize_email(email)
        for existing in self._users.values():
            if exclude_user_id and existing.user_id == exclude_user_id:
                continue
            if existing.email == normalized:
                raise UserConflictError(f"User with email '{normalized}' already exists")

    def _ensure_unique_username(self, username: str, *, exclude_user_id: Optional[str] = None) -> None:
        normalized = username.strip().lower()
        for existing in self._users.values():
            if exclude_user_id and existing.user_id == exclude_user_id:
                continue
            if existing.username.lower() == normalized:
                raise UserConflictError(f"User with login '{username}' already exists")

    def create_user(self, payload: Dict[str, Any]) -> dict:
        name_raw = payload.get("name")
        if not isinstance(name_raw, str) or not name_raw.strip():
            raise UserValidationError("Name is required")
        name = name_raw.strip()

        email_raw = payload.get("email")
        if not isinstance(email_raw, str) or not email_raw.strip():
            raise UserValidationError("Email is required")
        email = self._normalize_email(email_raw)
        if "@" not in email:
            raise UserValidationError("Email must contain '@'")
        self._ensure_unique_email(email)

        username_raw = payload.get("username")
        if not isinstance(username_raw, str) or not username_raw.strip():
            raise UserValidationError("Login is required")
        username = username_raw.strip()
        self._ensure_unique_username(username)

        role_raw = payload.get("role", "viewer")
        if not isinstance(role_raw, str) or not role_raw.strip():
            raise UserValidationError("Role is required")
        role = role_raw.strip()

        active = payload.get("active", True)
        if not isinstance(active, bool):
            raise UserValidationError("Active flag must be a boolean")

        password_raw = payload.get("password")
        if not isinstance(password_raw, str) or len(password_raw) < 8:
            raise UserValidationError("Password must be at least 8 characters long")
        password_hash = _hash_password(password_raw)

        now = _utcnow_iso()
        user = UserProfile(
            user_id=uuid.uuid4().hex,
            name=name,
            email=email,
            username=username,
            password_hash=password_hash,
            role=role,
            active=active,
            created_at=now,
            updated_at=now,
        )
        self._users[user.user_id] = user
        return {"user": self._user_to_dict(user)}

    def update_user(self, user_id: str, payload: Dict[str, Any]) -> dict:
        user = self._require_user(user_id)
        changed = False

        if "name" in payload:
            name_raw = payload.get("name")
            if not isinstance(name_raw, str) or not name_raw.strip():
                raise UserValidationError("Name cannot be empty")
            name = name_raw.strip()
            if name != user.name:
                user.name = name
                changed = True

        if "email" in payload:
            email_raw = payload.get("email")
            if not isinstance(email_raw, str) or not email_raw.strip():
                raise UserValidationError("Email cannot be empty")
            email = self._normalize_email(email_raw)
            if "@" not in email:
                raise UserValidationError("Email must contain '@'")
            self._ensure_unique_email(email, exclude_user_id=user_id)
            if email != user.email:
                user.email = email
                changed = True

        if "username" in payload:
            username_raw = payload.get("username")
            if not isinstance(username_raw, str) or not username_raw.strip():
                raise UserValidationError("Login cannot be empty")
            username = username_raw.strip()
            self._ensure_unique_username(username, exclude_user_id=user_id)
            if username != user.username:
                user.username = username
                changed = True

        if "role" in payload:
            role_raw = payload.get("role")
            if not isinstance(role_raw, str) or not role_raw.strip():
                raise UserValidationError("Role cannot be empty")
            role = role_raw.strip()
            if role != user.role:
                user.role = role
                changed = True

        if "active" in payload:
            active_raw = payload.get("active")
            if not isinstance(active_raw, bool):
                raise UserValidationError("Active flag must be a boolean")
            if active_raw != user.active:
                user.active = active_raw
                changed = True

        if "password" in payload:
            password_raw = payload.get("password")
            if not isinstance(password_raw, str) or len(password_raw) < 8:
                raise UserValidationError("Password must be at least 8 characters long")
            password_hash = _hash_password(password_raw)
            if password_hash != user.password_hash:
                user.password_hash = password_hash
                changed = True

        if changed:
            user.updated_at = _utcnow_iso()

        return {"user": self._user_to_dict(user)}

    # ------------------------------------------------------------------
    # Integrations catalog
    # ------------------------------------------------------------------

    def list_available_exchanges(self) -> dict:
        try:
            import nautilus_trader.adapters as adapters_pkg  # type: ignore
        except Exception:
            return {"exchanges": []}

        package_path = getattr(adapters_pkg, "__path__", None)
        if not package_path:
            return {"exchanges": []}

        exchanges: List[Dict[str, str]] = []
        for module_info in pkgutil.iter_modules(package_path):
            name = module_info.name
            if name.startswith("_") or name in {"env", "sandbox"}:
                continue
            code = name.upper()
            label = name.replace("_", " ").title()
            exchanges.append({"code": code, "name": label})

        exchanges.sort(key=lambda entry: entry["name"])
        return {"exchanges": exchanges}

    def _generate_historical_series(
        self,
        instrument_id: str,
        granularity: str,
        limit: int,
        end: datetime,
    ) -> List[Dict[str, Any]]:
        delta = self._granularity_to_timedelta(granularity)
        start = end - delta * (limit - 1)
        seed = hash((instrument_id, granularity)) & 0xFFFFFFFF
        rng = random.Random(seed)
        price = self._price_seed(instrument_id)
        bars: List[Dict[str, Any]] = []
        timestamp = start
        for _ in range(limit):
            drift = rng.uniform(-0.012, 0.012)
            open_price = price
            close_price = max(0.1, open_price * (1 + drift))
            high = max(open_price, close_price) * (1 + abs(rng.uniform(0.0, 0.006)))
            low = min(open_price, close_price) * (1 - abs(rng.uniform(0.0, 0.006)))
            volume_scale = max(1.0, price / 1_000.0)
            volume = rng.uniform(50.0, 250.0) * volume_scale
            bars.append(
                {
                    "timestamp": _isoformat(timestamp),
                    "open": round(open_price, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close_price, 2),
                    "volume": round(volume, 4),
                }
            )
            price = close_price
            timestamp += delta
        return bars

    def get_historical_bars(
        self,
        instrument_id: str,
        granularity: str,
        limit: Optional[int] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> dict:
        self._resolve_instrument(instrument_id)
        delta = self._granularity_to_timedelta(granularity)
        end_dt = self._parse_timestamp(end) or datetime.utcnow()
        start_dt = self._parse_timestamp(start)

        if start_dt and start_dt > end_dt:
            raise ValueError("Start timestamp must be before end timestamp")

        count = limit or 200
        if start_dt:
            max_count = int(((end_dt - start_dt).total_seconds() // delta.total_seconds())) + 1
            count = min(count, max(1, max_count))
        if count <= 0:
            raise ValueError("Requested bar count must be positive")

        end_aligned = end_dt.replace(microsecond=0)
        cache_key = (instrument_id, granularity)
        bars = self._historical_bar_cache.get(cache_key)
        if not bars or len(bars) < count:
            bars = self._generate_historical_series(instrument_id, granularity, count, end_aligned)
            self._historical_bar_cache[cache_key] = bars
        else:
            bars = bars[-count:]

        return {
            "instrument_id": instrument_id,
            "granularity": granularity,
            "bars": [deepcopy(bar) for bar in bars],
        }

    def _seed_portfolio_state(self) -> None:
        now = _utcnow_iso()
        self._portfolio_history: List[Dict[str, Any]] = []
        self._portfolio_balances: List[PortfolioBalance] = [
            PortfolioBalance(
                account_id="ACC-USD-PRIMARY",
                account_name="Primary USD",
                node_id="lv-00112233",
                venue="BINANCE",
                currency="USD",
                total=250_000.0,
                available=212_500.0,
                locked=37_500.0,
            ),
            PortfolioBalance(
                account_id="ACC-USD-ALGO",
                account_name="Algo USD",
                node_id="bt-00ffaacc",
                venue="COINBASE",
                currency="USD",
                total=145_000.0,
                available=118_000.0,
                locked=27_000.0,
            ),
            PortfolioBalance(
                account_id="ACC-BTC-PRIMARY",
                account_name="Primary BTC",
                node_id="lv-00112233",
                venue="BINANCE",
                currency="BTC",
                total=35.0,
                available=28.4,
                locked=6.6,
            ),
        ]

        self._portfolio_positions: List[PortfolioPosition] = [
            PortfolioPosition(
                position_id="POS-BTCUSDT",
                account_id="ACC-USD-PRIMARY",
                account_name="Primary USD",
                node_id="lv-00112233",
                venue="BINANCE",
                symbol="BTCUSDT",
                quantity=1.25,
                average_price=38_250.0,
                mark_price=38_980.0,
                unrealized_pnl=910.0,
                realized_pnl=4_120.0,
                margin_used=4_872.5,
                updated_at=now,
            ),
            PortfolioPosition(
                position_id="POS-ETHUSDT",
                account_id="ACC-USD-ALGO",
                account_name="Algo USD",
                node_id="bt-00ffaacc",
                venue="COINBASE",
                symbol="ETHUSDT",
                quantity=42.0,
                average_price=2_180.0,
                mark_price=2_205.0,
                unrealized_pnl=1_050.0,
                realized_pnl=-420.0,
                margin_used=7_398.0,
                updated_at=now,
            ),
            PortfolioPosition(
                position_id="POS-BTCUSDC",
                account_id="ACC-BTC-PRIMARY",
                account_name="Primary BTC",
                node_id="lv-00112233",
                venue="BINANCE",
                symbol="BTCUSDC",
                quantity=-0.8,
                average_price=39_050.0,
                mark_price=38_980.0,
                unrealized_pnl=56.0,
                realized_pnl=2_750.0,
                margin_used=3_126.4,
                updated_at=now,
            ),
        ]

        self._cash_movements: List[CashMovement] = [
            CashMovement(
                movement_id=uuid.uuid4().hex,
                account_id="ACC-USD-PRIMARY",
                account_name="Primary USD",
                node_id="lv-00112233",
                venue="BINANCE",
                currency="USD",
                amount=25_000.0,
                type="deposit",
                description="Initial funding",
                timestamp=now,
            ),
            CashMovement(
                movement_id=uuid.uuid4().hex,
                account_id="ACC-USD-ALGO",
                account_name="Algo USD",
                node_id="bt-00ffaacc",
                venue="COINBASE",
                currency="USD",
                amount=-7_500.0,
                type="withdrawal",
                description="Capital reallocation",
                timestamp=now,
            ),
            CashMovement(
                movement_id=uuid.uuid4().hex,
                account_id="ACC-BTC-PRIMARY",
                account_name="Primary BTC",
                node_id="lv-00112233",
                venue="BINANCE",
                currency="BTC",
                amount=0.45,
                type="trade_pnl",
                description="Settlement from BTCUSDT",
                timestamp=now,
            ),
        ]

        self._portfolio_equity = 0.0
        self._portfolio_margin = 0.0
        self._portfolio_timestamp = now
        self._recompute_portfolio_totals()
        self._backfill_portfolio_history()

    def _infer_asset_class(self, symbol: str) -> str:
        symbol = symbol.upper()
        crypto_tokens = [
            "BTC",
            "ETH",
            "SOL",
            "ADA",
            "XRP",
            "DOT",
            "DOGE",
            "AVAX",
            "MATIC",
            "USDT",
            "USDC",
        ]
        equity_tokens = ["AAPL", "TSLA", "MSFT", "AMZN", "GOOG", "META", "NVDA"]
        fx_pairs = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF"]
        if any(token in symbol for token in crypto_tokens):
            return "Crypto"
        if any(symbol.startswith(code) or symbol.endswith(code) for code in fx_pairs):
            return "FX"
        if any(token in symbol for token in equity_tokens):
            return "Equities"
        if "FUT" in symbol or "PERP" in symbol:
            return "Futures"
        return "Other"

    def _calculate_exposure_breakdown(self) -> Dict[str, float]:
        breakdown: Dict[str, float] = {}
        for position in self._portfolio_positions:
            mark = position.mark_price or position.average_price or 0.0
            quantity = position.quantity or 0.0
            exposure = quantity * mark
            asset_class = self._infer_asset_class(position.symbol)
            breakdown[asset_class] = round(breakdown.get(asset_class, 0.0) + exposure, 2)
        return breakdown

    def _capture_portfolio_sample(self) -> None:
        sample = {
            "timestamp": self._portfolio_timestamp,
            "equity": round(self._portfolio_equity, 2),
            "realized": round(
                sum(position.realized_pnl for position in self._portfolio_positions), 2
            ),
            "unrealized": round(
                sum(position.unrealized_pnl for position in self._portfolio_positions), 2
            ),
            "exposures": self._calculate_exposure_breakdown(),
        }
        self._portfolio_history.append(sample)
        if len(self._portfolio_history) > 1440:
            self._portfolio_history = self._portfolio_history[-1440:]

    def _backfill_portfolio_history(self, days: int = 90) -> None:
        if not self._portfolio_history:
            return
        latest = self._portfolio_history[-1]
        now = datetime.utcnow().replace(hour=21, minute=0, second=0, microsecond=0)
        equity = latest["equity"]
        realized = latest["realized"]
        unrealized = latest["unrealized"]
        exposures = dict(latest.get("exposures", {})) or {"Crypto": equity * 0.6}
        history: List[Dict[str, Any]] = []
        for offset in range(days, 0, -1):
            timestamp = now - timedelta(days=offset)
            drift_scale = max(900.0, equity * 0.0012)
            daily_shift = random.gauss(0, drift_scale)
            equity = max(50_000.0, equity - daily_shift)
            realized = realized - daily_shift * random.uniform(0.3, 0.55)
            unrealized = unrealized - daily_shift * random.uniform(0.25, 0.5)
            exposures = {
                key: round(value * (1 + random.gauss(0, 0.02)), 2)
                for key, value in exposures.items()
            }
            history.append(
                {
                    "timestamp": _isoformat(timestamp),
                    "equity": round(equity, 2),
                    "realized": round(realized, 2),
                    "unrealized": round(unrealized, 2),
                    "exposures": dict(exposures),
                }
            )
        self._portfolio_history = history + self._portfolio_history

    def core_info(self) -> dict:
        return {"nautilus_version": NT_VERSION, "available": nt is not None}

    def _recompute_portfolio_totals(self) -> None:
        self._portfolio_equity = round(
            sum(balance.total for balance in self._portfolio_balances), 2
        )
        self._portfolio_margin = round(
            sum(position.margin_used for position in self._portfolio_positions), 2
        )
        self._portfolio_timestamp = _utcnow_iso()
        self._capture_portfolio_sample()
        self._publish_portfolio()

    def _generate_cash_movement(self) -> CashMovement:
        balance = random.choice(self._portfolio_balances)
        movement_type = random.choices(
            population=["deposit", "withdrawal", "transfer", "trade_pnl", "adjustment"],
            weights=[0.22, 0.18, 0.15, 0.28, 0.17],
            k=1,
        )[0]
        magnitude = random.uniform(400.0, 4_000.0)
        amount = round(magnitude if movement_type in {"deposit", "trade_pnl", "adjustment"} else -magnitude, 2)
        descriptions = {
            "deposit": "External funding received",
            "withdrawal": "Capital withdrawn to treasury",
            "transfer": "Desk-to-desk transfer",
            "trade_pnl": "Realised trading P&L",
            "adjustment": "Manual balance adjustment",
        }
        return CashMovement(
            movement_id=uuid.uuid4().hex,
            account_id=balance.account_id,
            account_name=balance.account_name,
            node_id=balance.node_id,
            venue=balance.venue,
            currency=balance.currency,
            amount=amount,
            type=movement_type,
            description=descriptions.get(movement_type, ""),
            timestamp=_utcnow_iso(),
        )

    def _apply_movement_to_balances(self, movement: CashMovement) -> None:
        for balance in self._portfolio_balances:
            if balance.account_id == movement.account_id and balance.currency == movement.currency:
                balance.available = round(max(0.0, balance.available + movement.amount), 2)
                balance.total = round(max(0.0, balance.total + movement.amount), 2)
                break

    def _simulate_portfolio_tick(self) -> None:
        # Drift positions and balances slightly to emulate market activity
        for position in self._portfolio_positions:
            drift = random.gauss(0, 0.35)
            mark = max(0.5, position.mark_price * (1 + drift / 100))
            position.mark_price = round(mark, 2)
            position.unrealized_pnl = round(
                (position.mark_price - position.average_price) * position.quantity, 2
            )
            if random.random() < 0.12:
                realized_delta = random.gauss(0, max(50.0, abs(position.unrealized_pnl) * 0.15))
                position.realized_pnl = round(position.realized_pnl + realized_delta, 2)
            notional = abs(position.quantity * position.mark_price)
            position.margin_used = round(notional * 0.08, 2)
            position.updated_at = _utcnow_iso()

        for balance in self._portfolio_balances:
            available_drift = random.gauss(0, max(120.0, balance.available * 0.002))
            balance.available = round(max(0.0, balance.available + available_drift), 2)
            locked_drift = random.gauss(0, max(60.0, balance.locked * 0.002))
            balance.locked = round(max(0.0, balance.locked + locked_drift), 2)
            balance.total = round(balance.available + balance.locked, 2)

        if random.random() < 0.35:
            movement = self._generate_cash_movement()
            self._apply_movement_to_balances(movement)
            self._cash_movements.append(movement)
            self._cash_movements = self._cash_movements[-60:]

        self._recompute_portfolio_totals()

    def portfolio_snapshot(self) -> dict:
        return {
            "portfolio": {
                "balances": [asdict(balance) for balance in self._portfolio_balances],
                "positions": [asdict(position) for position in self._portfolio_positions],
                "cash_movements": [asdict(movement) for movement in self._cash_movements[-60:]],
                "equity_value": self._portfolio_equity,
                "margin_value": self._portfolio_margin,
                "timestamp": self._portfolio_timestamp,
            }
        }

    def portfolio_balances_stream_payload(self) -> dict:
        self._simulate_portfolio_tick()
        return {
            "balances": [asdict(balance) for balance in self._portfolio_balances],
            "equity_value": self._portfolio_equity,
            "margin_value": self._portfolio_margin,
            "timestamp": self._portfolio_timestamp,
        }

    def portfolio_positions_stream_payload(self) -> dict:
        self._simulate_portfolio_tick()
        return {
            "positions": [asdict(position) for position in self._portfolio_positions],
            "equity_value": self._portfolio_equity,
            "margin_value": self._portfolio_margin,
            "timestamp": self._portfolio_timestamp,
        }

    def portfolio_movements_stream_payload(self) -> dict:
        if random.random() < 0.5:
            self._simulate_portfolio_tick()
        return {
            "cash_movements": [asdict(movement) for movement in self._cash_movements[-60:]],
            "equity_value": self._portfolio_equity,
            "margin_value": self._portfolio_margin,
            "timestamp": self._portfolio_timestamp,
        }

    def portfolio_history(self, limit: int = 720) -> dict:
        history = self._portfolio_history[-limit:]
        return {"history": history}

    # --- Orders state --------------------------------------------------

    def _seed_orders_state(self) -> None:
        self._orders.clear()
        self._executions.clear()
        self._order_counter = 0

        nodes = ["lv-00112233", "bt-00ffaacc", "rv-0099abba"]
        venues = ["BINANCE", "COINBASE", "NASDAQ", "FTX"]
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "AAPL.XNAS", "MSFT.XNAS"]
        statuses = [
            "pending",
            "pending",
            "working",
            "working",
            "filled",
            "filled",
            "cancelled",
            "cancelled",
            "rejected",
            "working",
            "filled",
            "pending",
        ]

        base_time = datetime.utcnow() - timedelta(hours=6)

        tif_options = ["GTC", "IOC", "FOK", "DAY", "GTD"]

        for index, status in enumerate(statuses):
            quantity = round(random.uniform(0.5, 9.5), 4)
            price = round(random.uniform(25.0, 48000.0), 2)
            side = random.choice(["buy", "sell"])
            order_type = random.choice(["limit", "market", "stop", "stop_limit"])
            tif = random.choice(tif_options)
            node_id = random.choice(nodes)
            created = base_time + timedelta(minutes=index * 11)
            updated = created + timedelta(minutes=random.randint(1, 240))

            expire_time: Optional[str] = None
            if tif == "GTD":
                expire_time = _isoformat(created + timedelta(hours=random.randint(1, 48)))
            elif tif == "DAY":
                expire_time = _isoformat(created.replace(hour=23, minute=59))

            limit_offset: Optional[float] = None
            if order_type == "stop_limit":
                limit_offset = round(random.uniform(-25.0, 25.0), 2)

            contingency_type = random.choice([None, "OCO", "OTO"])
            order_list_id = None
            linked_order_ids: Optional[List[str]] = None
            parent_order_id = None
            if contingency_type == "OCO":
                order_list_id = f"OCO-{random.randint(1000, 9999)}"
                linked_order_ids = [f"ORD-{random.randint(1, index+1):06d}"] if index else None
            elif contingency_type == "OTO":
                parent_order_id = f"ORD-{random.randint(1, index+1):06d}" if index else None

            post_only = order_type in {"limit", "stop_limit"} and random.random() < 0.5
            reduce_only = random.random() < 0.3

            filled_quantity = 0.0
            average_price: Optional[float] = None
            if status in {"filled", "cancelled"}:
                filled_quantity = quantity if status == "filled" else round(quantity * random.uniform(0.25, 0.85), 4)
                average_price = round(price * random.uniform(0.98, 1.02), 2)
            elif status == "working":
                filled_quantity = round(quantity * random.uniform(0.1, 0.6), 4)
                average_price = round(price * random.uniform(0.98, 1.02), 2) if filled_quantity > 0 else None
            elif status == "rejected":
                updated = created + timedelta(minutes=random.randint(1, 8))

            order = OrderRecord(
                order_id=self._next_order_id(),
                client_order_id=f"CL-{1000 + index}",
                venue_order_id=(f"VN-{random.randint(100000, 999999)}" if status != "pending" else None),
                symbol=random.choice(symbols),
                venue=random.choice(venues),
                side=side,
                type=order_type,
                quantity=round(quantity, 4),
                filled_quantity=round(min(filled_quantity, quantity), 4),
                price=round(price, 2),
                average_price=average_price if filled_quantity > 0 else None,
                status=status,
                time_in_force=tif,
                expire_time=expire_time,
                post_only=post_only,
                reduce_only=reduce_only,
                limit_offset=limit_offset,
                contingency_type=contingency_type,
                order_list_id=order_list_id,
                linked_order_ids=linked_order_ids,
                parent_order_id=parent_order_id,
                instructions={},
                node_id=node_id,
                created_at=_isoformat(created),
                updated_at=_isoformat(updated if status != "pending" else created),
            )
            self._register_order(order)

            if order.filled_quantity > 0:
                self._bootstrap_executions(order)

        self._trim_orders()

    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f"ORD-{self._order_counter:06d}"

    def _register_order(self, order: OrderRecord) -> None:
        self._orders[order.order_id] = order
        self._executions.setdefault(order.order_id, [])
        self._publish(
            "engine.orders",
            {"event": "created", "order": asdict(order)},
        )

    def _bootstrap_executions(self, order: OrderRecord) -> None:
        executed = max(0.0, min(order.filled_quantity, order.quantity))
        if executed <= 0:
            return

        remaining = executed
        slices = 1 if executed < 0.01 else random.randint(1, min(3, int(max(1, round(executed)))))
        total_cost = 0.0
        fills: List[ExecutionRecord] = []
        for slice_index in range(slices):
            if remaining <= 0:
                break
            if slice_index == slices - 1:
                qty = remaining
            else:
                qty = round(remaining * random.uniform(0.35, 0.7), 4)
                qty = max(0.0001, min(qty, remaining))
            price = order.average_price or order.price or round(random.uniform(25.0, 48000.0), 2)
            timestamp = order.updated_at
            record = ExecutionRecord(
                execution_id=str(uuid.uuid4()),
                order_id=order.order_id,
                symbol=order.symbol,
                venue=order.venue,
                price=round(price, 2),
                quantity=round(qty, 4),
                side=order.side,
                liquidity=random.choice(["maker", "taker"]),
                fees=round(price * qty * 0.0004, 4),
                timestamp=timestamp,
                node_id=order.node_id,
            )
            fills.append(record)
            total_cost += record.price * record.quantity
            remaining = round(max(0.0, remaining - qty), 4)

        if not fills:
            return

        self._executions[order.order_id].extend(fills)
        filled_qty = sum(fill.quantity for fill in fills)
        order.filled_quantity = round(min(order.quantity, filled_qty), 4)
        if filled_qty > 0:
            order.average_price = round(total_cost / filled_qty, 2)
        for record in fills:
            self._publish(
                "engine.orders",
                {"event": "execution", "execution": asdict(record)},
            )
        self._publish(
            "engine.orders",
            {"event": "order_updated", "order": asdict(order)},
        )

    def _trim_orders(self, limit: int = 120) -> None:
        if len(self._orders) <= limit:
            return
        ordered = sorted(self._orders.values(), key=lambda o: o.created_at)
        for stale in ordered[: len(self._orders) - limit]:
            self._orders.pop(stale.order_id, None)
            self._executions.pop(stale.order_id, None)

    def _create_random_order(self) -> OrderRecord:
        now = datetime.utcnow()
        order_type = random.choice(["limit", "market", "stop", "stop_limit"])
        tif = random.choice(["GTC", "IOC", "FOK", "DAY", "GTD"])
        expire_time: Optional[str] = None
        if tif == "GTD":
            expire_time = _isoformat(now + timedelta(hours=random.randint(1, 48)))
        elif tif == "DAY":
            expire_time = _isoformat(now.replace(hour=23, minute=59, second=0, microsecond=0))

        limit_offset: Optional[float] = None
        if order_type == "stop_limit":
            limit_offset = round(random.uniform(-10.0, 10.0), 2)

        contingency_type = random.choice([None, "OCO", "OTO"])
        order_list_id = None
        linked_order_ids: Optional[List[str]] = None
        parent_order_id = None
        if contingency_type == "OCO":
            order_list_id = f"OCO-{random.randint(1000, 9999)}"
        elif contingency_type == "OTO":
            parent_order_id = f"ORD-{random.randint(1, max(1, self._order_counter)):06d}"

        order = OrderRecord(
            order_id=self._next_order_id(),
            client_order_id=f"CL-{1000 + self._order_counter}",
            venue_order_id=None,
            symbol=random.choice(["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "AAPL.XNAS", "MSFT.XNAS"]),
            venue=random.choice(["BINANCE", "COINBASE", "NASDAQ", "FTX"]),
            side=random.choice(["buy", "sell"]),
            type=order_type,
            quantity=round(random.uniform(0.2, 8.0), 4),
            filled_quantity=0.0,
            price=round(random.uniform(20.0, 50000.0), 2),
            average_price=None,
            status="pending",
            time_in_force=tif,
            expire_time=expire_time,
            post_only=order_type in {"limit", "stop_limit"} and random.random() < 0.5,
            reduce_only=random.random() < 0.35,
            limit_offset=limit_offset,
            contingency_type=contingency_type,
            order_list_id=order_list_id,
            linked_order_ids=linked_order_ids,
            parent_order_id=parent_order_id,
            instructions={},
            node_id=random.choice(["lv-00112233", "bt-00ffaacc", "rv-0099abba"]),
            created_at=_isoformat(now),
            updated_at=_isoformat(now),
        )
        self._register_order(order)
        self._trim_orders()
        return order

    def _apply_fill(self, order: OrderRecord) -> None:
        remaining = max(0.0, order.quantity - order.filled_quantity)
        if remaining <= 0:
            order.status = "filled"
            return

        partial = remaining > 0.05 and random.random() < 0.6
        fill_qty = remaining if not partial else round(remaining * random.uniform(0.25, 0.75), 4)
        fill_qty = max(0.0001, min(fill_qty, remaining))

        prev_qty = order.filled_quantity
        prev_cost = (order.average_price or 0.0) * prev_qty
        price = order.price or round(random.uniform(25.0, 48000.0), 2)
        timestamp = _utcnow_iso()

        order.filled_quantity = round(min(order.quantity, prev_qty + fill_qty), 4)
        total_cost = prev_cost + price * fill_qty
        if order.filled_quantity > 0:
            order.average_price = round(total_cost / order.filled_quantity, 2)

        order.status = "filled" if abs(order.quantity - order.filled_quantity) < 1e-6 else "working"
        order.updated_at = timestamp
        order.venue_order_id = order.venue_order_id or f"VN-{random.randint(100000, 999999)}"

        record = ExecutionRecord(
            execution_id=str(uuid.uuid4()),
            order_id=order.order_id,
            symbol=order.symbol,
            venue=order.venue,
            price=round(price, 2),
            quantity=round(fill_qty, 4),
            side=order.side,
            liquidity=random.choice(["maker", "taker"]),
            fees=round(price * fill_qty * 0.0004, 4),
            timestamp=timestamp,
            node_id=order.node_id,
        )
        self._executions.setdefault(order.order_id, []).append(record)
        self._executions[order.order_id] = self._executions[order.order_id][-40:]
        self._publish(
            "engine.orders",
            {"event": "order_updated", "order": asdict(order)},
        )
        self._publish(
            "engine.orders",
            {"event": "execution", "execution": asdict(record)},
        )

    def _apply_cancel(self, order: OrderRecord) -> None:
        order.status = "cancelled"
        order.updated_at = _utcnow_iso()
        self._publish(
            "engine.orders",
            {"event": "order_updated", "order": asdict(order)},
        )

    def _apply_reject(self, order: OrderRecord) -> None:
        order.status = "rejected"
        order.updated_at = _utcnow_iso()
        order.venue_order_id = None
        self._publish(
            "engine.orders",
            {"event": "order_updated", "order": asdict(order)},
        )

    def _advance_orders_state(self) -> None:
        if not self._orders:
            return

        open_orders = [
            order
            for order in self._orders.values()
            if order.status in {"pending", "working"}
        ]

        if open_orders and random.random() < 0.75:
            order = random.choice(open_orders)
            action_roll = random.random()
            if action_roll < 0.65:
                self._apply_fill(order)
            elif action_roll < 0.82:
                self._apply_cancel(order)
            elif order.status == "pending" and action_roll < 0.9:
                self._apply_reject(order)

        if random.random() < 0.4:
            self._create_random_order()

        self._trim_orders()
        self._publish_orders_snapshot()

    def orders_snapshot(self) -> dict:
        ordered = sorted(
            self._orders.values(),
            key=lambda order: (order.created_at, order.order_id),
            reverse=True,
        )
        executions = list(
            itertools.chain.from_iterable(
                self._executions.get(order.order_id, []) for order in ordered
            )
        )
        executions.sort(key=lambda execution: execution.timestamp, reverse=True)

        return {
            "orders": [asdict(order) for order in ordered],
            "executions": [asdict(execution) for execution in executions],
        }

    def orders_stream_payload(self) -> dict:
        self._advance_orders_state()
        return self.orders_snapshot()

    def _translate_order_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        symbol = (payload.get("symbol") or "").upper()
        venue = (payload.get("venue") or "").upper()
        side = (payload.get("side") or "buy").upper()
        order_type = (payload.get("type") or "market").lower()
        quantity = float(payload.get("quantity") or 0.0)
        price = payload.get("price")
        limit_offset = payload.get("limit_offset")
        time_in_force = (payload.get("time_in_force") or "GTC").upper()
        expire_time = payload.get("expire_time") or None
        post_only = payload.get("post_only")
        reduce_only = payload.get("reduce_only")
        contingency_type = payload.get("contingency_type") or None
        order_list_id = payload.get("order_list_id") or None
        parent_order_id = payload.get("parent_order_id") or None
        linked_order_ids = payload.get("linked_order_ids") or None

        limit_price: Optional[float] = None
        trigger_price: Optional[float] = None
        if order_type == "limit":
            limit_price = float(price) if price is not None else None
        elif order_type == "stop":
            trigger_price = float(price) if price is not None else None
        elif order_type == "stop_limit":
            trigger_price = float(price) if price is not None else None
            if price is not None and limit_offset is not None:
                limit_price = round(float(price) + float(limit_offset), 8)
            else:
                limit_price = float(price) if price is not None else None

        if isinstance(linked_order_ids, list):
            linked_ids = [str(item) for item in linked_order_ids if str(item).strip()]
        elif linked_order_ids:
            linked_ids = [str(linked_order_ids).strip()]
        else:
            linked_ids = None

        translated: Dict[str, Any] = {
            "symbol": symbol,
            "venue": venue,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "time_in_force": time_in_force,
            "expire_time": expire_time,
            "post_only": (None if post_only is None else bool(post_only)),
            "reduce_only": (None if reduce_only is None else bool(reduce_only)),
            "contingency_type": contingency_type,
            "order_list_id": order_list_id,
            "parent_order_id": parent_order_id,
            "linked_order_ids": linked_ids,
        }
        if limit_price is not None:
            translated["limit_price"] = limit_price
        if trigger_price is not None:
            translated["trigger_price"] = trigger_price
        if limit_offset is not None:
            translated["limit_offset"] = float(limit_offset)

        if nt is not None:
            try:
                from nautilus_trader.model.enums import (
                    OrderSide as NTOrderSide,
                    OrderType as NTOrderType,
                    TimeInForce as NTTimeInForce,
                    ContingencyType as NTContingencyType,
                )
            except Exception:
                pass
            else:
                enums: Dict[str, Any] = {}
                try:
                    enums["side"] = NTOrderSide[side]
                except KeyError:
                    pass
                try:
                    enums["order_type"] = NTOrderType[order_type.upper()]
                except KeyError:
                    pass
                try:
                    enums["time_in_force"] = NTTimeInForce[time_in_force]
                except KeyError:
                    pass
                if contingency_type:
                    try:
                        enums["contingency_type"] = NTContingencyType[contingency_type]
                    except KeyError:
                        pass
                if enums:
                    translated["nautilus_enums"] = enums

        return translated

    def _submit_to_engine(self, instructions: Dict[str, Any]) -> None:
        if not self._engine:
            return

        submit = getattr(self._engine, "submit_order", None)
        if submit is None:
            return

        try:
            submit(instructions)
        except TypeError:
            try:
                submit(**instructions)
            except Exception:
                pass
        except Exception:
            pass

    def create_order(self, payload: Dict[str, Any]) -> dict:
        symbol = payload.get("symbol", "").upper()
        venue = payload.get("venue", "").upper()
        side = (payload.get("side") or "buy").lower()
        order_type = (payload.get("type") or "market").lower()
        quantity = float(payload.get("quantity") or 0.0)
        price = payload.get("price")
        time_in_force_raw = payload.get("time_in_force")
        time_in_force = (
            str(time_in_force_raw).upper()
            if isinstance(time_in_force_raw, str) and time_in_force_raw
            else None
        )
        expire_time = payload.get("expire_time") or None
        post_only_raw = payload.get("post_only")
        reduce_only_raw = payload.get("reduce_only")
        limit_offset_raw = payload.get("limit_offset")
        contingency_type = payload.get("contingency_type") or None
        order_list_id = payload.get("order_list_id") or None
        parent_order_id = payload.get("parent_order_id") or None
        linked_raw = payload.get("linked_order_ids")
        client_order_id = payload.get("client_order_id") or None
        node_id = payload.get("node_id") or None

        linked_order_ids: Optional[List[str]]
        if isinstance(linked_raw, list):
            linked_order_ids = [str(item) for item in linked_raw if str(item).strip()]
        elif linked_raw:
            linked_order_ids = [str(linked_raw).strip()]
        else:
            linked_order_ids = None

        post_only = None if post_only_raw is None else bool(post_only_raw)
        reduce_only = None if reduce_only_raw is None else bool(reduce_only_raw)
        limit_offset = None
        if limit_offset_raw is not None:
            try:
                limit_offset = float(limit_offset_raw)
            except (TypeError, ValueError):
                limit_offset = None

        normalized_payload = dict(payload)
        normalized_payload.update(
            {
                "symbol": symbol,
                "venue": venue,
                "side": side,
                "type": order_type,
                "quantity": quantity,
                "price": price,
                "time_in_force": time_in_force,
                "expire_time": expire_time,
                "post_only": post_only,
                "reduce_only": reduce_only,
                "limit_offset": limit_offset,
                "contingency_type": contingency_type,
                "order_list_id": order_list_id,
                "parent_order_id": parent_order_id,
                "linked_order_ids": linked_order_ids,
            }
        )

        engine_payload = self._translate_order_payload(normalized_payload)
        self._submit_to_engine(engine_payload)

        now = _utcnow_iso()
        order = OrderRecord(
            order_id=self._next_order_id(),
            client_order_id=client_order_id,
            venue_order_id=None,
            symbol=symbol,
            venue=venue,
            side=side,
            type=order_type,
            quantity=round(quantity, 4),
            filled_quantity=0.0,
            price=(round(float(price), 4) if price is not None else None),
            average_price=None,
            status="pending",
            time_in_force=time_in_force,
            expire_time=expire_time,
            post_only=post_only,
            reduce_only=reduce_only,
            limit_offset=limit_offset,
            contingency_type=contingency_type,
            order_list_id=order_list_id,
            linked_order_ids=linked_order_ids,
            parent_order_id=parent_order_id,
            instructions=deepcopy(engine_payload),
            node_id=node_id,
            created_at=now,
            updated_at=now,
        )
        self._register_order(order)
        self._trim_orders()
        self._publish_orders_snapshot()
        return {"order": asdict(order)}

    def cancel_order(self, order_id: str) -> dict:
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order '{order_id}' not found")
        if order.status in {"filled", "cancelled", "rejected"}:
            return {"order": asdict(order)}
        self._apply_cancel(order)
        self._publish_orders_snapshot()
        return {"order": asdict(order)}

    def duplicate_order(self, order_id: str) -> dict:
        original = self._orders.get(order_id)
        if original is None:
            raise ValueError(f"Order '{order_id}' not found")

        now = _utcnow_iso()
        duplicate = OrderRecord(
            order_id=self._next_order_id(),
            client_order_id=(f"{original.client_order_id}-COPY" if original.client_order_id else None),
            venue_order_id=None,
            symbol=original.symbol,
            venue=original.venue,
            side=original.side,
            type=original.type,
            quantity=original.quantity,
            filled_quantity=0.0,
            price=original.price,
            average_price=None,
            status="pending",
            time_in_force=original.time_in_force,
            expire_time=original.expire_time,
            post_only=original.post_only,
            reduce_only=original.reduce_only,
            limit_offset=original.limit_offset,
            contingency_type=original.contingency_type,
            order_list_id=original.order_list_id,
            linked_order_ids=deepcopy(original.linked_order_ids) if original.linked_order_ids else None,
            parent_order_id=original.parent_order_id,
            instructions=deepcopy(original.instructions),
            node_id=original.node_id,
            created_at=now,
            updated_at=now,
        )
        self._register_order(duplicate)
        self._trim_orders()
        self._publish_orders_snapshot()
        return {"order": asdict(duplicate)}

    def risk_snapshot(self) -> dict:
        timestamp = _utcnow_iso()

        exposures: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for position in self._portfolio_positions:
            key = (position.symbol, position.venue)
            mark = position.mark_price or position.average_price or 0.0
            net = round(position.quantity * mark, 2)
            entry = exposures.setdefault(
                key,
                {
                    "symbol": position.symbol,
                    "venue": position.venue,
                    "net_exposure": 0.0,
                    "notional_value": 0.0,
                    "currency": "USD",
                },
            )
            entry["net_exposure"] = round(entry["net_exposure"] + net, 2)
            entry["notional_value"] = round(entry["notional_value"] + abs(net), 2)

        exposure_list = list(exposures.values())
        total_notional = sum(item["notional_value"] for item in exposure_list)

        exposure_limits = [
            {
                "name": "Max order quantity",
                "value": 0.0,
                "limit": 250.0,
                "unit": "units",
                "breached": False,
            },
            {
                "name": "Max order notional",
                "value": round(total_notional, 2),
                "limit": 250_000.0,
                "unit": "USD",
                "breached": total_notional > 250_000.0,
            },
        ]

        return {
            "risk": {
                "timestamp": timestamp,
                "total_var": round(total_notional * 0.12, 2),
                "stress_var": round(total_notional * 0.18, 2),
                "exposure_limits": exposure_limits,
                "exposures": exposure_list,
            },
            "limits": deepcopy(self._risk_limits),
        }

    def risk_limits_snapshot(self) -> dict:
        return {"limits": deepcopy(self._risk_limits)}

    def update_risk_limits(self, payload: Dict[str, Any]) -> dict:
        self._risk_limits = deepcopy(payload)
        snapshot = self.risk_limits_snapshot()
        self._publish_risk_snapshot()
        return snapshot

    def _default_risk_limits(self) -> Dict[str, Any]:
        return {
            "position_limits": {
                "enabled": True,
                "status": "up_to_date",
                "limits": [
                    {"venue": "BINANCE", "node": "lv-00112233", "limit": 750000.0},
                    {"venue": "COINBASE", "node": "bt-00ffaacc", "limit": 500000.0},
                ],
            },
            "max_loss": {
                "enabled": True,
                "status": "stale",
                "daily": 25000.0,
                "weekly": 100000.0,
            },
            "trade_locks": {
                "enabled": True,
                "status": "up_to_date",
                "locks": [
                    {"venue": "BINANCE", "node": "lv-00112233", "locked": False, "reason": None},
                    {
                        "venue": "COINBASE",
                        "node": "bt-00ffaacc",
                        "locked": True,
                        "reason": "Pending compliance review",
                    },
                ],
            },
        }

    def _seed_risk_alerts(self) -> None:
        if not self._portfolio_positions:
            return

        # Seed an initial limit breach to showcase the widget.
        position = random.choice(self._portfolio_positions)
        limit_entry = next(
            (
                item
                for item in self._risk_limits.get("position_limits", {})
                .get("limits", [])
                if item.get("venue") == position.venue
            ),
            None,
        )
        limit_value = limit_entry.get("limit", 500000.0) if limit_entry else 500000.0
        breach_value = round(limit_value * 1.18, 2)
        self._add_risk_alert(
            category="limit_breach",
            severity="high",
            title=f"Limit breach on {position.symbol}",
            message=(
                f"Net exposure on {position.symbol} at {position.venue} reached ${breach_value:,.0f} "
                f"against a limit of ${limit_value:,.0f}."
            ),
            context={
                "symbol": position.symbol,
                "venue": position.venue,
                "node": position.node_id,
                "limit": limit_value,
                "breach": breach_value,
            },
        )

        # Seed a circuit breaker alert.
        account = random.choice(self._portfolio_balances)
        circuit = self._add_risk_alert(
            category="circuit_breaker",
            severity="critical",
            title=f"Circuit breaker triggered on {account.venue}",
            message=(
                f"{account.account_name} trading halted on {account.venue} after latency spike."
            ),
            context={
                "venue": account.venue,
                "account": account.account_name,
                "node": account.node_id,
                "reason": "Latency breach",
            },
            unlockable=True,
        )
        circuit.locked = True

        # Seed a margin call alert.
        balance = random.choice(self._portfolio_balances)
        deficit = round(balance.total * 0.12, 2)
        self._add_risk_alert(
            category="margin_call",
            severity="medium",
            title=f"Margin call for {balance.account_name}",
            message=(
                f"Additional {deficit} {balance.currency} required for {balance.account_name} at {balance.venue}."
            ),
            context={
                "account": balance.account_name,
                "venue": balance.venue,
                "currency": balance.currency,
                "deficit": deficit,
            },
            escalatable=True,
        )

    def _add_risk_alert(
        self,
        *,
        category: RiskAlertCategory,
        severity: RiskAlertSeverity,
        title: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        unlockable: bool = False,
        escalatable: bool = False,
    ) -> RiskAlert:
        alert = RiskAlert(
            alert_id=uuid.uuid4().hex,
            category=category,
            title=title,
            message=message,
            severity=severity,
            timestamp=_utcnow_iso(),
            context=context or {},
            unlockable=unlockable,
            locked=unlockable,
            escalatable=escalatable,
        )
        alerts = self._risk_alerts.setdefault(category, [])
        alerts.append(alert)
        if len(alerts) > 50:
            alerts[:] = alerts[-50:]
        self._publish_risk_alert("created", alert)
        return alert

    def _risk_alert_to_dict(self, alert: RiskAlert) -> Dict[str, Any]:
        payload = asdict(alert)
        payload["id"] = payload.pop("alert_id")
        return payload

    def _risk_alerts_stream_payload(self, category: RiskAlertCategory) -> dict:
        events = [self._risk_alert_to_dict(alert) for alert in self._risk_alerts.get(category, [])]
        events.sort(key=lambda item: item.get("timestamp", ""))
        return {"events": events, "timestamp": _utcnow_iso()}

    def _maybe_generate_limit_breach(self) -> None:
        if not self._portfolio_positions or random.random() >= 0.32:
            return

        position = random.choice(self._portfolio_positions)
        mark = position.mark_price or position.average_price or 0.0
        notional = abs(round(position.quantity * mark, 2))
        limit_entry = next(
            (
                item
                for item in self._risk_limits.get("position_limits", {})
                .get("limits", [])
                if item.get("venue") == position.venue
            ),
            None,
        )
        limit_value = limit_entry.get("limit", 500000.0) if limit_entry else 500000.0
        breach_value = max(limit_value * random.uniform(1.05, 1.45), notional * 1.15)
        breach_value = round(breach_value, 2)
        ratio = breach_value / max(limit_value, 1)
        severity: RiskAlertSeverity
        if ratio >= 1.35:
            severity = "critical"
        elif ratio >= 1.2:
            severity = "high"
        else:
            severity = "medium"

        reasons = [
            "Volatility spike", "Order flow imbalance", "Position accumulation", "Hedging delay"
        ]
        reason = random.choice(reasons)

        self._add_risk_alert(
            category="limit_breach",
            severity=severity,
            title=f"Limit breach on {position.symbol}",
            message=(
                f"Exposure on {position.symbol} at {position.venue} now ${breach_value:,.0f} "
                f"vs limit ${limit_value:,.0f} ({reason})."
            ),
            context={
                "symbol": position.symbol,
                "venue": position.venue,
                "node": position.node_id,
                "limit": round(limit_value, 2),
                "breach": breach_value,
                "reason": reason,
            },
        )

    def _maybe_generate_circuit_breaker(self) -> None:
        if not self._portfolio_balances or random.random() >= 0.27:
            return

        account = random.choice(self._portfolio_balances)
        reasons = [
            "Latency spike",
            "Gateway disconnect",
            "Rapid drawdown",
            "Manual safety trigger",
        ]
        reason = random.choice(reasons)
        severity = random.choices([
            "high",
            "critical",
        ], weights=[0.6, 0.4])[0]

        alert = self._add_risk_alert(
            category="circuit_breaker",
            severity=severity,
            title=f"Circuit breaker triggered on {account.venue}",
            message=(
                f"{account.account_name} halted on {account.venue} due to {reason.lower()}."
            ),
            context={
                "venue": account.venue,
                "account": account.account_name,
                "node": account.node_id,
                "reason": reason,
            },
            unlockable=True,
        )
        alert.locked = True

    def _maybe_generate_margin_call(self) -> None:
        if not self._portfolio_balances or random.random() >= 0.3:
            return

        balance = random.choice(self._portfolio_balances)
        deficit = round(balance.total * random.uniform(0.08, 0.22), 2)
        ratio = deficit / max(balance.total, 1)
        severity: RiskAlertSeverity
        if ratio >= 0.18:
            severity = "critical"
        elif ratio >= 0.14:
            severity = "high"
        else:
            severity = "medium"

        self._add_risk_alert(
            category="margin_call",
            severity=severity,
            title=f"Margin call for {balance.account_name}",
            message=(
                f"{balance.account_name} at {balance.venue} requires {deficit} {balance.currency} "
                "to restore maintenance levels."
            ),
            context={
                "account": balance.account_name,
                "venue": balance.venue,
                "currency": balance.currency,
                "deficit": deficit,
            },
            escalatable=True,
        )

    def risk_limit_breaches_stream_payload(self) -> dict:
        self._maybe_generate_limit_breach()
        return self._risk_alerts_stream_payload("limit_breach")

    def risk_circuit_breakers_stream_payload(self) -> dict:
        self._maybe_generate_circuit_breaker()
        return self._risk_alerts_stream_payload("circuit_breaker")

    def risk_margin_calls_stream_payload(self) -> dict:
        self._maybe_generate_margin_call()
        return self._risk_alerts_stream_payload("margin_call")

    def _find_risk_alert(self, alert_id: str) -> RiskAlert:
        for alerts in self._risk_alerts.values():
            for alert in alerts:
                if alert.alert_id == alert_id:
                    return alert
        raise ValueError(f"Alert '{alert_id}' not found")

    def acknowledge_risk_alert(self, alert_id: str) -> dict:
        alert = self._find_risk_alert(alert_id)
        if not alert.acknowledged:
            alert.acknowledged = True
            alert.acknowledged_at = _utcnow_iso()
            alert.acknowledged_by = "operator"
            self._publish_risk_alert("acknowledged", alert)
        return {"alert": self._risk_alert_to_dict(alert)}

    def unlock_circuit_breaker(self, alert_id: str) -> dict:
        alert = self._find_risk_alert(alert_id)
        if not alert.unlockable:
            raise RuntimeError("Alert cannot be unlocked")
        if not alert.locked:
            return {"alert": self._risk_alert_to_dict(alert)}

        alert.locked = False
        alert.resolved = True
        alert.resolved_at = _utcnow_iso()
        alert.resolved_by = "operator"
        if not alert.acknowledged:
            alert.acknowledged = True
            alert.acknowledged_at = alert.resolved_at
            alert.acknowledged_by = "operator"
        self._publish_risk_alert("unlocked", alert)
        return {"alert": self._risk_alert_to_dict(alert)}

    def escalate_margin_call(self, alert_id: str) -> dict:
        alert = self._find_risk_alert(alert_id)
        if not alert.escalatable:
            raise RuntimeError("Alert cannot be escalated")
        if alert.escalated:
            return {"alert": self._risk_alert_to_dict(alert)}

        alert.escalated = True
        alert.escalated_at = _utcnow_iso()
        if not alert.acknowledged:
            alert.acknowledged = True
            alert.acknowledged_at = alert.escalated_at
            alert.acknowledged_by = "operator"
        self._publish_risk_alert("escalated", alert)
        return {"alert": self._risk_alert_to_dict(alert)}

    def start_backtest(
        self,
        symbol: str = "BTCUSDT",
        venue: str = "BINANCE",
        bar: str = "1m",
        detail: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        config_metadata: Optional[Dict[str, Any]] = None,
    ) -> NodeHandle:
        config_data: Dict[str, Any] = config or {
            "type": "backtest",
            "strategy": {
                "id": "default_backtest",
                "name": "Default backtest",
                "parameters": [
                    {"key": "symbol", "value": symbol},
                    {"key": "venue", "value": venue},
                    {"key": "bar", "value": bar},
                ],
            },
            "dataSources": [
                {
                    "id": f"{venue.lower()}-{symbol.lower()}-{bar}",
                    "label": f"{venue} {symbol} {bar}",
                    "type": "historical",
                    "mode": "read",
                }
            ],
            "keyReferences": [],
            "constraints": {"maxRuntimeMinutes": 480, "autoStopOnError": True},
        }
        return self._create_node(
            mode="backtest",
            detail=detail
            or f"Backtest node prepared (symbol={symbol}, venue={venue}, bar={bar})",
            config=config_data,
            config_metadata=config_metadata,
        )

    def start_live(
        self,
        venue: str = "BINANCE",
        detail: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        config_metadata: Optional[Dict[str, Any]] = None,
    ) -> NodeHandle:
        config_data: Dict[str, Any] = config or {
            "type": "live",
            "strategy": {
                "id": "live_default",
                "name": "Live execution",
                "parameters": [
                    {"key": "venue", "value": venue},
                    {"key": "mode", "value": "production"},
                ],
            },
            "dataSources": [
                {
                    "id": f"{venue.lower()}-market-data",
                    "label": f"{venue} market data",
                    "type": "live",
                    "mode": "read",
                }
            ],
            "keyReferences": [
                {"alias": f"{venue} primary key", "keyId": f"{venue.lower()}-primary", "required": True}
            ],
            "constraints": {"autoStopOnError": True},
        }
        return self._create_node(
            mode="live",
            detail=detail or f"Live node prepared (venue={venue}). Configure adapters to proceed.",
            config=config_data,
            config_metadata=config_metadata,
        )

    def stop_node(self, node_id: str) -> NodeHandle:
        state = self._require_node(node_id)
        handle = state.handle
        if handle.status == "stopped":
            return handle
        handle.status = "stopped"
        handle.updated_at = _utcnow_iso()
        self._record_lifecycle(node_id, "stopped", "Node stopped by operator")
        self._append_log(node_id, "info", "Node received stop signal", source="orchestrator")
        return handle

    def restart_node(self, node_id: str) -> NodeHandle:
        state = self._require_node(node_id)
        if nt is None:
            raise ValueError("Nautilus core not available. Install package into backend venv.")
        handle = state.handle
        handle.status = "running"
        handle.detail = handle.detail or "Node restarted"
        handle.updated_at = _utcnow_iso()
        self._record_lifecycle(node_id, "running", "Node restarted")
        self._append_log(node_id, "info", "Restart sequence completed", source="controller")
        return handle

    def node_detail(self, node_id: str) -> dict:
        state = self._require_node(node_id)
        return {
            "node": self.as_dict(state.handle),
            "config": state.config,
            "lifecycle": [asdict(event) for event in state.lifecycle],
        }

    def node_logs(self, node_id: str) -> dict:
        state = self._require_node(node_id)
        return {"logs": [asdict(entry) for entry in state.logs]}

    def export_logs(self, node_id: str) -> str:
        state = self._require_node(node_id)
        return "\n".join(
            f"[{entry.timestamp}] {entry.level.upper()} {entry.source}: {entry.message}"
            for entry in state.logs
        )

    def stream_snapshot(self, node_id: str) -> dict:
        state = self._require_node(node_id)
        handle = state.handle
        if nt is not None and handle.status == "running":
            self._maybe_append_runtime_activity(node_id)
        return {
            "logs": [asdict(entry) for entry in state.logs[-200:]],
            "lifecycle": [asdict(event) for event in state.lifecycle[-50:]],
        }

    def list_nodes(self) -> List[NodeHandle]:
        for node_id in list(self._nodes.keys()):
            self._ensure_metrics_seeded(node_id)
            self._update_handle_metrics(node_id)
        return [state.handle for state in self._nodes.values()]

    def as_dict(self, handle: NodeHandle) -> dict:
        return asdict(handle)

    def _create_node(
        self,
        mode: str,
        detail: Optional[str],
        config: Dict[str, Any],
        config_metadata: Optional[Dict[str, Any]] = None,
    ) -> NodeHandle:
        prefix = "bt" if mode == "backtest" else "lv"
        node_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
        handle = NodeHandle(id=node_id, mode=mode, status="created", detail=detail)
        state = NodeState(handle=handle, config=config, lifecycle=[], logs=[], metrics=[])
        self._nodes[node_id] = state
        self._record_lifecycle(node_id, "created", "Node registered")
        self._ensure_metrics_seeded(node_id)
        self._publish(
            "engine.nodes",
            {"event": "created", "node": self.as_dict(handle)},
        )

        try:
            engine_mode = EngineMode(mode)
        except ValueError:
            engine_mode = None

        if engine_mode is not None:
            metadata: Dict[str, Any] = {}
            if detail:
                metadata["detail"] = detail
            if config_metadata:
                metadata.update(
                    {key: value for key, value in config_metadata.items() if value is not None}
                )
            else:
                metadata.update({"source": "generated", "format": "json"})

            try:
                self._engine_service.store_node_config(
                    node_id=node_id,
                    mode=engine_mode,
                    config=config,
                    source=metadata.get("source"),
                    fmt=metadata.get("format"),
                    metadata=metadata,
                )
            except EngineConfigError as exc:
                self._append_log(
                    node_id,
                    "warning",
                    f"Failed to persist configuration: {exc}",
                    source="gateway",
                )

        if nt is None:
            handle.status = "error"
            handle.detail = (
                "Nautilus core not available. Install package into backend venv."
            )
            handle.updated_at = _utcnow_iso()
            self._record_lifecycle(node_id, "error", handle.detail)
            self._append_log(node_id, "error", handle.detail, source="system")
            self._publish(
                "engine.nodes",
                {"event": "error", "node": self.as_dict(handle)},
            )
            return handle

        handle.status = "running"
        handle.updated_at = _utcnow_iso()
        self._record_lifecycle(node_id, "running", "Node started")
        self._append_log(node_id, "info", "Node entered running state", source="engine")
        self._append_log(
            node_id,
            "debug",
            f"Configuration loaded: {config.get('strategy', {}).get('name', 'strategy')}",
            source="engine",
        )
        self._publish(
            "engine.nodes",
            {"event": "running", "node": self.as_dict(handle)},
        )
        return handle

    def _record_lifecycle(self, node_id: str, status: str, message: str) -> None:
        state = self._require_node(node_id)
        event = NodeLifecycleEvent(timestamp=_utcnow_iso(), status=status, message=message)
        state.lifecycle.append(event)
        self._publish(
            f"engine.nodes.{node_id}.lifecycle",
            {"node_id": node_id, "event": asdict(event)},
        )

    def _append_log(self, node_id: str, level: str, message: str, source: str) -> None:
        state = self._require_node(node_id)
        entry = NodeLogEntry(
            id=uuid.uuid4().hex,
            timestamp=_utcnow_iso(),
            level=level,
            message=message,
            source=source,
        )
        state.logs.append(entry)
        state.handle.updated_at = _utcnow_iso()
        self._publish(
            f"engine.nodes.{node_id}.logs",
            {"node_id": node_id, "log": asdict(entry)},
        )

    def _ensure_metrics_seeded(self, node_id: str) -> None:
        state = self._require_node(node_id)
        if state.metrics:
            return

        base_time = datetime.utcnow() - timedelta(minutes=179)
        pnl = random.uniform(-25.0, 25.0)
        latency = random.uniform(4.0, 16.0)
        cpu = random.uniform(20.0, 55.0)
        memory = random.uniform(480.0, 640.0)

        for step in range(180):
            pnl += random.gauss(0, 0.6)
            latency = max(1.0, latency + random.uniform(-1.2, 1.2))
            cpu = max(3.0, min(97.0, cpu + random.uniform(-3.5, 3.5)))
            memory = max(256.0, memory + random.uniform(-6.0, 6.0))
            timestamp = (base_time + timedelta(minutes=step)).isoformat() + "Z"
            state.metrics.append(
                NodeMetricsSample(
                    timestamp=timestamp,
                    pnl=round(pnl, 2),
                    latency_ms=round(latency, 2),
                    cpu_percent=round(cpu, 2),
                    memory_mb=round(memory, 2),
                )
            )

        self._update_handle_metrics(node_id)

    def _advance_metrics(self, node_id: str) -> NodeMetricsSample:
        self._ensure_metrics_seeded(node_id)
        state = self._require_node(node_id)
        previous = state.metrics[-1]
        pnl = previous.pnl + random.gauss(0, 1.2)
        latency = max(0.8, previous.latency_ms + random.uniform(-1.5, 1.5))
        cpu = max(2.5, min(98.0, previous.cpu_percent + random.uniform(-4.5, 4.5)))
        memory = max(240.0, previous.memory_mb + random.uniform(-9.0, 9.0))
        sample = NodeMetricsSample(
            timestamp=_utcnow_iso(),
            pnl=round(pnl, 2),
            latency_ms=round(latency, 2),
            cpu_percent=round(cpu, 2),
            memory_mb=round(memory, 2),
        )
        state.metrics.append(sample)
        if len(state.metrics) > 720:
            state.metrics = state.metrics[-720:]
        self._update_handle_metrics(node_id)
        return sample

    def _update_handle_metrics(self, node_id: str) -> None:
        state = self._require_node(node_id)
        if not state.metrics:
            state.handle.metrics = {}
            return

        latest = state.metrics[-1]
        state.handle.metrics = {
            "pnl": latest.pnl,
            "latency_ms": latest.latency_ms,
            "cpu_percent": latest.cpu_percent,
            "memory_mb": latest.memory_mb,
        }
        state.handle.updated_at = _utcnow_iso()
        self._publish(
            f"engine.nodes.{node_id}.metrics",
            {
                "node_id": node_id,
                "metrics": {
                    "pnl": latest.pnl,
                    "latency_ms": latest.latency_ms,
                    "cpu_percent": latest.cpu_percent,
                    "memory_mb": latest.memory_mb,
                },
                "timestamp": latest.timestamp,
            },
        )

    def metrics_series(self, node_id: str, limit: int = 360) -> dict:
        self._advance_metrics(node_id)
        state = self._require_node(node_id)
        history = state.metrics[-limit:]

        def build_series(attr: str) -> List[dict]:
            return [
                {"timestamp": sample.timestamp, "value": getattr(sample, attr)}
                for sample in history
            ]

        latest = history[-1] if history else None
        return {
            "series": {
                "pnl": build_series("pnl"),
                "latency_ms": build_series("latency_ms"),
                "cpu_percent": build_series("cpu_percent"),
                "memory_mb": build_series("memory_mb"),
            },
            "latest": asdict(latest) if latest else None,
        }

    def metrics_snapshot(self, node_id: str) -> Dict[str, float]:
        sample = self._advance_metrics(node_id)
        return {
            "pnl": sample.pnl,
            "latency_ms": sample.latency_ms,
            "cpu_percent": sample.cpu_percent,
            "memory_mb": sample.memory_mb,
        }

    def _maybe_append_runtime_activity(self, node_id: str) -> None:
        message = random.choice(
            [
                "Heartbeat received from risk manager",
                "Processed market data batch",
                "Strategy evaluation completed",
                "Order book snapshot normalised",
                "PnL checkpoint persisted",
                "Latency within expected thresholds",
            ]
        )
        level = random.choices(
            population=["info", "debug", "warning"],
            weights=[0.6, 0.3, 0.1],
            k=1,
        )[0]
        source = random.choice(["engine", "risk", "execution", "controller"])
        self._append_log(node_id, level, message, source=source)
        if random.random() < 0.15:
            self._record_lifecycle(node_id, "running", "Heartbeat acknowledged")

    def _require_node(self, node_id: str) -> NodeState:
        state = self._nodes.get(node_id)
        if state is None:
            raise ValueError(f"Node '{node_id}' not found")
        return state


class NautilusService:
    """Facade which delegates to the real engine or mock service.

    Only a literal ``None`` return value from the engine should trigger
    delegation to the mock fallback; empty payloads are considered valid
    engine responses and must be passed through unchanged.
    """

    def __init__(self, engine: Optional[NautilusEngineService] = None) -> None:
        self._engine = engine or build_engine_service()
        self._mock = MockNautilusService(engine=self._engine)

    def __getattr__(self, item: str):  # pragma: no cover - delegation helper
        return getattr(self._mock, item)

    @property
    def engine(self) -> NautilusEngineService:
        return self._engine

    def topic_stream(self, topic: str):
        async def generator():
            async with self._engine.bus.subscribe(topic) as subscription:
                async for payload in subscription:
                    yield payload

        return generator()

    def node_stream(self):
        return self.topic_stream("engine.nodes")

    def node_log_stream(self, node_id: str):
        return self.topic_stream(f"engine.nodes.{node_id}.logs")

    def node_lifecycle_stream(self, node_id: str):
        return self.topic_stream(f"engine.nodes.{node_id}.lifecycle")

    def node_metrics_stream(self, node_id: str):
        return self.topic_stream(f"engine.nodes.{node_id}.metrics")

    def orders_stream(self):
        return self.topic_stream("engine.orders")

    def portfolio_stream(self):
        return self.topic_stream("engine.portfolio")

    def risk_stream(self):
        return self.topic_stream("engine.risk")

    def risk_alert_stream(self):
        return self.topic_stream("engine.risk.alerts")

    def list_instruments(self, venue: Optional[str] = None) -> dict:
        engine_method = getattr(self._engine, "list_instruments", None)
        if callable(engine_method):
            try:
                payload = engine_method(venue=venue)
                # Only ``None`` indicates the engine could not provide data.
                if payload is not None:
                    return payload
            except Exception:
                pass
        return self._mock.list_instruments(venue=venue)

    def get_watchlist(self) -> dict:
        return self._mock.get_watchlist()

    def update_watchlist(self, favorites: List[str]) -> dict:
        return self._mock.update_watchlist(favorites)

    def get_historical_bars(
        self,
        instrument_id: str,
        granularity: str,
        limit: Optional[int] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> dict:
        engine_method = getattr(self._engine, "get_historical_bars", None)
        if callable(engine_method):
            try:
                payload = engine_method(
                    instrument_id=instrument_id,
                    granularity=granularity,
                    limit=limit,
                    start=start,
                    end=end,
                )
                # Only ``None`` indicates the engine could not provide data.
                if payload is not None:
                    return payload
            except Exception:
                pass
        return self._mock.get_historical_bars(
            instrument_id=instrument_id,
            granularity=granularity,
            limit=limit,
            start=start,
            end=end,
        )


svc = NautilusService()
print(f"[NautilusService] core={NT_VERSION} available={nt is not None}")

"""Schemas describing node resources exposed by the gateway API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class NodeLaunchStrategyParameter(BaseModel):
    key: str
    value: str

    model_config = ConfigDict(extra="allow")


class NodeLaunchStrategy(BaseModel):
    id: str
    name: str
    parameters: List[NodeLaunchStrategyParameter]

    model_config = ConfigDict(extra="allow")


class NodeLaunchAdapterSelection(BaseModel):
    venue: str
    alias: Optional[str] = None
    keyId: Optional[str] = Field(default=None, alias="keyId")
    enableData: bool = Field(alias="enableData")
    enableTrading: bool = Field(alias="enableTrading")
    sandbox: Optional[bool] = None
    options: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class NodeLaunchDataSource(BaseModel):
    id: str
    label: str
    type: str
    mode: str
    enabled: bool

    model_config = ConfigDict(extra="allow")


class NodeLaunchKeyReference(BaseModel):
    alias: str
    keyId: str
    required: bool

    model_config = ConfigDict(extra="allow")


class NodeLaunchConstraints(BaseModel):
    maxRuntimeMinutes: Optional[int] = None
    maxDrawdownPercent: Optional[float] = None
    autoStopOnError: bool
    concurrencyLimit: Optional[int] = None

    model_config = ConfigDict(extra="allow")


class NodeLaunchRequest(BaseModel):
    type: str
    strategy: NodeLaunchStrategy
    adapters: List[NodeLaunchAdapterSelection]
    constraints: NodeLaunchConstraints
    dataSources: List[NodeLaunchDataSource] = Field(default_factory=list)
    keyReferences: List[NodeLaunchKeyReference] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class NodeMetrics(BaseModel):
    pnl: Optional[float] = None
    equity: Optional[float] = None
    latency_ms: Optional[float] = None
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    equity_history: Optional[List[float]] = None

    model_config = ConfigDict(extra="allow")


class AdapterStatus(BaseModel):
    node_id: Optional[str] = None
    name: Optional[str] = None
    identifier: Optional[str] = None
    mode: Optional[str] = None
    state: Optional[str] = None
    sandbox: Optional[bool] = None
    sources: Optional[List[str]] = None

    model_config = ConfigDict(extra="allow")


class NodeStrategySummary(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    parameters: Optional[List[NodeLaunchStrategyParameter]] = None

    model_config = ConfigDict(extra="allow")


class NodeSummary(BaseModel):
    external_id: Optional[str] = None
    id: Optional[str] = None
    mode: Optional[str] = None
    status: Optional[str] = None
    detail: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    config_version: Optional[int] = None
    config_source: Optional[str] = None
    config_format: Optional[str] = None
    strategy: Optional[NodeStrategySummary] = None
    metrics: Optional[NodeMetrics] = None
    adapters: Optional[List[AdapterStatus]] = None
    pnl: Optional[float] = None
    equity: Optional[float] = None
    latency_ms: Optional[float] = None
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    error: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class NodeHandleResource(BaseModel):
    id: str
    mode: str
    status: str
    detail: Optional[str] = None
    metrics: Optional[NodeMetrics] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    adapters: Optional[List[AdapterStatus]] = None
    summary: Optional[NodeSummary] = None
    config_version: Optional[int] = None
    db_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="allow")


class NodeResponse(BaseModel):
    node: NodeHandleResource


class NodesListResponse(BaseModel):
    nodes: List[NodeHandleResource]


class NodeLifecycleEvent(BaseModel):
    timestamp: str
    status: str
    message: str

    model_config = ConfigDict(from_attributes=True)


class NodeLogEntry(BaseModel):
    id: str
    timestamp: str
    level: str
    message: str
    source: str

    model_config = ConfigDict(from_attributes=True)


class NodeConfiguration(BaseModel):
    type: Optional[str] = None
    strategy: Optional[Dict[str, Any]] = None
    dataSources: Optional[List[Dict[str, Any]]] = None
    keyReferences: Optional[List[Dict[str, Any]]] = None
    constraints: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")


class NodeDetailResponse(BaseModel):
    node: NodeHandleResource
    config: NodeConfiguration
    lifecycle: List[NodeLifecycleEvent]


class NodeLogsResponse(BaseModel):
    logs: List[NodeLogEntry]

    model_config = ConfigDict(extra="allow")

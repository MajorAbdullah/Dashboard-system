"""Pydantic contract shared by the pipeline, the LLM structured-output calls, and
the frontend renderers. ChartSpec is a superset of the existing dc-runtime widget
object: every field beyond type/title/source/confidence is optional, so a spec with
no data still renders via the legacy seeded path (graceful degradation)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ChartType = Literal[
    "kpi", "area", "line", "bar", "donut", "funnel", "heatmap",
    "forecast", "insight", "risk", "summary", "table",
]
Tone = Literal["pos", "warn", "neg"]


# ---------- request models ----------
class DatasetsRequest(BaseModel):
    global_key: Optional[str] = None


class SignupRequest(BaseModel):
    model_config = {"extra": "ignore"}
    name: Optional[str] = None
    email: str
    company: Optional[str] = None
    password: str
    inflectiv_key: Optional[str] = None
    inflectiv_dataset_id: Optional[int] = None
    inflectiv_dataset_name: Optional[str] = None
    db_type: Optional[str] = None
    db_connection_string: Optional[str] = None
    db_table_name: Optional[str] = None
    onboarding: Optional[dict] = None
    ai_prefs: Optional[dict] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotRequest(BaseModel):
    email: str


class ResetRequest(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    model_config = {"extra": "ignore"}
    name: Optional[str] = None
    company: Optional[str] = None
    ai_prefs: Optional[dict] = None
    inflectiv_dataset_id: Optional[int] = None
    inflectiv_dataset_name: Optional[str] = None
    db_type: Optional[str] = None
    db_connection_string: Optional[str] = None
    db_table_name: Optional[str] = None


class SettingsUpdate(BaseModel):
    settings: dict


class DashboardSave(BaseModel):
    model_config = {"extra": "ignore"}
    name: str
    widgets: list = Field(default_factory=list)
    dataset_id: Optional[int] = None
    dataset_name: Optional[str] = None


class ComponentSave(BaseModel):
    spec: dict
    goal: Optional[str] = None


class TeamInvite(BaseModel):
    email: str
    name: Optional[str] = None
    role: Optional[str] = "member"


class WorkspaceSave(BaseModel):
    model_config = {"extra": "ignore"}
    widgets: list = Field(default_factory=list)
    drafts: list = Field(default_factory=list)
    chatMessages: list = Field(default_factory=list)


class SessionRequest(BaseModel):
    global_key: Optional[str] = None
    dataset_name: Optional[str] = None
    dataset_id: Optional[int] = None
    source_type: str = "inflectiv"
    conn_string: Optional[str] = None
    table_name: Optional[str] = None


class GenerateRequest(BaseModel):
    session_id: str
    goal: str
    job_id: Optional[str] = None


class RefineRequest(BaseModel):
    session_id: str
    message: str
    job_id: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: str
    message: str


# ---------- chart-spec (the heart) ----------
class Datum(BaseModel):
    label: str
    value: float


class TableRow(BaseModel):
    cells: list[str]
    tone: Optional[Tone] = None


class Metric(BaseModel):
    label: str
    value: str


class SourceRef(BaseModel):
    """Provenance — the retrieved chunk a number/claim traces back to."""
    text: str
    score: float = 0.0
    knowledge_source_id: Optional[int] = None


class ChartSpec(BaseModel):
    model_config = {"extra": "ignore"}

    type: ChartType
    title: str
    source: str = ""
    confidence: int = 70  # 0-100, drives the ring + color
    exact: bool = False  # True only when numbers are exact (small-dataset local aggregation)
    grounded: bool = True  # False => values inferred from a sample => "estimated" badge

    # KPI
    label: Optional[str] = None
    value: Optional[str] = None  # already formatted; renderer prints verbatim
    delta: Optional[str] = None
    tone: Optional[Tone] = None

    # single-series (area/line/forecast/kpi sparkline)
    series: Optional[list[float]] = None
    forecastSeries: Optional[list[float]] = None

    # categorical (bar/donut/funnel)  + heatmap grid
    data: Optional[list[Datum]] = None
    grid: Optional[list[list[float]]] = None

    # table
    columns: Optional[list[str]] = None
    rows: Optional[list[TableRow]] = None

    # prose (insight/risk/summary)
    headline: Optional[str] = None
    body: Optional[str] = None
    chips: Optional[list[str]] = None
    metrics: Optional[list[Metric]] = None

    # provenance (attached by the pipeline, not the LLM)
    sources: Optional[list[SourceRef]] = None


class ChatAnswer(BaseModel):
    model_config = {"extra": "ignore"}
    answer: str
    chart: Optional[ChartSpec] = None
    grounded: bool = True
    confidence: int = 70


# ---------- planning ----------
class PlannedChart(BaseModel):
    type: ChartType
    title: str
    needs: list[int] = Field(default_factory=list)  # indices into subqueries


class DashboardPlan(BaseModel):
    model_config = {"extra": "ignore"}
    subqueries: list[str] = Field(default_factory=list)
    charts: list[PlannedChart] = Field(default_factory=list)


# ---------- profiling ----------
class DatasetProfile(BaseModel):
    model_config = {"extra": "ignore"}
    tabular_vs_prose: Literal["tabular", "prose", "mixed"] = "mixed"
    summary: str = ""
    entities: list[str] = Field(default_factory=list)
    numeric_fields: list[str] = Field(default_factory=list)
    categorical_fields: list[str] = Field(default_factory=list)
    suggested_kpis: list[str] = Field(default_factory=list)
    suggested_charts: list[PlannedChart] = Field(default_factory=list)
    suggested_queries: list[str] = Field(default_factory=list)  # NL prompts the user could ask
    size_estimate: Literal["small", "large"] = "large"

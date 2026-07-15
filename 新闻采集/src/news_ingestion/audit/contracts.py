"""业务无关的工作流、漏斗与设计校验值对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ValidationStatus = Literal["compliant", "deviation", "incomplete"]


@dataclass(frozen=True, slots=True)
class StageDefinition:
    key: str
    sequence: int
    unit: str | None = None
    prerequisites: tuple[str, ...] = ()

    def snapshot(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "sequence": self.sequence,
            "unit": self.unit,
            "prerequisites": list(self.prerequisites),
        }


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    name: str
    version: str
    stages: tuple[StageDefinition, ...]
    schema_version: str = "audit-workflow/v1"

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "version": self.version,
            "stages": [stage.snapshot() for stage in self.stages],
        }


@dataclass(frozen=True, slots=True)
class UnitConversion:
    """显式记录单位转换；不同单位不做机械守恒。"""

    input_unit: str
    output_unit: str
    input_count: int | None
    output_count: int | None


@dataclass(frozen=True, slots=True)
class FunnelSnapshot:
    unit: str
    input_count: int | None
    output_count: int | None
    routes: tuple[tuple[str, int | None], ...] = ()
    conversion: UnitConversion | None = None
    schema_version: str = "audit-funnel/v1"

    def snapshot(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "unit": self.unit,
            "input_count": self.input_count,
            "output_count": self.output_count,
            "routes": [{"key": key, "count": count} for key, count in self.routes],
        }
        if self.conversion is not None:
            result["conversion"] = {
                "input_unit": self.conversion.input_unit,
                "output_unit": self.conversion.output_unit,
                "input_count": self.conversion.input_count,
                "output_count": self.conversion.output_count,
            }
        return result


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule_id: str
    status: ValidationStatus
    expected: Any = None
    actual: Any = None
    delta: int | float | None = None
    message: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "status": self.status,
            "expected": self.expected,
            "actual": self.actual,
            "delta": self.delta,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class ValidationConclusion:
    status: ValidationStatus
    results: tuple[RuleResult, ...] = field(default_factory=tuple)
    schema_version: str = "audit-validation/v1"

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "results": [result.snapshot() for result in self.results],
        }


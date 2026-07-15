"""业务审计通用契约：用非新闻工作流证明核心没有领域耦合。"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from news_ingestion.audit.contracts import (
    FunnelSnapshot,
    StageDefinition,
    UnitConversion,
    WorkflowDefinition,
)
from news_ingestion.audit.validation import validate_funnel, validate_workflow


def test_non_news_workflow_and_same_unit_funnels_are_valid() -> None:
    workflow = WorkflowDefinition(
        name="document-publishing",
        version="v1",
        stages=(
            StageDefinition(key="receive", sequence=1, unit="document"),
            StageDefinition(key="render", sequence=2, unit="document", prerequisites=("receive",)),
            StageDefinition(key="publish", sequence=3, unit="document", prerequisites=("render",)),
        ),
    )

    assert validate_workflow(workflow).status == "compliant"
    assert validate_funnel(
        FunnelSnapshot(unit="document", input_count=10, output_count=7, routes=(
            ("rejected", 2),
            ("deferred", 1),
        ))
    ).status == "compliant"
    assert "news" not in repr(workflow).lower()


def test_zero_is_present_but_missing_required_count_is_incomplete() -> None:
    zero = validate_funnel(FunnelSnapshot(unit="record", input_count=0, output_count=0))
    missing = validate_funnel(FunnelSnapshot(unit="record", input_count=None, output_count=0))

    assert zero.status == "compliant"
    assert missing.status == "incomplete"
    assert missing.results[0].rule_id == "audit.funnel.required_counts"


def test_negative_duplicate_route_and_non_conservation_are_deviations() -> None:
    negative = validate_funnel(FunnelSnapshot(unit="record", input_count=-1, output_count=0))
    duplicate = validate_funnel(
        FunnelSnapshot(unit="record", input_count=2, output_count=0, routes=(("dropped", 1), ("dropped", 1)))
    )
    mismatch = validate_funnel(
        FunnelSnapshot(unit="record", input_count=5, output_count=2, routes=(("dropped", 1),))
    )

    assert negative.status == "deviation"
    assert negative.results[0].rule_id == "audit.funnel.non_negative"
    assert duplicate.status == "deviation"
    assert duplicate.results[0].rule_id == "audit.funnel.unique_routes"
    assert mismatch.status == "deviation"
    result = mismatch.results[0]
    assert result.rule_id == "audit.funnel.conservation"
    assert (result.expected, result.actual, result.delta) == (5, 3, -2)


def test_different_units_are_not_compared_without_explicit_conversion() -> None:
    snapshot = FunnelSnapshot(
        unit="article",
        input_count=8,
        output_count=8,
        conversion=UnitConversion(input_unit="article", output_unit="event", input_count=8, output_count=3),
    )

    result = validate_funnel(snapshot)
    assert result.status == "compliant"
    assert any(item.rule_id == "audit.funnel.conservation" for item in result.results)
    assert any(item.rule_id == "audit.funnel.unit_conversion" for item in result.results)


def test_conversion_does_not_hide_same_unit_funnel_deviation() -> None:
    result = validate_funnel(
        FunnelSnapshot(
            unit="document",
            input_count=8,
            output_count=6,
            routes=(("rejected", 1),),
            conversion=UnitConversion(
                input_unit="document",
                output_unit="bundle",
                input_count=6,
                output_count=2,
            ),
        )
    )

    assert result.status == "deviation"
    assert {item.rule_id for item in result.results} == {
        "audit.funnel.conservation",
        "audit.funnel.unit_conversion",
    }


def test_conversion_requires_matching_non_empty_input_unit_and_complete_counts() -> None:
    wrong_unit = validate_funnel(
        FunnelSnapshot(
            unit="document",
            input_count=1,
            output_count=1,
            conversion=UnitConversion(input_unit="article", output_unit="bundle", input_count=1, output_count=1),
        )
    )
    missing = validate_funnel(
        FunnelSnapshot(
            unit="document",
            input_count=1,
            output_count=1,
            conversion=UnitConversion(input_unit="document", output_unit="", input_count=None, output_count=1),
        )
    )

    assert wrong_unit.status == "deviation"
    assert missing.status == "incomplete"


def test_generic_audit_core_does_not_import_news_models() -> None:
    for module_name in (
        "news_ingestion.audit.contracts",
        "news_ingestion.audit.validation",
        "news_ingestion.audit.context",
    ):
        spec = importlib.util.find_spec(module_name)
        assert spec is not None and spec.origin is not None
        tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
        imports = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not any(module.endswith("models") for module in imports)

"""对工作流声明和同单位漏斗执行确定性校验。"""

from __future__ import annotations

from .contracts import FunnelSnapshot, RuleResult, ValidationConclusion, WorkflowDefinition


def _conclusion(results: list[RuleResult]) -> ValidationConclusion:
    if any(result.status == "deviation" for result in results):
        status = "deviation"
    elif any(result.status == "incomplete" for result in results):
        status = "incomplete"
    else:
        status = "compliant"
    return ValidationConclusion(status=status, results=tuple(results))


def validate_workflow(workflow: WorkflowDefinition) -> ValidationConclusion:
    results: list[RuleResult] = []
    keys = [stage.key for stage in workflow.stages]
    sequences = [stage.sequence for stage in workflow.stages]
    if not workflow.name or not workflow.version or not workflow.stages:
        results.append(RuleResult("audit.workflow.required", "incomplete", message="工作流名称、版本和阶段不可缺失"))
        return _conclusion(results)
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        results.append(RuleResult("audit.workflow.unique_stage_keys", "deviation", expected="unique non-empty keys", actual=keys))
    if any(sequence <= 0 for sequence in sequences) or len(sequences) != len(set(sequences)):
        results.append(RuleResult("audit.workflow.unique_sequences", "deviation", expected="unique positive sequences", actual=sequences))
    positions = {stage.key: stage.sequence for stage in workflow.stages}
    violations = [
        (stage.key, prerequisite)
        for stage in workflow.stages
        for prerequisite in stage.prerequisites
        if prerequisite not in positions or positions[prerequisite] >= stage.sequence
    ]
    if violations:
        results.append(RuleResult("audit.workflow.prerequisites", "deviation", expected="existing earlier stages", actual=violations))
    if not results:
        results.append(RuleResult("audit.workflow.definition", "compliant"))
    return _conclusion(results)


def validate_funnel(funnel: FunnelSnapshot) -> ValidationConclusion:
    results: list[RuleResult] = []
    counts = [funnel.input_count, funnel.output_count, *(count for _, count in funnel.routes)]
    if any(count is None for count in counts):
        results.append(
            RuleResult(
                "audit.funnel.required_counts",
                "incomplete",
                expected="all required counts present",
                actual=counts,
                message="缺失不能按零处理",
            )
        )
    elif any(count < 0 for count in counts if count is not None):
        results.append(RuleResult("audit.funnel.non_negative", "deviation", expected=">= 0", actual=counts))
    else:
        route_keys = [key for key, _ in funnel.routes]
        if any(not key for key in route_keys) or len(route_keys) != len(set(route_keys)):
            results.append(RuleResult("audit.funnel.unique_routes", "deviation", expected="unique non-empty routes", actual=route_keys))
        else:
            actual = funnel.output_count + sum(count for _, count in funnel.routes if count is not None)
            if actual != funnel.input_count:
                results.append(
                    RuleResult(
                        "audit.funnel.conservation",
                        "deviation",
                        expected=funnel.input_count,
                        actual=actual,
                        delta=actual - funnel.input_count,
                    )
                )
            else:
                results.append(RuleResult("audit.funnel.conservation", "compliant", expected=funnel.input_count, actual=actual, delta=0))

    if funnel.conversion is not None:
        conversion = funnel.conversion
        conversion_counts = (funnel.conversion.input_count, funnel.conversion.output_count)
        if not conversion.input_unit or not conversion.output_unit or any(count is None for count in conversion_counts):
            results.append(RuleResult("audit.funnel.unit_conversion", "incomplete", expected="non-empty units and counts present", actual={"input_unit": conversion.input_unit, "output_unit": conversion.output_unit, "counts": conversion_counts}))
        elif conversion.input_unit != funnel.unit:
            results.append(RuleResult("audit.funnel.unit_conversion", "deviation", expected=funnel.unit, actual=conversion.input_unit, message="转换输入单位必须等于主漏斗单位"))
        elif any(count < 0 for count in conversion_counts if count is not None):
            results.append(RuleResult("audit.funnel.unit_conversion", "deviation", expected=">= 0", actual=conversion_counts))
        else:
            results.append(
                RuleResult(
                    "audit.funnel.unit_conversion",
                    "compliant",
                    expected=conversion.input_unit,
                    actual=conversion.output_unit,
                    message="单位转换已显式声明，不机械要求跨单位数量相等",
                )
            )
    return _conclusion(results)

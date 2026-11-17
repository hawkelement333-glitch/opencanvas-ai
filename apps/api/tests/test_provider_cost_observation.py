"""Configured tariff plus actual response usage, never a fabricated provider bill."""

from dataclasses import replace

import pytest

from opencanvas_api.services.ai import MockAIProvider, ObservedAIProvider
from opencanvas_api.services.context import ContextBundle
from tests.test_observability import _telemetry


@pytest.mark.parametrize("grounded", [False, True])
async def test_observed_provider_usage_drives_estimated_cost_without_private_content(grounded):
    class UsageProvider(MockAIProvider):
        mock = False

        async def generate(self, instruction, context):
            value = await super().generate(instruction, context)
            return replace(value, input_tokens=1000, output_tokens=100, total_tokens=1100)

        async def generate_grounded(self, instruction, notes_context, sources):
            value = await super().generate_grounded(instruction, notes_context, sources)
            return replace(value, input_tokens=1000, output_tokens=100, total_tokens=1100)

    telemetry, sink = _telemetry()
    provider = ObservedAIProvider(
        UsageProvider(), telemetry, input_cost_per_million=2, output_cost_per_million=12
    )
    context = ContextBundle(node_ids=[], snapshot=[], rendered="private source")
    if grounded:
        await provider.generate_grounded("private question", context, [])
    else:
        await provider.generate("private question", context)
    await telemetry.flush()
    costs = [item for item in sink.signals if item.name == "mobius.provider.cost"]
    assert len(costs) == 1
    assert costs[0].payload["value"] == pytest.approx(0.0032)
    assert costs[0].payload["unit"] == "usd"
    assert "private" not in str([item.as_dict() for item in sink.signals])
    await telemetry.close()


@pytest.mark.parametrize(
    "mock,usage,tariff", [(True, True, 2), (False, False, 2), (False, True, 0)]
)
async def test_mock_missing_usage_or_unconfigured_tariff_never_emit_healthy_zero(
    mock, usage, tariff
):
    class UsageProvider(MockAIProvider):
        async def generate(self, instruction, context):
            value = await super().generate(instruction, context)
            return replace(
                value,
                input_tokens=10 if usage else None,
                output_tokens=5 if usage else None,
                total_tokens=15 if usage else None,
            )

    source = UsageProvider()
    source.mock = mock
    telemetry, sink = _telemetry()
    provider = ObservedAIProvider(
        source, telemetry, input_cost_per_million=tariff, output_cost_per_million=12
    )
    await provider.generate("private", ContextBundle(node_ids=[], snapshot=[], rendered=""))
    await telemetry.flush()
    assert not any(item.name == "mobius.provider.cost" for item in sink.signals)
    await telemetry.close()

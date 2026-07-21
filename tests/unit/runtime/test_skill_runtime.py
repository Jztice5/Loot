"""Skill Runtime boundary and audit tests."""

from __future__ import annotations

import time
import unittest
from uuid import uuid4

from loot.contracts import Market
from loot.contracts.base import ContractModel
from loot.runtime import (
    InMemorySkillAuditLog,
    SkillAlreadyRegisteredError,
    SkillCapability,
    SkillDefinition,
    SkillDefinitionMismatchError,
    SkillExecutionRequest,
    SkillExecutor,
    SkillManifest,
    SkillRegistry,
    SkillRunStatus,
)


class EchoInput(ContractModel):
    """Test input contract."""

    value: str


class EchoOutput(ContractModel):
    """Test output contract."""

    value: str


def make_manifest(
        *,
        timeout_seconds: float = 1,
        capabilities: tuple[SkillCapability, ...] = (
            SkillCapability.READ_CANDIDATE,
        ),
) -> SkillManifest:
    """Build a Crypto-only manifest for tests."""

    return SkillManifest(
        skill_id="crypto.test.echo",
        version="1.0.0",
        markets=(Market.CRYPTO,),
        input_type="EchoInput",
        output_type="EchoOutput",
        timeout_seconds=timeout_seconds,
        capabilities=capabilities,
    )


def make_request(value: object = EchoInput(value="btc")) -> SkillExecutionRequest:
    """Build a request with all trace identifiers."""

    return SkillExecutionRequest(
        run_id=uuid4(),
        correlation_id=uuid4(),
        market=Market.CRYPTO,
        input_snapshot_id=uuid4(),
        input=value,
    )


def slow_handler(value: EchoInput) -> EchoOutput:
    """Provide a deterministic timeout test handler."""

    time.sleep(0.05)
    return EchoOutput(value=value.value)


class SkillRuntimeTest(unittest.TestCase):
    """Verify execution boundaries without external services."""

    def setUp(self) -> None:
        self.registry = SkillRegistry()
        self.audit_log = InMemorySkillAuditLog()
        self.registry.register(
            SkillDefinition(
                manifest=make_manifest(),
                input_type=EchoInput,
                output_type=EchoOutput,
                handler=lambda value: EchoOutput(value=value.value.upper()),
            )
        )

    def executor(
            self,
            capabilities: frozenset[SkillCapability] | None = None,
    ) -> SkillExecutor:
        return SkillExecutor(
            self.registry,
            self.audit_log,
            allowed_capabilities=(
                capabilities
                if capabilities is not None
                else frozenset(SkillCapability)
            ),
        )

    def execute(self, request: SkillExecutionRequest | None = None):
        return self.executor().execute(
            request or make_request(),
            skill_id="crypto.test.echo",
            skill_version="1.0.0",
        )

    def test_success_returns_typed_output_and_audit_trace(self) -> None:
        request = make_request()
        result = self.execute(request)

        self.assertEqual(result.output, EchoOutput(value="BTC"))
        self.assertEqual(result.run.status, SkillRunStatus.SUCCEEDED)
        self.assertEqual(result.run.correlation_id, request.correlation_id)
        self.assertEqual(result.run.input_snapshot_id, request.input_snapshot_id)
        self.assertIsNotNone(result.run.output_digest)
        self.assertEqual(self.audit_log.list_records(), (result.run,))

    def test_unregistered_skill_is_rejected_without_handler_execution(self) -> None:
        result = self.executor().execute(
            make_request(),
            skill_id="crypto.test.missing",
            skill_version="1.0.0",
        )

        self.assertEqual(result.run.status, SkillRunStatus.REJECTED)
        self.assertEqual(result.run.error_code, "SKILL_NOT_REGISTERED")
        self.assertIsNone(result.output)

    def test_market_and_capability_boundaries_reject_before_handler(self) -> None:
        wrong_market = make_request()
        wrong_market = wrong_market.model_copy(update={"market": Market.US_EQUITY})
        market_result = self.execute(wrong_market)
        self.assertEqual(market_result.run.error_code, "MARKET_NOT_ALLOWED")

        capability_result = self.executor(frozenset()).execute(
            make_request(),
            skill_id="crypto.test.echo",
            skill_version="1.0.0",
        )
        self.assertEqual(capability_result.run.error_code, "CAPABILITY_NOT_ALLOWED")

    def test_input_and_output_types_are_enforced(self) -> None:
        input_result = self.execute(make_request(value={"value": "btc"}))
        self.assertEqual(input_result.run.error_code, "INPUT_TYPE_MISMATCH")

        self.registry = SkillRegistry()
        self.audit_log = InMemorySkillAuditLog()
        self.registry.register(
            SkillDefinition(
                manifest=make_manifest(),
                input_type=EchoInput,
                output_type=EchoOutput,
                handler=lambda value: value.value,
            )
        )
        output_result = self.execute()
        self.assertEqual(output_result.run.error_code, "OUTPUT_TYPE_MISMATCH")

    def test_handler_failure_and_timeout_are_distinct(self) -> None:
        self.registry = SkillRegistry()
        self.audit_log = InMemorySkillAuditLog()
        self.registry.register(
            SkillDefinition(
                manifest=make_manifest(),
                input_type=EchoInput,
                output_type=EchoOutput,
                handler=lambda value: (_ for _ in ()).throw(RuntimeError("hidden")),
            )
        )
        failed = self.execute()
        self.assertEqual(failed.run.status, SkillRunStatus.FAILED)
        self.assertEqual(failed.run.error_code, "SKILL_HANDLER_FAILED")

        self.registry = SkillRegistry()
        self.audit_log = InMemorySkillAuditLog()
        self.registry.register(
            SkillDefinition(
                manifest=make_manifest(timeout_seconds=0.01),
                input_type=EchoInput,
                output_type=EchoOutput,
                handler=slow_handler,
            )
        )
        timed_out = self.execute()
        self.assertEqual(timed_out.run.status, SkillRunStatus.TIMED_OUT)
        self.assertEqual(timed_out.run.error_code, "SKILL_TIMEOUT")

    def test_duplicate_version_registration_is_rejected(self) -> None:
        with self.assertRaises(SkillAlreadyRegisteredError):
            self.registry.register(
                SkillDefinition(
                    manifest=make_manifest(),
                    input_type=EchoInput,
                    output_type=EchoOutput,
                    handler=lambda value: EchoOutput(value=value.value),
                )
            )

    def test_manifest_type_declaration_must_match_definition(self) -> None:
        mismatched_manifest = make_manifest().model_copy(
            update={"input_type": "DifferentInput"}
        )

        with self.assertRaises(SkillDefinitionMismatchError):
            SkillRegistry().register(
                SkillDefinition(
                    manifest=mismatched_manifest,
                    input_type=EchoInput,
                    output_type=EchoOutput,
                    handler=lambda value: EchoOutput(value=value.value),
                )
            )


if __name__ == "__main__":
    unittest.main()

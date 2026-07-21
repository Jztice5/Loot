"""可声明、可校验和可审计的 Skill Runtime。

业务描述:
    为 Crypto First Vertical Slice 提供受控的 Skill 执行边界，统一校验 Skill 版本、
    市场范围、输入输出类型、capability 和 timeout。

业务场景:
    Candidate 或 Context Builder 已经确定分析路径后，显式选择一个注册 Skill，运行时
    负责执行前置校验并生成 SkillRunRecord，供后续 EvidenceSet 和 Replay 追踪。

业务原因:
    Agent 和未来 LLM 只能编排已授权 Skill，不能绕过市场路由、Policy Gate 或 Signal
    State Machine。Skill Runtime 先固定边界，避免把网络访问和业务状态修改藏进 handler。

调用链:
    SkillExecutionRequest -> SkillRegistry.resolve -> allowlist/type validation
    -> SkillExecutor -> handler -> typed output + SkillRunRecord

业务规则:
    - Registry 以 ``(skill_id, version)`` 精确寻址，禁止静默覆盖和自动选择最新版本。
    - 未注册、市场越界、capability 越权和输入类型错误时 handler 不得执行。
    - handler 异常、超时和输出类型错误不能伪装成成功。
    - 当前审计只使用内存适配器；Skill Runtime 不修改 Signal、Position 或 Policy 事实。
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Any, Generic, Protocol, TypeVar
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from loot.contracts import Market
from loot.contracts.base import ContractModel, ensure_non_empty, ensure_utc_datetime

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class SkillCapability(StrEnum):
    """Skill 可以声明的最小平台能力。"""

    READ_MARKET_SNAPSHOT = "READ_MARKET_SNAPSHOT"
    READ_CANDIDATE = "READ_CANDIDATE"
    EMIT_EVIDENCE = "EMIT_EVIDENCE"


class SkillRunStatus(StrEnum):
    """一次 Skill 运行的终态。"""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    REJECTED = "REJECTED"


class SkillManifest(ContractModel):
    """Skill 的稳定声明和权限边界。

    业务描述:
        固定 Skill 的身份、版本、市场范围、输入输出模型、超时和能力声明。

    调用链:
        SkillDefinition -> SkillRegistry -> SkillExecutor

    业务规则:
        版本必须由调用方精确选择；运行时只允许执行 manifest 声明且平台 allowlist
        已授权的 capability。
    """

    skill_id: str
    version: str
    markets: tuple[Market, ...] = Field(min_length=1)
    input_type: str
    output_type: str
    timeout_seconds: float = Field(gt=0, le=300)
    capabilities: tuple[SkillCapability, ...] = Field(min_length=1)

    @field_validator("skill_id", "version", "input_type", "output_type")
    @classmethod
    def _required_text_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @model_validator(mode="after")
    def _scope_entries_are_unique(self) -> "SkillManifest":
        if len(set(self.markets)) != len(self.markets):
            raise ValueError("markets must not contain duplicates")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must not contain duplicates")
        return self


class SkillExecutionRequest(ContractModel, Generic[InputT]):
    """绑定一次 Skill 运行的链路和不可变输入快照。"""

    run_id: UUID
    correlation_id: UUID
    market: Market
    input_snapshot_id: UUID
    input: Any


class SkillRunRecord(ContractModel):
    """Skill 执行结果的最小审计事实。"""

    run_id: UUID
    skill_id: str
    skill_version: str
    market: Market
    status: SkillRunStatus
    correlation_id: UUID
    input_snapshot_id: UUID
    started_at: datetime
    finished_at: datetime
    output_digest: str | None = None
    error_code: str | None = None

    @field_validator("skill_id", "skill_version")
    @classmethod
    def _identity_text_is_present(cls, value: str) -> str:
        return ensure_non_empty(value)

    @field_validator("started_at", "finished_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @field_validator("error_code", "output_digest")
    @classmethod
    def _optional_text_is_present(cls, value: str | None) -> str | None:
        return ensure_non_empty(value) if value is not None else None


@dataclass(frozen=True)
class SkillExecutionResult(Generic[OutputT]):
    """返回强类型 Skill 输出和对应审计记录。"""

    output: OutputT
    run: SkillRunRecord


class SkillHandler(Protocol[InputT, OutputT]):
    """Skill handler 的类型约束。"""

    def __call__(self, value: InputT) -> OutputT:
        """执行一次已经通过 Runtime 校验的 Skill。"""


@dataclass(frozen=True)
class SkillDefinition(Generic[InputT, OutputT]):
    """将 manifest、输入输出类型和 handler 绑定为一个不可变定义。"""

    manifest: SkillManifest
    input_type: type[InputT]
    output_type: type[OutputT]
    handler: SkillHandler[InputT, OutputT]


class SkillRegistryError(ValueError):
    """Skill Registry 业务错误基类。"""


class SkillAlreadyRegisteredError(SkillRegistryError):
    """同一 Skill 版本重复注册。"""


class SkillDefinitionMismatchError(SkillRegistryError):
    """Manifest 类型声明与实际 SkillDefinition 不一致。"""


class SkillNotFoundError(SkillRegistryError):
    """未找到精确 Skill 版本。"""


class SkillRegistry:
    """维护不可覆盖的精确 Skill 版本注册表。"""

    def __init__(self) -> None:
        self._definitions: dict[
            tuple[str, str], SkillDefinition[Any, Any]
        ] = {}

    def register(
            self,
            definition: SkillDefinition[InputT, OutputT],
    ) -> None:
        """注册一个唯一的 ``skill_id + version``。"""

        manifest = definition.manifest
        if manifest.input_type != definition.input_type.__name__:
            raise SkillDefinitionMismatchError(
                "manifest input_type does not match definition input_type"
            )
        if manifest.output_type != definition.output_type.__name__:
            raise SkillDefinitionMismatchError(
                "manifest output_type does not match definition output_type"
            )
        key = (definition.manifest.skill_id, definition.manifest.version)
        if key in self._definitions:
            raise SkillAlreadyRegisteredError(
                f"skill is already registered: {key[0]}@{key[1]}"
            )
        self._definitions[key] = definition

    def resolve(
            self,
            skill_id: str,
            skill_version: str,
    ) -> SkillDefinition[Any, Any]:
        """按精确版本解析 Skill，禁止隐式选择最新版本。"""

        key = (skill_id, skill_version)
        try:
            return self._definitions[key]
        except KeyError as error:
            raise SkillNotFoundError(
                f"skill is not registered: {skill_id}@{skill_version}"
            ) from error


class SkillAuditLog(Protocol):
    """SkillRun 审计存储端口。"""

    def append(self, record: SkillRunRecord) -> None:
        """追加不可变的运行记录。"""


class InMemorySkillAuditLog:
    """用于 Phase 0 测试和本地运行的线程安全审计适配器。"""

    def __init__(self) -> None:
        self._records: list[SkillRunRecord] = []
        self._lock = Lock()

    def append(self, record: SkillRunRecord) -> None:
        """追加一条 SkillRun，不允许通过查询结果修改事实。"""

        with self._lock:
            self._records.append(record)

    def list_records(self) -> tuple[SkillRunRecord, ...]:
        """返回按写入顺序排列的不可变审计记录。"""

        with self._lock:
            return tuple(self._records)


class SkillExecutor:
    """执行已注册 Skill 并生成可审计运行结果。

    业务场景:
        Crypto 上游已经确定市场和 Skill 版本时调用；运行时先做权限和契约校验，再
        运行 handler，避免不受控的 Skill 触碰其他市场或下游状态机。

    调用链:
        resolve -> validate market/capability/input -> execute with timeout
        -> validate output -> append audit
    """

    def __init__(
            self,
            registry: SkillRegistry,
            audit_log: SkillAuditLog,
            *,
            allowed_capabilities: frozenset[SkillCapability],
    ) -> None:
        self._registry = registry
        self._audit_log = audit_log
        self._allowed_capabilities = allowed_capabilities

    def execute(
            self,
            request: SkillExecutionRequest[InputT],
            *,
            skill_id: str,
            skill_version: str,
    ) -> SkillExecutionResult[Any]:
        """执行一次 Skill，并将所有终态写入审计日志。"""

        started_at = datetime.now(UTC)
        try:
            definition = self._registry.resolve(skill_id, skill_version)
        except SkillNotFoundError:
            run = self._finish(
                request,
                skill_id,
                skill_version,
                SkillRunStatus.REJECTED,
                started_at,
                error_code="SKILL_NOT_REGISTERED",
            )
            return SkillExecutionResult(output=None, run=run)

        manifest = definition.manifest
        if request.market not in manifest.markets:
            return SkillExecutionResult(
                output=None,
                run=self._finish(
                    request,
                    skill_id,
                    skill_version,
                    SkillRunStatus.REJECTED,
                    started_at,
                    error_code="MARKET_NOT_ALLOWED",
                ),
            )
        if not set(manifest.capabilities).issubset(self._allowed_capabilities):
            return SkillExecutionResult(
                output=None,
                run=self._finish(
                    request,
                    skill_id,
                    skill_version,
                    SkillRunStatus.REJECTED,
                    started_at,
                    error_code="CAPABILITY_NOT_ALLOWED",
                ),
            )
        if not isinstance(request.input, definition.input_type):
            return SkillExecutionResult(
                output=None,
                run=self._finish(
                    request,
                    skill_id,
                    skill_version,
                    SkillRunStatus.REJECTED,
                    started_at,
                    error_code="INPUT_TYPE_MISMATCH",
                ),
            )

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(definition.handler, request.input)
        # noinspection PyBroadException - arbitrary Skill failures become audited FAILED.
        try:
            output = future.result(timeout=manifest.timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            run = self._finish(
                request,
                skill_id,
                skill_version,
                SkillRunStatus.TIMED_OUT,
                started_at,
                error_code="SKILL_TIMEOUT",
            )
            return SkillExecutionResult(output=None, run=run)
        except Exception:  # noqa: BLE001 - audit stable code, never exception text.
            run = self._finish(
                request,
                skill_id,
                skill_version,
                SkillRunStatus.FAILED,
                started_at,
                error_code="SKILL_HANDLER_FAILED",
            )
            return SkillExecutionResult(output=None, run=run)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if not isinstance(output, definition.output_type):
            run = self._finish(
                request,
                skill_id,
                skill_version,
                SkillRunStatus.FAILED,
                started_at,
                error_code="OUTPUT_TYPE_MISMATCH",
            )
            return SkillExecutionResult(output=None, run=run)

        run = self._finish(
            request,
            skill_id,
            skill_version,
            SkillRunStatus.SUCCEEDED,
            started_at,
            output_digest=_digest(output),
        )
        return SkillExecutionResult(output=output, run=run)

    def _finish(
            self,
            request: SkillExecutionRequest[Any],
            skill_id: str,
            skill_version: str,
            status: SkillRunStatus,
            started_at: datetime,
            *,
            output_digest: str | None = None,
            error_code: str | None = None,
    ) -> SkillRunRecord:
        """统一创建并追加终态审计记录。"""

        record = SkillRunRecord(
            run_id=request.run_id,
            skill_id=skill_id,
            skill_version=skill_version,
            market=request.market,
            status=status,
            correlation_id=request.correlation_id,
            input_snapshot_id=request.input_snapshot_id,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            output_digest=output_digest,
            error_code=error_code,
        )
        self._audit_log.append(record)
        return record


def _digest(value: Any) -> str:
    """对成功输出生成不依赖对象地址的审计摘要。"""

    if hasattr(value, "model_dump"):
        serializable = value.model_dump(mode="json")
    else:
        serializable = value
    encoded = json.dumps(
        serializable,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

# 项目文档索引

## 先看哪里

- 当前项目状态：[development/memory.md](development/memory.md)
- 设计分层索引：[architecture/README.md](architecture/README.md)
- 今天/近期计划：[planning/开发计划.md](planning/开发计划.md)
- 本地运行说明：[runbooks/local-run.md](runbooks/local-run.md)

## 架构设计

- 系统宏观架构：[architecture/system/loot-system-architecture-v0.1.md](architecture/system/loot-system-architecture-v0.1.md)
- 核心契约设计：[architecture/contracts/loot-contracts-v0.1.md](architecture/contracts/loot-contracts-v0.1.md)
- 自选与持仓信号监控闭环：[architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md](architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md)
- Signal State Machine：[architecture/signal-state-machine/loot-signal-state-machine-v0.1.md](architecture/signal-state-machine/loot-signal-state-machine-v0.1.md)
- Crypto 行情数据 Provider：[architecture/market-domains/crypto-market-data-provider-v0.1.md](architecture/market-domains/crypto-market-data-provider-v0.1.md)

## 开发过程

- 开发过程索引：[development/log/README.md](development/log/README.md)
- 设计上下文分层过程：[development/log/2026-07-10-context-management.md](development/log/2026-07-10-context-management.md)
- 核心契约骨架过程：[development/log/2026-07-10-contracts-foundation.md](development/log/2026-07-10-contracts-foundation.md)
- Signal State Machine 过程：[development/log/2026-07-10-signal-state-machine.md](development/log/2026-07-10-signal-state-machine.md)
- 过程记录模板：[development/log/TEMPLATE.md](development/log/TEMPLATE.md)

## 评审记录

- 设计分层校对备忘录：[reviews/loot-design-layering-review-2026-07-10.md](reviews/loot-design-layering-review-2026-07-10.md)
- Crypto 行情地基评审：[reviews/crypto-market-data-foundation-review-2026-07-10.md](reviews/crypto-market-data-foundation-review-2026-07-10.md)

## Runbooks

- 本地运行说明：[runbooks/local-run.md](runbooks/local-run.md)
- 上下文健康检查：[runbooks/context-health-check.md](runbooks/context-health-check.md)

## 目录分工

```text
docs/
  architecture/   稳定架构设计：系统级、组件级、功能闭环级设计
  development/    开发记忆和功能点过程记录
  planning/       每日计划和项目管理记录
  reviews/        设计评审、校对和阶段结论
  runbooks/       本地运行、测试、排障手册
```

## 分层原则

- `architecture/system` 只回答系统为什么这样分层、边界在哪里、P1 不做什么。
- `architecture/<component>` 回答某个闭环或组件如何运行、契约是什么、状态如何变化。
- `development/memory.md` 记录当前真实状态，不承载长期架构细节。
- `development/log` 记录一次功能推进中的判断过程、证据、改动和验证。
- `reviews` 记录阶段校对结论，避免设计债和实现债散落在聊天里。
- `runbooks` 记录可复用操作步骤，避免每次从设计文档里翻命令。

## 上下文维护规则

- 临时推理和调试过程进入 `development/log`。
- 当前真实状态和下一步进入 `development/memory.md`。
- 稳定边界、契约和状态机进入 `architecture`。
- 可重复命令和检查步骤进入 `runbooks`。
- 阶段性判断和风险清单进入 `reviews`。

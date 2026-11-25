# 设计说明：UML 图到代码的转换

本文件是实验三报告「根据 UML 图实现代码」一节的技术底稿，
记录实验二的 UML 图如何被翻译成本项目的代码结构。

## 1 分层与实验二组件图的对应关系

实验二的组件图把系统划分为八个模块，本实现按同样的边界落成五个代码层，
模块名与类图、组件图中的命名保持一致，便于对照：

| 实验二组件图模块 | 本项目的代码位置 | 职责 |
|---|---|---|
| 表现层（WebUI / RestApi / AuthInterceptor） | `shared_ledger/ui/`、`shared_ledger/cli.py` | 界面渲染、输入校验、错误提示 |
| 账本与成员模块（LedgerMemberService / InvitationService） | `service/ledger_member_service.py`、`service/invitation_service.py` | 创建账本、邀请与成员管理 |
| 记录与审核模块（RecordService / AuditService） | `service/record_service.py`、`service/audit_service.py` | 草稿、提交、撤回、审核、冲正 |
| 分类模块（CategoryService） | `service/category_service.py` | 分类的创建、停用与删除 |
| 统计与预算模块（StatisticsService / BudgetService） | `service/statistics_service.py`、`service/budget_service.py` | 四项统计与预算执行进度 |
| 结算模块（SettlementService） | `service/settlement_service.py` | 净额计算、转账方案、确认与裁决 |
| 操作日志模块（LogService） | `service/log_service.py` | 关键操作留痕与日志查询 |
| 支撑模块（AmountAllocator / StateGuard / IdempotentGuard / OptimisticLock） | `support/` 四个模块 | 金额分摊、状态机、幂等、乐观锁 |

组件图之外补了三块：

- `domain/` —— 类图中 15 个类与 8 个枚举的实体定义；
- `persistence/` —— 数据层，SQLite 表结构与仓储；
- `service/access.py` —— 权限守卫，把类图中「角色决定可执行用例」这条
  关系落成唯一一处判定点。

## 2 类图到代码的映射

| UML 类图中的类 | 代码位置 | 与类图的差异 |
|---|---|---|
| User | `domain/entities.py::User` | 增加 `password_hash`、`created_at` 两个实现必需的字段 |
| Ledger | `domain/entities.py::Ledger` | 无差异 |
| LedgerMember | `domain/entities.py::LedgerMember` | 增加 `display_name`、`account_name` 两个便于列表展示的冗余字段 |
| Invitation | `domain/entities.py::Invitation` | 增加 `max_uses`（REQ-003 待确认项按可配置处理） |
| Record | `domain/entities.py::Record` | 增加 `reviewed_at`、`reviewer_id` 两个审核留痕字段 |
| ShareItem | `domain/entities.py::ShareItem` | 无差异 |
| RecordTrace | `domain/entities.py::RecordTrace` | 增加 `actor_name` 冗余字段 |
| Category | `domain/entities.py::Category` | 增加 `record_count` 冗余字段 |
| Budget | `domain/entities.py::Budget` | 无差异 |
| StatResult | `domain/entities.py::StatResult` | 增加 `label` 字段用于展示分类名与成员昵称 |
| Settlement | `domain/entities.py::Settlement` | 增加 `snapshot_record_ids` 字段落实快照隔离（REQ-034） |
| SettlementMember | `domain/entities.py::SettlementMember` | 增加 `member_name` 冗余字段 |
| TransferPlanItem | `domain/entities.py::TransferPlanItem` | 增加两个姓名冗余字段 |
| OperationLog | `domain/entities.py::OperationLog` | 增加 `actor_name` 冗余字段 |
| RequestDedup | `domain/entities.py::RequestDedup` | 无差异 |
| 八个枚举 | `domain/enums.py` | 取值完全一致，另外为每个枚举补了 `display_name` 等展示用属性 |

类图上标注的实体方法（`Record.submit/withdraw/approve/reject/voidRecord/
createReversal`、`Settlement.createSettlement/confirm/appeal/verdictBy`）
没有直接写成实体的方法，而是落在对应的服务上：

| 类图方法 | 实际实现位置 | 为什么这样放 |
|---|---|---|
| `Record.submit()` | `RecordService.submit()` | 提交要做权限判定、幂等去重、乐观锁校验与日志写入，四件事必须在一个事务里完成 |
| `Record.withdraw()` | `RecordService.withdraw()` | 同上 |
| `Record.approve()` | `AuditService.approve()` | 审核是管理员的职责，与记录录入者的操作不在一个权限域 |
| `Record.reject()` | `AuditService.reject()` | 同上 |
| `Record.voidRecord()` | `AuditService.void_record()` | 同上 |
| `Record.createReversal()` | `RecordService.create_reversal()` | 发起冲正由录入人或管理员发起，与提交同属记录人的操作 |
| `Settlement.createSettlement()` | `SettlementService.create_settlement()` | 结算只读记录表，不回写 |
| `Settlement.confirm()` | `SettlementService.confirm()` | 同上 |
| `Settlement.appeal()` | `SettlementService.appeal()` | 同上 |
| `Settlement.verdictBy()` | `SettlementService.verdict()` | 裁决是管理员权限 |

这样做有一个直接好处：实体是纯数据，不带任何隐含的副作用，
可以被仓储层安全地读写；所有跨实体的规则集中在服务层，
事务边界也由服务层统一控制。

## 3 三条横切规则为什么单独抽成支撑层

实验二组件图把 `AmountAllocator`、`StateGuard`、`IdempotentGuard`、
`OptimisticLock` 画成支撑模块，原因在实现过程中被具体问题验证：

- **金额分摊（`support/amount_allocator.py`）**：REQ-017 到 REQ-020 四条规则
  互相耦合（精度、上限、均摊、余数归属、分摊合计），且同时被记录服务、
  统计服务、结算服务依赖。分散实现必然出现「记录能存进去但统计算不出来」
  的偏差。实现时还发现 REQ-017（草稿也要校验精度）与 REQ-018（超限金额
  允许存草稿但不允许提交）需要**分级校验**，因此金额校验拆成
  `check_limit` 两个档次。
- **状态机（`support/state_guard.py`）**：记录有六个状态、结算单有四个状态，
  允许的转换表一旦散落在各个接口里，同一条规则在不同入口出现不一致是这类
  系统最常见的缺陷来源。转换表集中在此，业务服务只调用
  `assert_record_transition` / `assert_settlement_transition`。
- **幂等（`support/idempotent_guard.py`）与乐观锁（`support/optimistic_lock.py`）**：
  两者都是「在动手前先看一眼当前状态」的前置校验，且都被多个入口共用，
  抽出来才能保证每个入口都做同样的检查。

## 4 实现过程中发现的几个设计问题

### 4.1 冲正在统计口径里的位置

需求清单里 REQ-024 写「作废与已冲正的记录不进入统计」，REQ-013 又写
「冲正记录审核通过后原记录状态变为已冲正，两条记录在统计中净额相抵」。
这两句话在冲正场景下互相张力：原记录退出统计后，冲正记录单条无法与它相抵。

本实现的处理是（见 `service/statistics_service.py::counted_entries`）：

- 只有「已通过」的记录参与统计（REQ-024 的口径不动）；
- 冲正记录以**相反方向**计入（它与原记录类型相同、金额相同，取负号）；
- 与冲正记录配对的原记录在冲正生效后重新纳入统计并取正号。

这样处理的效果是：**已冲正记录对任何统计总额净贡献恒为零**，
既满足 REQ-013 的「两条记录净额相抵」，也不会让任何已冲正记录单独影响总额；
成员统计同样按分摊明细取反，因此成员的分摊净额也为零
（对应 REQ-014 的验收方法）。

这个口径与实验二 UI 原型中「冲正原记录 R-20261025-0009 · 金额 -¥ 288.00 ·
类型 支出」的呈现方式一致——冲正条目以负额计入同一分类的支出，
该笔金额被完全抵消。

### 4.2 管理员自审豁免与冲正审核的交互

REQ-016 规定管理员本人录入的记录提交后直接置为已通过。由于一本账只有一名
管理员，管理员发起的冲正记录也会走自审豁免路径，直接变为已通过，
不会进入待审核列表。实现时如果只在 `AuditService.approve()` 里处理
「冲正生效」，就会出现**冲正记录已通过但原记录仍是已通过**的不一致状态。

解决办法是把「冲正生效」抽成独立函数 `service/reversal.py::apply_reversal_effect`，
由审核通过与自审豁免两条路径共同调用（`service/reversal.py`）。

### 4.3 日志写入与关键操作的事务关系

REQ-039 要求「日志写入失败时关键操作整体回滚」。为此数据层做了两处配合：

- `Database.transaction()` 提供可嵌套的事务上下文，只有最外层负责提交或回滚；
- 仓储的 `_execute()` 在显式事务内**不立即提交**，由事务上下文统一收口。

于是「改记录状态 + 写记录历史 + 写操作日志」三步要么一起成功、要么一起回滚。

另一方面，越权日志必须**在业务事务回滚之后**补写，否则回滚会把它一起抹掉。
为此 `PermissionDeniedError` 携带账本、操作者与目标对象的上下文，
由 `service/base.py::with_denial_log` 装饰器在事务结束后统一补写。

### 4.4 结算的取数方向是单向的

实验二通信图特别说明结算服务与统计服务之间是单向依赖。实现上体现为：
结算服务只调用 `StatisticsService.counted_entries()` 与 `total_net()` 取数，
从不反过来修改统计口径或记录数据；结算单把计算结果存成快照
（`Settlement.snapshot_record_ids` 与结算成员行），之后账本新增记录
不追溯修改已生成的结算单（REQ-034）。

### 4.5 转账方案的条目数

REQ-031 要求「条目数尽量少的转账条目」但没有给出硬性上限，因此没有写成
断言。实现用的是两轮配对：第一轮先配对**剩余金额完全相等**的两方
（这类配对一次结清双方，是最省的配法），第二轮再按金额从大到小依次配对，
每轮取双方剩余金额的较小值作为转账金额。

需要说明的是，REQ-031 的「验收方法」另有一句「条目数不多于应收方人数与
应付方人数中较小的一方」，这个上限**在数学上不可达**。例如应付方为
−100.00、−40.00，应收方为 +50.00、+90.00，双方各 2 人，上限是 2 条；
但若只用 2 条转账，每位付款人只能整笔付给一位收款人，付 100.00 的人
必须整笔付给某一位收款人，而两位收款人分别只应收 50.00 与 90.00，
都收不下 100.00，因此两行的合法方案根本不存在，最少需要 3 条。

REQ-031 的「正常结果」同时写明「条目数按金额排序后依次配对生成，
不设硬性条数上限」。两条表述存在张力，实现遵循「正常结果」，
并把该论证写进了单元测试 `tests/test_settlement.py` 的 docstring，
以预期失败的形式保留为该需求张力的证据。

## 5 与实验二设计的差异

按任务书要求，实验三的实现与实验二的设计允许有出入，本项目的实际差异：

| 项目 | 实验二设计 | 实验三实现 | 原因 |
|---|---|---|---|
| 持久化 | 未指定 | SQLite 单文件 | 需要真实的数据存取，又不引入第三方依赖 |
| 界面技术 | HTML 原型 | tkinter 桌面界面 | 任务书建议写桌面应用 |
| 账号体系 | 未展开 | PBKDF2 口令散列 | REQ-001 前置条件要求「操作用户处于登录状态」 |
| 冲正统计口径 | 未明确 | 见 4.1 | 需求清单两处表述存在张力，实现时做了取舍并记录 |
| 管理员记录 | 审核列表排除 | 自审豁免直接通过 | REQ-016 的必然结果 |

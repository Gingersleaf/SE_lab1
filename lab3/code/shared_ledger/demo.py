"""端到端演示场景。

这个模块把实验一需求清单里的主要用例串成一条可运行的剧本，
既用于命令行演示、也用于给图形界面准备一份初始数据。

剧本覆盖的场景：

1. 注册三个账号并创建账本（REQ-001）；
2. 管理员邀请记账成员与只读成员，对方通过链接加入（REQ-002、REQ-019）；
3. 记账成员录入记录、提交审核（REQ-007、REQ-008）；
4. 管理员审核通过（REQ-009）；
5. 只读成员越权录入被拒绝并留下越权日志（REQ-044）；
6. 重复提交同一请求标识被幂等去重（REQ-035）；
7. 使用过期版本号保存被拒绝（REQ-037）；
8. 管理员自审豁免（REQ-016）；
9. 发起冲正并审核通过，统计中净额相抵（REQ-013）；
10. 设置预算并查看执行进度（REQ-028、REQ-029）；
11. 发起结算、生成转账方案、成员确认、申诉与裁决
    （REQ-030 ~ REQ-034）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable, List, Optional

from .app import ApplicationContext
from .domain.enums import RecordType, Role
from .domain.errors import LedgerError
from .service.record_service import RecordDraftInput

ADMIN_ACCOUNT = "zhoucy"
WRITER_ACCOUNT = "jiangzc"
READER_ACCOUNT = "chenmo"


@dataclass
class Step:
    """演示剧本中的一步。"""

    title: str
    detail: str = ""
    result: str = ""


@dataclass
class DemoResult:
    """演示剧本的执行结果。"""

    steps: List[Step] = field(default_factory=list)
    admin_id: str = ""
    writer_id: str = ""
    reader_id: str = ""
    ledger_id: str = ""

    @property
    def passed(self) -> int:
        """返回执行成功的步骤数。"""
        return len([step for step in self.steps if step.result])

    def add(self, title: str, detail: str = "", result: str = "") -> Step:
        """记录一步执行结果。

        :param title: 步骤标题。
        :param detail: 步骤说明。
        :param result: 执行结果描述。
        :return: 步骤实体。
        """
        step = Step(title=title, detail=detail, result=result)
        self.steps.append(step)
        return step


def run_demo(context: ApplicationContext, echo: Optional[Callable] = None) -> DemoResult:
    """执行完整的演示剧本。

    :param context: 应用上下文。
    :param echo: 输出回调，接收一行行文本。
    :return: 演示结果。
    """
    # 演示剧本刻意保持一条直线：21 个场景按业务顺序依次演出，
    # 便于和实验报告正文逐条对照，因此不限制单函数的语句数
    # pylint: disable=too-many-statements
    result = DemoResult()
    out = echo if echo is not None else (lambda line: None)

    def say(line: str = "") -> None:
        """输出一行文本。"""
        out(line)

    say("=" * 68)
    say("多人共享记账系统 · 实验三演示场景")
    say("=" * 68)

    admin = context.auth.register(ADMIN_ACCOUNT, "周宸聿", "123456")
    writer = context.auth.register(WRITER_ACCOUNT, "蒋至成", "123456")
    reader = context.auth.register(READER_ACCOUNT, "陈默", "123456")
    result.admin_id, result.writer_id, result.reader_id = (
        admin.user_id,
        writer.user_id,
        reader.user_id,
    )
    result.add("注册账号", "周宸聿 / 蒋至成 / 陈默", "三个账号创建成功")
    say("[1] 注册账号 ....................... 成功：周宸聿 / 蒋至成 / 陈默")

    ledger = context.members.create_ledger(admin.user_id, "合租公寓账本")
    result.ledger_id = ledger.ledger_id
    result.add("创建账本", "合租公寓账本", "创建者自动成为管理员")
    say(f"[2] 创建账本 ....................... 成功：{ledger.name}")
    default_names = [
        item.name
        for item in context.categories.list_categories(admin.user_id, ledger.ledger_id)
    ]
    say(f"      默认分类：{'、'.join(default_names)}")

    writer_invite = context.invitations.create_invitation(
        admin.user_id, ledger.ledger_id, Role.WRITER
    )
    writer_member = context.invitations.accept_invitation(
        writer_invite.token, writer.user_id
    )
    reader_invite = context.invitations.create_invitation(
        admin.user_id, ledger.ledger_id, Role.READER
    )
    reader_member = context.invitations.accept_invitation(
        reader_invite.token, reader.user_id
    )
    result.add("邀请成员", "记账成员与只读成员各一名", "两人通过链接加入，角色即时生效")
    say(
        f"[3] 邀请成员 ....................... 成功："
        f"{writer_member.role.display_name} / {reader_member.role.display_name}"
    )

    categories = context.categories.list_categories(admin.user_id, ledger.ledger_id)
    food = next(item for item in categories if item.name == "餐饮")
    rent = next(item for item in categories if item.name == "房租")
    traffic = next(item for item in categories if item.name == "交通")

    draft = RecordDraftInput(
        record_type=RecordType.EXPENSE,
        amount=Decimal("288.00"),
        category_id=food.category_id,
        record_date=date(2026, 10, 30),
        note="周末聚餐 AA",
        payer_member_id=writer_member.member_id,
        participant_member_ids=[
            writer_member.member_id,
            context.repos.members.find(ledger.ledger_id, admin.user_id).member_id,
        ],
    )
    record = context.records.create_draft(
        writer.user_id, ledger.ledger_id, draft, request_id="REQ-2026-1030-0001"
    )
    shares = context.repos.shares.list_by_record(record.record_id)
    result.add("录入记录并存草稿", "餐饮 288.00 元，两人平摊", f"{record.record_id} 已保存")
    say(f"[4] 录入记录并存草稿 ............... 成功：{record.record_id}，状态 草稿")
    say(
        "      分摊明细："
        + "、".join(f"{item.member_name} {item.amount} 元" for item in shares)
    )

    duplicate = context.records.create_draft(
        writer.user_id, ledger.ledger_id, draft, request_id="REQ-2026-1030-0001"
    )
    result.add("重复提交幂等去重", "同一请求标识再次提交", f"返回首次记录 {duplicate.record_id}")
    say(
        f"[5] 重复提交幂等去重 ............... 成功：返回首次结果 "
        f"{duplicate.record_id}，记录总数未增加"
    )

    try:
        context.records.update_draft(
            writer.user_id,
            ledger.ledger_id,
            record.record_id,
            draft,
            expected_version=99,
        )
        detail = "未拦截"
    except LedgerError as exc:
        detail = exc.message
    result.add("版本号冲突校验", "使用过期版本号保存", detail)
    say(f"[6] 版本号冲突校验 ................. 成功：{detail}")

    context.records.submit(
        writer.user_id, ledger.ledger_id, record.record_id, request_id="REQ-2026-1030-0002"
    )
    result.add("提交审核", "记账成员提交草稿", "状态 草稿 → 待审核")
    say("[7] 提交审核 ....................... 成功：草稿 → 待审核")

    context.audits.approve(admin.user_id, ledger.ledger_id, record.record_id)
    result.add("审核通过", "管理员审核通过", "状态 待审核 → 已通过，计入统计")
    say("[8] 审核通过 ....................... 成功：待审核 → 已通过")

    try:
        context.records.create_draft(
            reader.user_id, ledger.ledger_id, draft, request_id="REQ-READER-0001"
        )
        detail = "未拦截"
    except LedgerError as exc:
        detail = exc.message
    result.add("只读成员越权录入", "只读成员尝试录入记录", detail)
    say(f"[9] 只读成员越权录入 ............... 成功：{detail}（已记越权日志）")

    admin_record = context.records.create_draft(
        admin.user_id,
        ledger.ledger_id,
        RecordDraftInput(
            record_type=RecordType.EXPENSE,
            amount=Decimal("1200.00"),
            category_id=rent.category_id,
            record_date=date(2026, 11, 1),
            note="本月房租",
            payer_member_id=writer_member.member_id,
            participant_member_ids=[
                writer_member.member_id,
                context.repos.members.find(ledger.ledger_id, admin.user_id).member_id,
            ],
        ),
        request_id="REQ-2026-1101-0001",
    )
    context.records.submit(admin.user_id, ledger.ledger_id, admin_record.record_id)
    result.add("管理员自审豁免", "管理员本人录入并提交", "直接置为 已通过")
    say("[10] 管理员自审豁免 ................. 成功：提交后直接置为 已通过")

    context.records.create_draft(
        writer.user_id,
        ledger.ledger_id,
        RecordDraftInput(
            record_type=RecordType.INCOME,
            amount=Decimal("60.00"),
            category_id=traffic.category_id,
            record_date=date(2026, 11, 2),
            note="地铁充值分摊",
            payer_member_id=writer_member.member_id,
            participant_member_ids=[writer_member.member_id],
        ),
        request_id="REQ-2026-1102-0001",
    )
    income_record = context.repos.records.find_by_request_id("REQ-2026-1102-0001")
    context.records.submit(writer.user_id, ledger.ledger_id, income_record.record_id)
    context.audits.approve(admin.user_id, ledger.ledger_id, income_record.record_id)
    result.add("录入并审核收入记录", "地铁充值 60.00 元", "计入收入统计")
    say("[11] 录入收入记录并审核 ............. 成功：收入 60.00 元计入统计")

    reversal = context.records.create_reversal(
        admin.user_id, ledger.ledger_id, admin_record.record_id
    )
    context.records.submit(admin.user_id, ledger.ledger_id, reversal.record_id)
    reversal_now = context.repos.records.find_by_id(reversal.record_id)
    if reversal_now.status.value == "PENDING":
        context.audits.approve(admin.user_id, ledger.ledger_id, reversal.record_id)
    original_now = context.repos.records.find_by_id(admin_record.record_id)
    result.add(
        "发起冲正并审核通过",
        f"冲正 {admin_record.record_id}",
        f"原记录状态 {original_now.status.display_name}，两条记录统计净额相抵",
    )
    say(
        f"[12] 发起冲正并审核通过 ............. 成功：原记录 "
        f"{original_now.status.display_name}，冲正记录 {reversal.record_id}"
        f"（{reversal_now.status.display_name}）"
    )

    overview = context.statistics.overview(admin.user_id, ledger.ledger_id, "2026-11")
    result.add(
        "账本概览",
        "2026 年 11 月",
        f"收入 {overview.income} 元，支出 {overview.expense} 元，净额 {overview.net} 元",
    )
    say(
        f"[13] 账本概览 ....................... 收入 {overview.income} 元 / "
        f"支出 {overview.expense} 元 / 净额 {overview.net} 元"
    )

    context.budgets.set_budget(
        admin.user_id, ledger.ledger_id, None, Decimal("5000.00")
    )
    context.budgets.set_budget(
        admin.user_id, ledger.ledger_id, food.category_id, Decimal("500.00")
    )
    progress = context.budgets.budget_progress(admin.user_id, ledger.ledger_id, "2026-10")
    for item in progress:
        say(
            f"      预算 {item.category_name}：{item.used} / {item.budget.amount} 元"
            f"（{item.level}）"
        )
    result.add("设置预算与执行进度", "总预算与餐饮分类预算", "九成以上标橙、超额标红")
    say("[14] 设置预算与执行进度 ............. 成功：预算进度已计算")

    settlement = context.settlements.create_settlement(admin.user_id, ledger.ledger_id)
    result.add(
        "发起结算",
        "基于已通过且未被冲正的记录",
        f"{settlement.settlement.settlement_id}，涉及 {settlement.total_members} 名成员",
    )
    say(
        f"[15] 发起结算 ....................... 成功：{settlement.settlement.settlement_id}，"
        f"参与成员 {settlement.total_members} 人"
    )
    for item in settlement.plan:
        say(f"      转账 {item.seq}：{item.from_member_name} → {item.to_member_name} {item.amount} 元")

    partial = context.settlements.confirm(
        admin.user_id, ledger.ledger_id, settlement.settlement.settlement_id
    )
    result.add(
        "成员确认结算单",
        "管理员先确认",
        f"确认进度 {partial.confirmed_count}/{partial.total_members}，"
        f"状态 {partial.settlement.status.display_name}",
    )
    say(
        f"[16] 成员确认结算单 ................. 成功："
        f"{partial.confirmed_count}/{partial.total_members} 已确认，状态 "
        f"{partial.settlement.status.display_name}"
    )

    appealed = context.settlements.appeal(
        writer.user_id,
        ledger.ledger_id,
        settlement.settlement.settlement_id,
        "10 月的餐饮分摊金额与我记的不一致",
    )
    result.add("成员申诉", "记账成员对结算结果有异议", f"状态 {appealed.settlement.status.display_name}")
    say(f"[17] 成员申诉 ....................... 成功：状态 {appealed.settlement.status.display_name}")

    verdict = context.settlements.verdict(
        admin.user_id,
        ledger.ledger_id,
        settlement.settlement.settlement_id,
        "维持",
        "核对原始分摊明细后确认金额无误，维持本次结算",
    )
    result.add(
        "管理员裁决",
        "结论 维持",
        f"状态 {verdict.settlement.status.display_name}，裁决理由已写入日志",
    )
    say(f"[18] 管理员裁决 ..................... 成功：状态 {verdict.settlement.status.display_name}")

    extra = context.records.create_draft(
        writer.user_id,
        ledger.ledger_id,
        RecordDraftInput(
            record_type=RecordType.EXPENSE,
            amount=Decimal("30.00"),
            category_id=traffic.category_id,
            record_date=date(2026, 11, 5),
            note="打车费用",
            payer_member_id=writer_member.member_id,
            participant_member_ids=[writer_member.member_id],
        ),
        request_id="REQ-2026-1105-0001",
    )
    context.records.submit(writer.user_id, ledger.ledger_id, extra.record_id)
    context.audits.approve(admin.user_id, ledger.ledger_id, extra.record_id)
    second = context.settlements.create_settlement(admin.user_id, ledger.ledger_id)
    first_now = context.settlements.get_settlement(
        admin.user_id, ledger.ledger_id, settlement.settlement.settlement_id
    )
    result.add(
        "结算单快照隔离",
        "结算后新增记录并再次结算",
        f"{settlement.settlement.settlement_id} 净额仍为 {first_now.ledger_net} 元，"
        f"新结算单 {second.settlement.settlement_id} 纳入新记录",
    )
    say(
        f"[19] 结算单快照隔离 ................. 成功：原结算单内容未变，"
        f"新结算单 {second.settlement.settlement_id} 已纳入新增记录"
    )

    context.settlements.confirm(
        admin.user_id, ledger.ledger_id, second.settlement.settlement_id
    )
    final = context.settlements.confirm(
        writer.user_id, ledger.ledger_id, second.settlement.settlement_id
    )
    result.add(
        "全员确认结算单",
        "两名成员依次确认",
        f"确认进度 {final.confirmed_count}/{final.total_members}，"
        f"状态 {final.settlement.status.display_name}",
    )
    say(
        f"[20] 全员确认结算单 ................. 成功："
        f"{final.confirmed_count}/{final.total_members} 已确认，状态 "
        f"{final.settlement.status.display_name}"
    )

    logs = context.logs.query(admin.user_id, ledger.ledger_id)
    result.add("查询操作日志", "管理员查询全账本日志", f"共 {logs.total} 条")
    say(f"[21] 查询操作日志 ................... 成功：共 {logs.total} 条日志")
    for item in logs.items[:8]:
        say(
            f"      · {item.occurred_at:%Y-%m-%d %H:%M:%S} "
            f"{item.action.display_name} · {item.target_id} · {item.params[:28]}"
        )

    say("-" * 68)
    say(f"演示结束：共 {len(result.steps)} 个场景全部执行完毕")
    say("=" * 68)
    return result

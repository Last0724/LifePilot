"""LifePilot 的确定性周调度器（Scheduler V1）。

设计约定
--------
* 时间都是 naive 本地时间；区间使用左闭右开 ``[start, end)``。
* 一周从 ``questionnaire.week_start``（周一）00:00 开始，共 7 天。
* 一次性的 ``TaskInput`` 只能落在 ``work_days`` 与
  ``preferred_work_start`` ~ ``preferred_work_end`` 组成的每日工作时间窗内；
  ``PredictableRoutine`` 由自己的 ``weekdays`` 决定星期，不受 ``work_days``
  排除，但仍使用同一每日工作时间窗并扣除受保护区间。
* 不拆分任务：每个任务必须获得一个连续空档，长度等于
  :attr:`TaskInput.planned_minutes`。
* 不会把任务排到 ``now`` 之前；``build_schedule`` 默认用当前本地时间，
  测试可通过 ``now`` 参数固定。
* deadline 分三种情况：
  - 已经逾期（``deadline <= now``）：仍然安排到最早的未来空档，并写入
    ``Deadline Overdue`` 警告；它只表示实际截止时间已过，不是排程结束时间
    已过；
  - 尚未到期：作为硬约束，任务必须不晚于 deadline 结束，否则不排；
  - 没有 deadline：排在所有有 deadline 的任务之后，再按重要性 rank 和
    输入顺序。
  “本周排不下”不等于“已逾期”，两者不能混为一谈。
* 受保护区间（固定承诺、休息时段）之间任意两种重叠都会被显式报告，
  所有区间都保留，重叠部分不会被安排任务。
* 用户锁定的 :class:`ScheduledItem` 会尽量保留原时间并占用该时段；它
  不是 ``FixedCommitment``，不能违反 deadline、工作时间或与其他锁定块
  冲突。不满足时释放锁、写入警告，再按普通任务重新排程。

调度顺序（与产品契约一致）
--------------------------
1. 预留 ``FixedCommitment``。
2. 预留 ``RestPeriod``（按“休息开始的那一天”展开，支持跨夜）。
3. 保留通过校验的锁定时间块。
4. 安排 ``PredictableRoutine`` 重复活动：每个配置的星期各排一次，
   优先使用偏好时间（若提供），否则使用该天最早可用空档；不加缓冲。
5. 安排 ``PREDICTABLE`` 日常：先尝试完整落在偏好窗口内，失败后退化为
   任意可用空档。
6. 安排 ``UNCERTAIN`` 任务：Earliest Deadline First；deadline 相同按
   ``TaskInput.effective_importance_rank``（1 最小、最重要）；仍相同则
   保持问卷中的输入顺序。

``PredictableRoutine`` 通过一个只用于日历展示的合成 :class:`TaskInput`
接入现有排程管线（``category="predictable_routine"``、``PREDICTABLE``
时长类型，因此没有 20% 缓冲）。原始 routine 仍是问卷中的事实来源；合成
任务不会写回 ``QuestionnaireData.tasks``。

``build_schedule`` 是模块唯一公开入口，返回
:class:`~core.models.ScheduleResult`。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable

from .models import (
    DurationType,
    FixedCommitment,
    PredictableRoutine,
    QuestionnaireData,
    RestPeriod,
    ScheduleResult,
    ScheduledItem,
    TaskInput,
    UnscheduledTask,
    parse_hhmm,
)

__all__ = ["build_schedule"]

#: 半开区间 ``[start, end)``。
Interval = tuple[datetime, datetime]


# ---------------------------------------------------------------------------
# 时间区间工具
# ---------------------------------------------------------------------------


def _at(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock)


def _clip(interval: Interval, window: Interval) -> Interval | None:
    """返回区间与窗口的交集；没有交集时返回 ``None``。"""
    start = max(interval[0], window[0])
    end = min(interval[1], window[1])
    if start < end:
        return (start, end)
    return None


def _merge(intervals: Iterable[Interval]) -> list[Interval]:
    """合并重叠或首尾相接的区间（首尾相接可安全合并）。"""
    ordered = sorted((start, end) for start, end in intervals if start < end)
    merged: list[Interval] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _subtract(window: Interval, blockers: Iterable[Interval]) -> list[Interval]:
    """从窗口里扣除所有阻塞区间，返回剩余的空档。"""
    free: list[Interval] = []
    cursor = window[0]
    for block_start, block_end in _merge(blockers):
        if block_end <= cursor:
            continue
        if block_start >= window[1]:
            break
        if block_start > cursor:
            free.append((cursor, min(block_start, window[1])))
        cursor = max(cursor, block_end)
        if cursor >= window[1]:
            break
    if cursor < window[1]:
        free.append((cursor, window[1]))
    return [(start, end) for start, end in free if start < end]


def _reserve(slots: list[Interval], start: datetime, end: datetime) -> list[Interval]:
    """把 ``[start, end)`` 从空档列表中扣除。"""
    remaining: list[Interval] = []
    for slot_start, slot_end in slots:
        if end <= slot_start or start >= slot_end:
            remaining.append((slot_start, slot_end))
            continue
        if slot_start < start:
            remaining.append((slot_start, start))
        if end < slot_end:
            remaining.append((end, slot_end))
    return remaining


def _format(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 受保护区间：固定承诺 + 休息时段
# ---------------------------------------------------------------------------


def _fixed_occurrences(
    questionnaire: QuestionnaireData,
    week_start: datetime,
    week_end: datetime,
) -> list[tuple[FixedCommitment, datetime, datetime]]:
    """返回与本周有交集的固定承诺，保留原始起止时间用于冲突提示。"""
    occurrences: list[tuple[FixedCommitment, datetime, datetime]] = []
    for commitment in questionnaire.fixed_commitments:
        if commitment.end <= week_start or commitment.start >= week_end:
            continue
        occurrences.append((commitment, commitment.start, commitment.end))
    occurrences.sort(key=lambda occurrence: occurrence[1])
    return occurrences


def _rest_occurrences(
    questionnaire: QuestionnaireData,
    week_start: datetime,
    week_end: datetime,
) -> list[tuple[RestPeriod, datetime, datetime]]:
    """把每周重复的休息时段展开成本周的具体区间。

    ``RestPeriod.days`` 表示“休息开始”的星期几，因此除了本周的 0~6 天，
    还要看「上周日」开始的跨夜休息是否延伸进本周一凌晨。
    休息时长小于 24 小时，所以上周日之前的 occurrence 不可能影响本周。
    """
    occurrences: list[tuple[RestPeriod, datetime, datetime]] = []
    for period in questionnaire.rest_periods:
        start_clock = parse_hhmm(period.start_time)
        duration = timedelta(minutes=period.duration_minutes)
        for offset in range(-1, 7):
            day = questionnaire.week_start + timedelta(days=offset)
            if day.weekday() not in period.days:
                continue
            start = _at(day, start_clock)
            end = start + duration
            if end <= week_start or start >= week_end:
                continue
            occurrences.append((period, start, end))
    occurrences.sort(key=lambda occurrence: occurrence[1])
    return occurrences


#: 中文星期名，仅用于给用户解释未排原因。
_WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _routine_adapter_task(
    routine: PredictableRoutine,
    task_id: str,
) -> TaskInput:
    """把 routine 的一个星期 occurrence 包装成仅供日历展示的 TaskInput。

    这不是用户任务，不会写回问卷；``PREDICTABLE`` 保证 ``planned_minutes``
    原样等于 ``estimated_minutes``，因此不会加 20% 缓冲。
    """
    return TaskInput(
        title=routine.title,
        estimated_minutes=routine.estimated_minutes,
        id=task_id,
        category="predictable_routine",
        duration_type=DurationType.PREDICTABLE,
        notes="由 PredictableRoutine 生成的日历占位任务，不是用户输入任务。",
    )


def _routine_occurrences(
    questionnaire: QuestionnaireData,
) -> list[tuple[int, PredictableRoutine, TaskInput]]:
    """把每个 routine 按 ``weekdays`` 展开成本周的 occurrence。

    返回 ``(weekday, routine, synthetic_task)``；synthetic_task 的 id 以
    ``routine-`` 开头，并避开所有真实任务 id。
    """
    used_ids = {task.id for task in questionnaire.tasks}
    occurrences: list[tuple[int, PredictableRoutine, TaskInput]] = []
    for routine_index, routine in enumerate(
        questionnaire.predictable_routines, start=1
    ):
        for weekday in routine.weekdays:
            base_id = f"routine-{routine_index}-{weekday}"
            task_id = base_id
            suffix = 2
            while task_id in used_ids:
                task_id = f"{base_id}-{suffix}"
                suffix += 1
            used_ids.add(task_id)
            occurrences.append(
                (
                    weekday,
                    routine,
                    _routine_adapter_task(routine, task_id),
                )
            )
    return occurrences


def _place_routine(
    routine: PredictableRoutine,
    weekday: int,
    task: TaskInput,
    free_by_day: dict[int, list[Interval]],
    week_start: date,
) -> ScheduledItem | None:
    """在 routine 指定的星期内安排一次活动。

    有偏好时间时先尝试偏好时间/窗口，失败后退化为该天任意可用空档。
    活动不跨天，且不加缓冲。
    """
    slots = free_by_day.get(weekday)
    if not slots:
        return None

    day = week_start + timedelta(days=weekday)
    duration = routine.estimated_minutes
    start: datetime | None = None

    if routine.preferred_start is not None:
        preferred_start = _at(day, parse_hhmm(routine.preferred_start))
        preferred_slots: list[Interval] = []
        if routine.preferred_end is not None:
            preferred_end = _at(day, parse_hhmm(routine.preferred_end))
            for slot in slots:
                clipped = _clip(slot, (preferred_start, preferred_end))
                if clipped is not None:
                    preferred_slots.append(clipped)
        else:
            for slot_start, slot_end in slots:
                if slot_end <= preferred_start:
                    continue
                preferred_slots.append((max(slot_start, preferred_start), slot_end))
        start = _find_start(preferred_slots, duration, None)

    if start is None:
        start = _find_start(slots, duration, None)
    if start is None:
        return None

    end = start + timedelta(minutes=duration)
    free_by_day[weekday] = _reserve(slots, start, end)
    return ScheduledItem(task, start, end)


def _routine_unscheduled_reason(
    routine: PredictableRoutine,
    weekday: int,
) -> str:
    day_name = _WEEKDAY_NAMES[weekday]
    return (
        f"{day_name} 找不到连续 {routine.estimated_minutes} 分钟的空档"
        "（已考虑固定承诺、休息时段、锁定块和其他日程）。"
    )


def _overlap_warnings(
    fixed: list[tuple[FixedCommitment, datetime, datetime]],
    rests: list[tuple[RestPeriod, datetime, datetime]],
    week_start: datetime,
    week_end: datetime,
) -> list[str]:
    """报告所有类型的受保护区间重叠。

    三种组合都必须显式报告：固定承诺 × 固定承诺、休息时段 × 休息时段、
    固定承诺 × 休息时段。所有区间都保留，调度器只把它们的并集当作阻塞时间，
    绝不覆盖或删除任何一个区间。
    """
    labelled: list[tuple[str, str, datetime, datetime]] = []
    for commitment, start, end in fixed:
        labelled.append(("固定承诺", commitment.title, start, end))
    for period, start, end in rests:
        labelled.append(("休息时段", period.title, start, end))

    warnings: list[str] = []
    for index, (left_kind, left_title, left_start, left_end) in enumerate(labelled):
        for right_kind, right_title, right_start, right_end in labelled[index + 1 :]:
            overlap_start = max(left_start, right_start)
            overlap_end = min(left_end, right_end)
            if overlap_start >= overlap_end:
                continue
            # 只报告落在本周范围内的冲突，避免提示用户看不到的日期。
            if overlap_end <= week_start or overlap_start >= week_end:
                continue
            warnings.append(
                f"{left_kind} {left_title!r} 与 {right_kind} {right_title!r} 重叠"
                f"（{_format(overlap_start)} ~ {_format(overlap_end)}）；"
                "两者均被保留，重叠时间不会安排任务。"
            )
    return warnings


# ---------------------------------------------------------------------------
# 排程主体
# ---------------------------------------------------------------------------


def _work_offsets(questionnaire: QuestionnaireData) -> list[int]:
    """返回本周可排程的 day offset（0=周一），保持星期顺序。"""
    return [
        offset
        for offset in range(7)
        if (questionnaire.week_start + timedelta(days=offset)).weekday()
        in questionnaire.work_days
    ]


def _free_slots_by_day(
    questionnaire: QuestionnaireData,
    offsets: list[int],
    blockers: list[Interval],
) -> dict[int, list[Interval]]:
    """按给定 day offset 计算每日工作时间窗内的可用空档。

    ``offsets`` 可以包含 ``work_days`` 之外的星期：``PredictableRoutine``
    的 recurrence 由它自己的 ``weekdays`` 决定，不能被 ``work_days`` 排除；
    两种 offset 共用同一个每日工作时间窗，并同样扣除固定承诺/休息时段。
    """
    start_clock, end_clock = questionnaire.work_window
    free: dict[int, list[Interval]] = {}
    for offset in offsets:
        day = questionnaire.week_start + timedelta(days=offset)
        window = (_at(day, start_clock), _at(day, end_clock))
        free[offset] = _subtract(window, blockers)
    return free


def _find_start(
    slots: list[Interval],
    duration_minutes: int,
    deadline: datetime | None,
) -> datetime | None:
    """在空档中找最早的可放置起点；deadline 是硬截止。"""
    need = timedelta(minutes=duration_minutes)
    for slot_start, slot_end in slots:
        if deadline is not None:
            if slot_start >= deadline:
                continue
            if slot_end > deadline:
                slot_end = deadline
        if slot_end - slot_start >= need:
            return slot_start
    return None


def _place(
    task: TaskInput,
    offset: int,
    free_by_day: dict[int, list[Interval]],
    start: datetime,
) -> ScheduledItem:
    duration = timedelta(minutes=task.planned_minutes)
    end = start + duration
    free_by_day[offset] = _reserve(free_by_day[offset], start, end)
    return ScheduledItem(task, start, end)


def _place_anywhere(
    task: TaskInput,
    offsets: list[int],
    free_by_day: dict[int, list[Interval]],
    deadline: datetime | None,
) -> tuple[ScheduledItem, int] | None:
    for offset in offsets:
        start = _find_start(free_by_day[offset], task.planned_minutes, deadline)
        if start is not None:
            return _place(task, offset, free_by_day, start), offset
    return None


def _place_in_preferred_window(
    task: TaskInput,
    offsets: list[int],
    free_by_day: dict[int, list[Interval]],
    week_start: date,
    window_start: time,
    window_end: time,
    deadline: datetime | None,
) -> tuple[ScheduledItem, int] | None:
    for offset in offsets:
        day = week_start + timedelta(days=offset)
        window = (_at(day, window_start), _at(day, window_end))
        slots: list[Interval] = []
        for slot in free_by_day[offset]:
            clipped = _clip(slot, window)
            if clipped is not None:
                slots.append(clipped)
        start = _find_start(slots, task.planned_minutes, deadline)
        if start is not None:
            return _place(task, offset, free_by_day, start), offset
    return None


def _effective_deadline(task: TaskInput, now: datetime) -> datetime | None:
    """返回本次排程要执行的硬截止时间。

    * 没有 deadline -> None。
    * deadline 已经过去 -> None（逾期任务仍要排进未来空档，不能被过去
      的 deadline 直接判定为“排不下”），由调用方单独记录 Deadline Overdue
      警告。
    * deadline 仍在未来 -> 原 deadline（硬约束）。
    """
    if task.deadline is None or task.deadline <= now:
        return None
    return task.deadline


def _overdue_warning(task: TaskInput, now: datetime) -> str | None:
    if task.deadline is None or task.deadline > now:
        return None
    return (
        f"Deadline Overdue（实际截止时间已过）：任务 {task.title!r} 的截止时间 "
        f"{_format(task.deadline)} 已过；任务不会被丢弃，调度器会尝试未来空档。"
    )


def _locked_warning(item: ScheduledItem, reason: str) -> str:
    return (
        f"锁定时间块 {item.task.title!r}"
        f"（{_format(item.start)} ~ {_format(item.end)}）未被保留：{reason}；"
        "将按普通任务重新排程。"
    )


def _retain_locked_items(
    questionnaire: QuestionnaireData,
    locked_items: list[ScheduledItem],
    free_by_day: dict[int, list[Interval]],
    work_offsets: list[int],
    week_start: datetime,
    week_end: datetime,
    now: datetime,
) -> tuple[list[ScheduledItem], set[str], list[str]]:
    """尽可能保留用户锁定的时间块。

    锁定块按传入顺序处理，先接受者先占用时段，因此重叠的第二个锁会被
    释放。任何不符合当前约束的锁都不会被静默保留，而是写入明确警告后
    退化为普通任务重新排程。
    """
    tasks_by_id = {task.id: task for task in questionnaire.tasks}
    work_day_set = set(work_offsets)
    start_clock, end_clock = questionnaire.work_window
    accepted: list[ScheduledItem] = []
    accepted_ids: set[str] = set()
    warnings: list[str] = []

    for item in locked_items:
        task = tasks_by_id.get(item.task_id)
        if task is None:
            warnings.append(_locked_warning(item, "对应任务已不在当前问卷中"))
            continue
        if task.id in accepted_ids:
            warnings.append(_locked_warning(item, "同一任务已有另一个锁定的时间块"))
            continue
        if item.start.tzinfo is not None or item.end.tzinfo is not None:
            warnings.append(_locked_warning(item, "时间块带时区，当前只支持 naive 本地时间"))
            continue
        if item.end <= week_start or item.start >= week_end:
            warnings.append(_locked_warning(item, "时间块不在本周范围内"))
            continue
        if item.start < now:
            warnings.append(_locked_warning(item, "开始时间已经过去，不能把任务排到过去"))
            continue
        if (
            task.deadline is not None
            and task.deadline > now
            and item.end > task.deadline
        ):
            warnings.append(
                _locked_warning(
                    item, f"会超过实际截止时间 {_format(task.deadline)}"
                )
            )
            continue
        if item.start.date() != item.end.date():
            warnings.append(_locked_warning(item, "时间块跨天，当前不支持"))
            continue

        offset = (item.start.date() - questionnaire.week_start).days
        if offset not in work_day_set:
            warnings.append(_locked_warning(item, "落在非工作星期"))
            continue
        work_window = (
            _at(item.start.date(), start_clock),
            _at(item.start.date(), end_clock),
        )
        if item.start < work_window[0] or item.end > work_window[1]:
            warnings.append(_locked_warning(item, "超出每日工作时间窗"))
            continue

        seconds = int((item.end - item.start).total_seconds())
        if seconds % 60 != 0:
            warnings.append(_locked_warning(item, "起止时间不是整分钟"))
            continue
        if seconds // 60 != task.planned_minutes:
            warnings.append(
                _locked_warning(
                    item,
                    f"时长 {seconds // 60} 分钟与任务当前计划时长 "
                    f"{task.planned_minutes} 分钟不一致",
                )
            )
            continue

        slots = free_by_day[offset]
        if not any(
            slot_start <= item.start and item.end <= slot_end
            for slot_start, slot_end in slots
        ):
            warnings.append(
                _locked_warning(
                    item,
                    "与固定承诺、休息时段、其他锁定块或当前时间冲突",
                )
            )
            continue

        accepted_item = ScheduledItem(
            task,
            item.start,
            item.end,
            completed=item.completed,
            locked=True,
        )
        free_by_day[offset] = _reserve(slots, item.start, item.end)
        accepted.append(accepted_item)
        accepted_ids.add(task.id)

        overdue = _overdue_warning(task, now)
        if overdue is not None:
            warnings.append(overdue)

    return accepted, accepted_ids, warnings


def _unscheduled_reason(
    task: TaskInput,
    work_offsets: list[int],
    week_start: datetime,
    week_end: datetime,
    now: datetime,
) -> str:
    if not work_offsets:
        return "work_days 为空，本周没有可用于排程的工作日。"

    deadline = task.deadline
    if deadline is not None and deadline <= now:
        return (
            f"任务的实际截止时间 {_format(deadline)} 已过，"
            f"且本周可用时间内找不到连续 {task.planned_minutes} 分钟的空档。"
        )
    if deadline is not None and deadline > now:
        if deadline <= week_start:
            return (
                f"本周可排程时间晚于截止时间 {_format(deadline)}，"
                "无法在截止时间前完成。"
            )
        if deadline < week_end:
            return (
                f"截止时间 {_format(deadline)} 前找不到连续 "
                f"{task.planned_minutes} 分钟的空档。"
            )
    return (
        f"本周可用时间内找不到连续 {task.planned_minutes} 分钟的空档"
        "（已考虑固定承诺、休息时段和工作时间窗）。"
    )


def build_schedule(
    questionnaire: QuestionnaireData,
    now: datetime | None = None,
    locked_items: Iterable[ScheduledItem] | None = None,
) -> ScheduleResult:
    """根据问卷生成一周的确定性日程。

    Args:
        questionnaire: 已确认的问卷，是排程约束的唯一来源。
        now: 可选的本地 naive datetime；``None`` 时使用 ``datetime.now()``。
            该时间点之前的可用时间会被排除，任务绝不会排到过去。测试可传入
            固定值以获得确定性结果。
        locked_items: 可选的用户锁定时间块；只有 ``locked=True`` 的项会被
            尝试保留。锁定项必须与当前问卷中的任务 id 对应，并满足本周、
            deadline、工作时间、时长和空档约束，否则释放并写入警告。

    Returns:
        :class:`ScheduleResult`：已排任务、未排任务及警告。

    Raises:
        TypeError: 传入的不是 :class:`QuestionnaireData`，``now`` 不是
            :class:`datetime`，或 ``locked_items`` 不是可迭代的
            :class:`ScheduledItem` 集合。
        ValueError: ``now`` 带时区（当前模型统一使用 naive 本地时间）。

    所有输入任务都会出现在结果里：要么在 ``items``，要么在
    ``unscheduled_tasks`` 并带有原因，不会被静默丢弃。已经超过截止时间的任务
    仍会尝试安排到未来空档，并写入 Deadline Overdue 警告。锁定的任务留在
    ``items`` 中并带 ``locked=True``，不会重复排程。
    """
    if not isinstance(questionnaire, QuestionnaireData):
        raise TypeError(
            "build_schedule() 需要 QuestionnaireData，"
            f"收到 {type(questionnaire).__name__}"
        )
    if now is None:
        now = datetime.now()
    elif not isinstance(now, datetime):
        raise TypeError(f"now 必须是 datetime 或 None，收到 {type(now).__name__}")
    elif now.tzinfo is not None:
        raise ValueError("now 必须是 naive 本地时间（不带 tzinfo）")

    if locked_items is None:
        lock_candidates: list[ScheduledItem] = []
    elif isinstance(locked_items, ScheduledItem):
        raise TypeError(
            "locked_items 必须是可迭代的 ScheduledItem 集合，不能是单个对象"
        )
    else:
        try:
            lock_candidates = list(locked_items)
        except TypeError as exc:
            raise TypeError(
                "locked_items 必须是可迭代的 ScheduledItem 集合"
            ) from exc
        for item in lock_candidates:
            if not isinstance(item, ScheduledItem):
                raise TypeError(
                    "locked_items 只能包含 ScheduledItem，"
                    f"收到 {type(item).__name__}"
                )
    locks = [item for item in lock_candidates if item.locked]

    week_start_dt = datetime.combine(questionnaire.week_start, time(0, 0))
    week_end_dt = week_start_dt + timedelta(days=7)

    work_offsets = _work_offsets(questionnaire)
    routine_offsets = sorted(
        {
            weekday
            for routine in questionnaire.predictable_routines
            for weekday in routine.weekdays
        }
    )
    # work_days 只限制灵活的一次性任务；PredictableRoutine 的 weekdays
    # 是自身 recurrence 的权威。两类星期共用工作时间窗和阻塞区间。
    slot_offsets = sorted(set(work_offsets) | set(routine_offsets))
    fixed = _fixed_occurrences(questionnaire, week_start_dt, week_end_dt)
    rests = _rest_occurrences(questionnaire, week_start_dt, week_end_dt)
    warnings = _overlap_warnings(fixed, rests, week_start_dt, week_end_dt)

    if not work_offsets:
        warnings.append(
            "work_days 为空，本周没有可用于排程灵活一次性任务的工作日"
            "（PredictableRoutine 仍按自身 weekdays 排程）。"
        )

    blockers: list[Interval] = []
    for _, start, end in fixed:
        clipped = _clip((start, end), (week_start_dt, week_end_dt))
        if clipped is not None:
            blockers.append(clipped)
    for _, start, end in rests:
        clipped = _clip((start, end), (week_start_dt, week_end_dt))
        if clipped is not None:
            blockers.append(clipped)

    free_by_day = _free_slots_by_day(questionnaire, slot_offsets, blockers)

    # 当前时间预防：把 now 之前的时间从所有空档中裁掉。now 早于本周时不需要
    # 裁剪；晚于本周结束时所有空档都会变成空列表。
    if now > week_start_dt:
        for offset in list(free_by_day):
            clipped_slots: list[Interval] = []
            for slot in free_by_day[offset]:
                clipped = _clip(slot, (now, week_end_dt))
                if clipped is not None:
                    clipped_slots.append(clipped)
            free_by_day[offset] = clipped_slots

    items: list[ScheduledItem] = []
    unscheduled: list[UnscheduledTask] = []

    locked_items_kept, locked_ids, lock_warnings = _retain_locked_items(
        questionnaire,
        locks,
        free_by_day,
        work_offsets,
        week_start_dt,
        week_end_dt,
        now,
    )
    warnings.extend(lock_warnings)
    items.extend(locked_items_kept)

    def record_failure(task: TaskInput) -> None:
        unscheduled.append(
            UnscheduledTask(
                task,
                _unscheduled_reason(
                    task, work_offsets, week_start_dt, week_end_dt, now
                ),
            )
        )
        if (
            task.deadline is not None
            and task.deadline > now
            and task.deadline < week_end_dt
        ):
            warnings.append(
                f"任务 {task.title!r} 未能在截止时间 "
                f"{_format(task.deadline)} 前完成，已列为未排任务。"
            )

    # 第 4 步：PredictableRoutine 重复活动。每个配置的星期各排一次；
    # 不加缓冲，合成 TaskInput 只用于日历展示。
    for weekday, routine, routine_task in _routine_occurrences(questionnaire):
        placed_routine = _place_routine(
            routine,
            weekday,
            routine_task,
            free_by_day,
            questionnaire.week_start,
        )
        if placed_routine is None:
            unscheduled.append(
                UnscheduledTask(
                    routine_task,
                    _routine_unscheduled_reason(routine, weekday),
                )
            )
        else:
            items.append(placed_routine)

    # 第 5 步：可预测日常。保持问卷输入顺序，先偏爱偏好窗口 / 偏好星期。
    routines = [
        task
        for task in questionnaire.tasks
        if task.duration_type is DurationType.PREDICTABLE
    ]
    for task in routines:
        if task.id in locked_ids:
            continue
        overdue = _overdue_warning(task, now)
        if overdue is not None:
            warnings.append(overdue)
        deadline = _effective_deadline(task, now)

        preferred_offsets = work_offsets
        if task.preferred_days is not None:
            preferred_offsets = [
                offset
                for offset in work_offsets
                if (questionnaire.week_start + timedelta(days=offset)).weekday()
                in task.preferred_days
            ]

        placed: tuple[ScheduledItem, int] | None = None
        if task.preferred_start is not None:
            window_start = parse_hhmm(task.preferred_start)
            window_end = parse_hhmm(task.preferred_end)
            placed = _place_in_preferred_window(
                task,
                preferred_offsets,
                free_by_day,
                questionnaire.week_start,
                window_start,
                window_end,
                deadline,
            )
        elif task.preferred_days is not None:
            placed = _place_anywhere(
                task, preferred_offsets, free_by_day, deadline
            )

        if placed is None:
            placed = _place_anywhere(task, work_offsets, free_by_day, deadline)

        if placed is None:
            record_failure(task)
        else:
            items.append(placed[0])

    # 第 6 步：不确定任务。EDF -> importance_rank -> 输入顺序。
    indexed_uncertain = [
        (index, task)
        for index, task in enumerate(questionnaire.tasks)
        if task.duration_type is DurationType.UNCERTAIN
    ]
    indexed_uncertain.sort(
        key=lambda pair: (
            pair[1].deadline if pair[1].deadline is not None else datetime.max,
            pair[1].effective_importance_rank,
            pair[0],
        )
    )
    for _, task in indexed_uncertain:
        if task.id in locked_ids:
            continue
        overdue = _overdue_warning(task, now)
        if overdue is not None:
            warnings.append(overdue)
        deadline = _effective_deadline(task, now)
        placed = _place_anywhere(task, work_offsets, free_by_day, deadline)
        if placed is None:
            record_failure(task)
        else:
            items.append(placed[0])

    return ScheduleResult(
        week_start=questionnaire.week_start,
        items=items,
        unscheduled_tasks=unscheduled,
        warnings=warnings,
    )

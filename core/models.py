"""LifePilot 核心数据模型（V1.2：AI 咨询字段 + 可预测日常模型）。

四类时间
--------
* 硬承诺（:class:`FixedCommitment`）：精确起止、不可移动，绝不加时间缓冲。
* 休息时段（:class:`RestPeriod`）：受保护的重复区间，支持跨夜（如 23:00–07:00）；
  调度器不得把普通任务排进去，也不加缓冲。
* 可预测日常（``DurationType.PREDICTABLE`` 或 :class:`PredictableRoutine`）：
  按 ``estimated_minutes`` 原样安排，不加缓冲；偏好字段只是软偏好。
* 不确定任务（``DurationType.UNCERTAIN``）：``planned_minutes`` 在估算超过 10 分钟时
  加 20% 缓冲，但绝不修改 ``estimated_minutes``，也不自动拆分任务。

AI 咨询
-------
* :class:`FollowUpQuestion` 的 id 为 ``q`` + 正整数（q1、q2、q3…），不再限制数量。
* :class:`ConsultationDraft` 用 ``resolved_fields`` / ``unknown_fields`` /
  ``unresolved_fields`` 记录字段状态，三者互斥；``is_complete`` 只表示 AI 咨询
  结束，不代表数据已可直接排程。
* ``PredictableRoutine`` 是独立模型：它是需要排进日历的重复活动，不是受保护的
  不可用时间；不要把它和 :class:`RestPeriod` 混用。

重要性排序
----------
* 新字段 :attr:`TaskInput.importance_rank` 使用 1 起的用户自定义序号，数字越小越重要。
* 未提供该字段时，调度器回退到旧版 :class:`Priority`
  （HIGH → 1、MEDIUM → 2、LOW → 3），因此 A/B 现有接口仍可工作。
* 相等 rank 合法，由原始输入顺序决胜。

其它约定
--------
* 所有 ``datetime`` 都是 naive 本地时间，不做时区转换。
* 时间区间使用左闭右开 ``[start, end)``：10:00 结束的任务与 10:00 开始的任务不冲突。
* ``QuestionnaireData`` 是排程约束的唯一来源（任务、固定承诺、休息时段、工作时间窗、
  可用星期）；``UserProfile`` 只用于展示，不参与时间分配。
* 模型只校验“单个对象自身是否合法”；跨对象冲突（重叠、装不下、超过 deadline）
  留给 ``core/validator.py``。
* 星期沿用 Python 约定：``0=周一`` … ``6=周日``。
* ``QuestionnaireData.tasks`` 的列表顺序就是用户输入顺序，调度器用于同优先级时的决胜。
* 字段说明见各 dataclass 的 docstring。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any

__all__ = [
    "ModelError",
    "Priority",
    "DurationType",
    "TaskInput",
    "FixedCommitment",
    "RestPeriod",
    "PredictableRoutine",
    "FollowUpQuestion",
    "ActivityCategory",
    "ActivitySuggestion",
    "ConsultationDraft",
    "UserProfile",
    "QuestionnaireData",
    "ScheduledItem",
    "UnscheduledTask",
    "ScheduleResult",
    "ENERGY_PEAKS",
    "monday_of",
    "parse_hhmm",
]

#: 问卷中 energy_peak 允许的取值。
ENERGY_PEAKS = frozenset({"morning", "afternoon", "evening", "flexible", "unknown"})

_PREFERRED_PERIODS = frozenset({"morning", "afternoon", "evening"})
_HHMM_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_FOLLOW_UP_ID_PATTERN = re.compile(r"q[1-9]\d*$")


class ModelError(ValueError):
    """模型数据不合法时抛出，消息面向用户、可直接展示。"""


# ---------------------------------------------------------------------------
# 校验 / 归一化辅助函数（模块内部使用）
# ---------------------------------------------------------------------------


def _require_text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ModelError(f"{field_name} 必须是字符串，收到 {type(value).__name__}")
    text = value.strip()
    if not text and not allow_empty:
        raise ModelError(f"{field_name} 不能为空")
    return text


def _require_typed_list(value: Any, field_name: str, item_type: type) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise ModelError(f"{field_name} 必须是列表，收到 {type(value).__name__}")
    items = list(value)
    for index, item in enumerate(items):
        if not isinstance(item, item_type):
            raise ModelError(
                f"{field_name}[{index}] 必须是 {item_type.__name__}，"
                f"收到 {type(item).__name__}"
            )
    return items


def _clean_str_list(value: Any, field_name: str) -> list[str]:
    """校验字符串列表，去掉首尾空白与空字符串。"""
    if not isinstance(value, (list, tuple)):
        raise ModelError(f"{field_name} 必须是字符串列表，收到 {type(value).__name__}")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ModelError(
                f"{field_name}[{index}] 必须是字符串，收到 {type(item).__name__}"
            )
        text = item.strip()
        if text:
            result.append(text)
    return result


def _clean_field_names(value: Any, field_name: str) -> list[str]:
    """校验字段名列表：非空字符串，去掉首尾空白；重复由调用方统一检查。"""
    if not isinstance(value, (list, tuple)):
        raise ModelError(f"{field_name} 必须是字符串列表，收到 {type(value).__name__}")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ModelError(
                f"{field_name}[{index}] 必须是字符串，收到 {type(item).__name__}"
            )
        name = item.strip()
        if not name:
            raise ModelError(f"{field_name}[{index}] 不能为空")
        result.append(name)
    return result


def _require_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelError(f"{field_name} 必须是整数，收到 {type(value).__name__}")
    if not minimum <= value <= maximum:
        raise ModelError(f"{field_name} 必须在 {minimum}~{maximum} 之间，收到 {value}")
    return value


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ModelError(f"{field_name} 必须是 bool，收到 {type(value).__name__}")
    return value


def _require_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ModelError(f"{field_name} 必须是 datetime，收到 {type(value).__name__}")
    return value


def _require_date(value: Any, field_name: str) -> date:
    """只接受 date；datetime 是 date 的子类，这里要显式拒绝。"""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ModelError(f"{field_name} 必须是 date，收到 {type(value).__name__}")
    return value


def _clean_weekdays(
    value: Any, field_name: str, *, allow_empty: bool = False
) -> list[int]:
    """工作日列表使用 0~6（0=周一），去重并排序。"""
    if not isinstance(value, (list, tuple)):
        raise ModelError(f"{field_name} 必须是整数列表，收到 {type(value).__name__}")
    days: set[int] = set()
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ModelError(
                f"{field_name}[{index}] 必须是 0~6 的整数（0=周一），收到 {item!r}"
            )
        if not 0 <= item <= 6:
            raise ModelError(
                f"{field_name} 取值必须在 0~6 之间（0=周一，6=周日），收到 {item}"
            )
        days.add(item)
    if not days and not allow_empty:
        raise ModelError(f"{field_name} 不能为空")
    return sorted(days)


def _clean_energy_peak(value: Any) -> str:
    if not isinstance(value, str):
        raise ModelError(f"energy_peak 必须是字符串，收到 {type(value).__name__}")
    normalized = value.strip().lower()
    if normalized not in ENERGY_PEAKS:
        allowed = ", ".join(sorted(ENERGY_PEAKS))
        raise ModelError(f"energy_peak 必须是 [{allowed}] 之一，收到 {value!r}")
    return normalized


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def monday_of(day: date) -> date:
    """返回 ``day`` 所在自然周的周一。"""
    day = _require_date(day, "monday_of(day)")
    return day - timedelta(days=day.weekday())


def parse_hhmm(value: str) -> time:
    """把 ``"HH:MM"`` 解析成 ``datetime.time``；格式错误时抛 :class:`ModelError`。"""
    if not isinstance(value, str):
        raise ModelError(f'time 必须是 "HH:MM" 字符串，收到 {type(value).__name__}')
    text = value.strip()
    if not _HHMM_PATTERN.fullmatch(text):
        raise ModelError(f'time 必须符合 "HH:MM" 格式（00:00~23:59），收到 {value!r}')
    return time.fromisoformat(text)


class Priority(str, Enum):
    """旧版任务优先级，保留用于 A/B 接口兼容。

    新代码可以改用 :attr:`TaskInput.importance_rank`；未提供 rank 时调度器
    回退到这里的 :attr:`rank`（数字越小越优先）。
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"high": 0, "medium": 1, "low": 2}[self.value]


# ---------------------------------------------------------------------------
# 输入类模型
# ---------------------------------------------------------------------------


class DurationType(str, Enum):
    """任务时长类型，决定调度器是否添加 20% 缓冲。"""

    PREDICTABLE = "predictable"
    UNCERTAIN = "uncertain"


@dataclass
class TaskInput:
    """用户想要完成的一件事。

    Attributes:
        title: 任务标题，不能为空。
        estimated_minutes: 用户估算时长（分钟），1~480；模型只读，绝不改写。
        id: 稳定标识；为空时由 :class:`QuestionnaireData` 自动分配 ``t1..tn``。
        priority: 优先级，默认 ``MEDIUM``。
        deadline: 截止时间；``None`` 表示本周内完成即可。
        category: 分类（如 ``study`` / ``work`` / ``health``），只用于 UI 展示。
        preferred_period: 偏好时段：``""`` / ``morning`` / ``afternoon`` / ``evening``。
        notes: 备注。
        duration_type: ``PREDICTABLE`` 原样安排；``UNCERTAIN`` 在估算超过
            10 分钟时由 :attr:`planned_minutes` 加 20% 缓冲。
        preferred_start / preferred_end: 可选的 ``"HH:MM"`` 软偏好窗口，必须成对
            出现且 start < end（V1 不支持跨夜偏好窗口）。
        preferred_days: 可选的星期软偏好（0~6）；``None`` 表示不限。
        importance_rank: 用户自定义重要性序号，1~999，数字越小越重要；
            ``None`` 表示回退到 :attr:`priority`。相等 rank 合法。
    """

    title: str
    estimated_minutes: int
    id: str = ""
    priority: Priority = Priority.MEDIUM
    deadline: datetime | None = None
    category: str = ""
    preferred_period: str = ""
    notes: str = ""
    duration_type: DurationType = DurationType.UNCERTAIN
    preferred_start: str | None = None
    preferred_end: str | None = None
    preferred_days: list[int] | None = None
    importance_rank: int | None = None

    def __post_init__(self) -> None:
        self.title = _require_text(self.title, "TaskInput.title")
        self.estimated_minutes = _require_int(
            self.estimated_minutes, "estimated_minutes", 1, 480
        )

        if not isinstance(self.id, str):
            raise ModelError(f"TaskInput.id 必须是字符串，收到 {type(self.id).__name__}")
        self.id = self.id.strip()

        if not isinstance(self.priority, Priority):
            raise ModelError(
                "TaskInput.priority 必须是 Priority 枚举"
                f"（high/medium/low），收到 {self.priority!r}"
            )

        if not isinstance(self.duration_type, DurationType):
            raise ModelError(
                "TaskInput.duration_type 必须是 DurationType 枚举"
                f"（predictable/uncertain），收到 {self.duration_type!r}"
            )

        if self.deadline is not None:
            self.deadline = _require_datetime(self.deadline, "TaskInput.deadline")

        self.category = _require_text(
            self.category, "TaskInput.category", allow_empty=True
        )
        self.notes = _require_text(self.notes, "TaskInput.notes", allow_empty=True)

        if not isinstance(self.preferred_period, str):
            raise ModelError(
                f"TaskInput.preferred_period 必须是字符串，"
                f"收到 {type(self.preferred_period).__name__}"
            )
        period = self.preferred_period.strip().lower()
        if period and period not in _PREFERRED_PERIODS:
            allowed = ", ".join(sorted(_PREFERRED_PERIODS))
            raise ModelError(
                f"TaskInput.preferred_period 必须是空字符串或 [{allowed}] 之一，"
                f"收到 {self.preferred_period!r}"
            )
        self.preferred_period = period

        if (self.preferred_start is None) != (self.preferred_end is None):
            raise ModelError(
                "TaskInput.preferred_start 和 preferred_end 必须同时提供或同时为 None"
            )
        if self.preferred_start is not None:
            preferred_start = parse_hhmm(self.preferred_start)
            preferred_end = parse_hhmm(self.preferred_end)
            if preferred_start >= preferred_end:
                raise ModelError(
                    "TaskInput.preferred_start 必须早于 preferred_end"
                    "（V1 的偏好窗口不支持跨夜）"
                )
            self.preferred_start = preferred_start.strftime("%H:%M")
            self.preferred_end = preferred_end.strftime("%H:%M")

        if self.preferred_days is not None:
            preferred_days = _clean_weekdays(
                self.preferred_days, "TaskInput.preferred_days", allow_empty=True
            )
            self.preferred_days = preferred_days or None

        if self.importance_rank is not None:
            self.importance_rank = _require_int(
                self.importance_rank, "TaskInput.importance_rank", 1, 999
            )

    @property
    def effective_importance_rank(self) -> int:
        """调度器实际使用的重要性序号（1 起，越小越重要）。

        显式 ``importance_rank`` 优先；否则把旧版 :class:`Priority` 映射为
        HIGH=1 / MEDIUM=2 / LOW=3，保证 A/B 旧接口继续工作。
        """
        if self.importance_rank is not None:
            return self.importance_rank
        return self.priority.rank + 1

    @property
    def planned_minutes(self) -> int:
        """调度器实际需要分配的分钟数；``estimated_minutes`` 保持不变。"""
        if self.duration_type is DurationType.PREDICTABLE:
            return self.estimated_minutes
        if self.estimated_minutes <= 10:
            return self.estimated_minutes
        # ceil(estimated_minutes * 1.2) 的整数算法，避免浮点误差。
        return (self.estimated_minutes * 12 + 9) // 10

    @property
    def has_preferred_window(self) -> bool:
        """是否设置了任意软偏好（时间窗或星期）。"""
        return self.preferred_start is not None or self.preferred_days is not None


@dataclass(frozen=True)
class FixedCommitment:
    """不可移动的固定承诺（上课、开会、健身课等）。

    使用 ``frozen=True`` 是刻意的：AI 和 UI 都不能修改已存在的承诺对象，
    从类型层面保证“固定承诺必须保留”。
    """

    title: str
    start: datetime
    end: datetime
    location: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "title", _require_text(self.title, "FixedCommitment.title")
        )
        object.__setattr__(
            self,
            "location",
            _require_text(self.location, "FixedCommitment.location", allow_empty=True),
        )
        start = _require_datetime(self.start, "FixedCommitment.start")
        end = _require_datetime(self.end, "FixedCommitment.end")
        if end <= start:
            raise ModelError(
                f"FixedCommitment 的结束时间必须晚于开始时间（{start} → {end}）"
            )

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class RestPeriod:
    """受保护的重复休息区间（睡眠、固定休息等）。

    ``days`` 使用 0~6（0=周一），会去重并排序。``start_time`` / ``end_time`` 为
    ``"HH:MM"``；当 ``end_time`` 早于 ``start_time`` 时表示跨夜区间
    （例如 23:00–07:00），:attr:`duration_minutes` 已按跨夜计算。

    调度器必须先把这些区间从可用时间中扣除，且不得给它们加时间缓冲。
    """

    title: str
    days: list[int]
    start_time: str
    end_time: str

    def __post_init__(self) -> None:
        self.title = _require_text(self.title, "RestPeriod.title")
        self.days = _clean_weekdays(self.days, "RestPeriod.days")
        start = parse_hhmm(self.start_time)
        end = parse_hhmm(self.end_time)
        if start == end:
            raise ModelError(
                "RestPeriod 的 start_time 与 end_time 不能相同"
                "（无法区分 0 分钟和 24 小时）"
            )
        self.start_time = start.strftime("%H:%M")
        self.end_time = end.strftime("%H:%M")

    @property
    def is_overnight(self) -> bool:
        return parse_hhmm(self.end_time) < parse_hhmm(self.start_time)

    @property
    def duration_minutes(self) -> int:
        start = parse_hhmm(self.start_time)
        end = parse_hhmm(self.end_time)
        start_minutes = start.hour * 60 + start.minute
        end_minutes = end.hour * 60 + end.minute
        if end_minutes > start_minutes:
            return end_minutes - start_minutes
        return (24 * 60 - start_minutes) + end_minutes


@dataclass
class PredictableRoutine:
    """可预测的重复活动（如晨跑、背单词、固定练习）。

    与 :class:`RestPeriod` 不同，这是需要被调度成实际时间块的活动，而不是
    受保护的不可用时间；因此它不占用“禁止排程”区间，也不加 20% 缓冲。

    ``weekdays`` 使用 0~6（0=周一），会去重并排序且不能为空。
    ``estimated_minutes`` 为 1~480 的整数。``preferred_start`` 单独提供时表示
    偏好开始时间；``preferred_start`` 与 ``preferred_end`` 同时提供时表示偏好
    时间窗。只提供 ``preferred_end`` 不合法；V1 不支持跨夜偏好窗口。
    """

    title: str
    weekdays: list[int]
    estimated_minutes: int
    preferred_start: str | None = None
    preferred_end: str | None = None

    def __post_init__(self) -> None:
        self.title = _require_text(self.title, "PredictableRoutine.title")
        self.weekdays = _clean_weekdays(
            self.weekdays, "PredictableRoutine.weekdays"
        )
        self.estimated_minutes = _require_int(
            self.estimated_minutes,
            "PredictableRoutine.estimated_minutes",
            1,
            480,
        )
        if self.preferred_start is None and self.preferred_end is None:
            return
        if self.preferred_start is None:
            raise ModelError(
                "PredictableRoutine.preferred_end 不能单独提供；"
                "请同时提供 preferred_start"
            )
        start = parse_hhmm(self.preferred_start)
        self.preferred_start = start.strftime("%H:%M")
        if self.preferred_end is not None:
            end = parse_hhmm(self.preferred_end)
            if end <= start:
                raise ModelError(
                    "PredictableRoutine.preferred_end 必须晚于 preferred_start"
                    "（V1 不支持跨夜偏好窗口）"
                )
            self.preferred_end = end.strftime("%H:%M")


# ---------------------------------------------------------------------------
# AI 咨询相关模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FollowUpQuestion:
    """AI 生成的追问。

    ``id`` 为 ``q`` + 正整数（q1、q2、q3…），不再限制追问数量。``target_field``
    表示这条追问希望补充的问卷字段名；为空表示旧版调用未提供该字段（保持 A/B
    接口兼容）。``priority`` 为 0~4 的整数，由咨询控制器解释其排序含义；
    旧版两参数调用默认使用中性的 2。
    """

    id: str
    question: str
    target_field: str = ""
    priority: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.id, str):
            raise ModelError(
                f"FollowUpQuestion.id 必须是字符串，收到 {type(self.id).__name__}"
            )
        question_id = self.id.strip()
        if not _FOLLOW_UP_ID_PATTERN.fullmatch(question_id):
            raise ModelError(
                '追问 id 必须形如 "q1"、"q2"、"q3"…（q + 正整数），'
                f"收到 {self.id!r}"
            )
        object.__setattr__(self, "id", question_id)
        object.__setattr__(
            self, "question", _require_text(self.question, "FollowUpQuestion.question")
        )
        object.__setattr__(
            self,
            "target_field",
            _require_text(
                self.target_field,
                "FollowUpQuestion.target_field",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "priority",
            _require_int(self.priority, "FollowUpQuestion.priority", 0, 4),
        )


class ActivityCategory(str, Enum):
    """AI 对用户活动的初步分类；写入 QuestionnaireData 前必须经用户确认。"""

    HARD_COMMITMENT = "hard_commitment"
    REST_PERIOD = "rest_period"
    PREDICTABLE_ROUTINE = "predictable_routine"
    UNCERTAIN_TASK = "uncertain_task"


@dataclass(frozen=True)
class ActivitySuggestion:
    """AI 的轻量分类建议（只读展示，用户确认后才会影响问卷）。

    ``source_task_id`` 指向问卷中已有任务的 id；无法对应到具体任务时为 ``None``。
    """

    activity_name: str
    suggested_category: ActivityCategory
    reason: str
    source_task_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "activity_name",
            _require_text(self.activity_name, "ActivitySuggestion.activity_name"),
        )
        if not isinstance(self.suggested_category, ActivityCategory):
            raise ModelError(
                "ActivitySuggestion.suggested_category 必须是 ActivityCategory 枚举"
                "（hard_commitment/rest_period/predictable_routine/uncertain_task），"
                f"收到 {self.suggested_category!r}"
            )
        object.__setattr__(
            self,
            "reason",
            _require_text(self.reason, "ActivitySuggestion.reason"),
        )
        if self.source_task_id is not None:
            object.__setattr__(
                self,
                "source_task_id",
                _require_text(self.source_task_id, "ActivitySuggestion.source_task_id"),
            )


@dataclass
class ConsultationDraft:
    """``start_consultation`` 的返回值：追问、字段状态与可选的分类建议。

    ``follow_up_questions`` 不限制数量；``id`` 必须唯一且形如 q1、q2、q3…
    ``resolved_fields`` / ``unknown_fields`` / ``unresolved_fields`` 由 Python
    咨询控制器填写，不能在三个列表之间重复，也不能在同一个列表内重复。

    ``is_complete`` 只表示“AI 咨询已经结束”，不代表数据已经可以直接排程：
    即使 ``is_complete=True``，未知的必填字段仍需前端手动补全。
    ``activity_suggestions`` 只是 AI 的猜测，必须由用户逐条确认后才能写入
    :class:`QuestionnaireData`；这里不会自动应用任何分类。
    最终的分析摘要放在 :attr:`UserProfile.summary`，本模型不单独保存。
    """

    follow_up_questions: list[FollowUpQuestion] = field(default_factory=list)
    activity_suggestions: list[ActivitySuggestion] = field(default_factory=list)
    resolved_fields: list[str] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        questions = _require_typed_list(
            self.follow_up_questions,
            "ConsultationDraft.follow_up_questions",
            FollowUpQuestion,
        )
        ids = [question.id for question in questions]
        if len(set(ids)) != len(ids):
            raise ModelError("追问 id 必须唯一")
        self.follow_up_questions = questions
        self.activity_suggestions = _require_typed_list(
            self.activity_suggestions,
            "ConsultationDraft.activity_suggestions",
            ActivitySuggestion,
        )

        field_states = (
            ("resolved_fields", _clean_field_names(
                self.resolved_fields, "ConsultationDraft.resolved_fields"
            )),
            ("unknown_fields", _clean_field_names(
                self.unknown_fields, "ConsultationDraft.unknown_fields"
            )),
            ("unresolved_fields", _clean_field_names(
                self.unresolved_fields, "ConsultationDraft.unresolved_fields"
            )),
        )
        seen: dict[str, str] = {}
        for field_name, names in field_states:
            for name in names:
                if name in seen:
                    raise ModelError(
                        f"字段 {name!r} 不能同时出现在 {seen[name]} 和 {field_name} 中"
                    )
                seen[name] = field_name
        (
            self.resolved_fields,
            self.unknown_fields,
            self.unresolved_fields,
        ) = (names for _, names in field_states)

    @property
    def is_complete(self) -> bool:
        """AI 咨询是否结束；这是派生属性，不单独存储。"""
        return len(self.unresolved_fields) == 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ConsultationDraft:
        """解析 AI 返回的 JSON；id 非法、字段状态非法时抛 :class:`ModelError`。

        追问数量不设上限，也不做截断：调用方应捕获异常并决定是否降级。
        """
        if not isinstance(data, Mapping):
            raise ModelError(
                f"ConsultationDraft.from_dict 需要字典，收到 {type(data).__name__}"
            )

        raw = data.get("follow_up_questions", [])
        if raw is None:
            raw = []
        if not isinstance(raw, (list, tuple)):
            raise ModelError(
                f"follow_up_questions 必须是列表，收到 {type(raw).__name__}"
            )

        questions: list[FollowUpQuestion] = []
        for index, item in enumerate(raw, start=1):
            if isinstance(item, str):
                questions.append(FollowUpQuestion(id=f"q{index}", question=item))
                continue
            if not isinstance(item, Mapping):
                raise ModelError(
                    f"follow_up_questions[{index - 1}] 必须是字符串或对象，"
                    f"收到 {type(item).__name__}"
                )
            question_id = item.get("id") or f"q{index}"
            target_field = item.get("target_field")
            if target_field is None:
                target_field = ""
            raw_priority = item.get("priority")
            if raw_priority is None:
                raw_priority = 2
            questions.append(
                FollowUpQuestion(
                    id=question_id,
                    question=item.get("question", ""),
                    target_field=target_field,
                    priority=raw_priority,
                )
            )

        raw_suggestions = data.get("activity_suggestions", [])
        if raw_suggestions is None:
            raw_suggestions = []
        if not isinstance(raw_suggestions, (list, tuple)):
            raise ModelError(
                f"activity_suggestions 必须是列表，收到 {type(raw_suggestions).__name__}"
            )
        suggestions: list[ActivitySuggestion] = []
        for index, item in enumerate(raw_suggestions):
            if not isinstance(item, Mapping):
                raise ModelError(
                    f"activity_suggestions[{index}] 必须是对象，"
                    f"收到 {type(item).__name__}"
                )
            raw_category = item.get("suggested_category")
            try:
                category = ActivityCategory(raw_category)
            except (TypeError, ValueError):
                allowed = ", ".join(
                    category.value for category in ActivityCategory
                )
                raise ModelError(
                    f"activity_suggestions[{index}].suggested_category "
                    f"必须是 [{allowed}] 之一，收到 {raw_category!r}"
                ) from None
            suggestions.append(
                ActivitySuggestion(
                    activity_name=item.get("activity_name", ""),
                    suggested_category=category,
                    reason=item.get("reason", ""),
                    source_task_id=item.get("source_task_id") or None,
                )
            )

        resolved_fields = data.get("resolved_fields", [])
        unknown_fields = data.get("unknown_fields", [])
        unresolved_fields = data.get("unresolved_fields", [])
        if resolved_fields is None:
            resolved_fields = []
        if unknown_fields is None:
            unknown_fields = []
        if unresolved_fields is None:
            unresolved_fields = []

        return cls(
            follow_up_questions=questions,
            activity_suggestions=suggestions,
            resolved_fields=resolved_fields,
            unknown_fields=unknown_fields,
            unresolved_fields=unresolved_fields,
        )


# ---------------------------------------------------------------------------
# 用户画像（AI 输出）
# ---------------------------------------------------------------------------


@dataclass
class UserProfile:
    """AI 归纳出的用户画像。

    只用于展示与建议，不参与排程时间分配；排程约束以
    :class:`QuestionnaireData` 为准。
    """

    summary: str = ""
    goals: list[str] = field(default_factory=list)
    work_style: str = ""
    preferences: list[str] = field(default_factory=list)
    recommended_work_block_minutes: int = 50
    break_preferences: str = ""
    scheduling_notes: str = ""
    is_fallback: bool = False

    def __post_init__(self) -> None:
        self.summary = _require_text(
            self.summary, "UserProfile.summary", allow_empty=True
        )
        self.goals = _clean_str_list(self.goals, "UserProfile.goals")
        self.work_style = _require_text(
            self.work_style, "UserProfile.work_style", allow_empty=True
        )
        self.preferences = _clean_str_list(
            self.preferences, "UserProfile.preferences"
        )
        self.recommended_work_block_minutes = _require_int(
            self.recommended_work_block_minutes,
            "recommended_work_block_minutes",
            15,
            180,
        )
        self.break_preferences = _require_text(
            self.break_preferences, "UserProfile.break_preferences", allow_empty=True
        )
        self.scheduling_notes = _require_text(
            self.scheduling_notes, "UserProfile.scheduling_notes", allow_empty=True
        )
        self.is_fallback = _require_bool(self.is_fallback, "UserProfile.is_fallback")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UserProfile:
        """把 AI 返回的 JSON 转成 :class:`UserProfile`。

        类型仍严格校验（错误类型直接抛 :class:`ModelError`），但允许：
        缺失字段使用默认值、``goals`` / ``preferences`` 接受单个字符串。
        调用方捕获 :class:`ModelError` 后可改用 ``build_fallback_profile``。
        """
        if not isinstance(data, Mapping):
            raise ModelError(
                f"UserProfile.from_dict 需要字典，收到 {type(data).__name__}"
            )

        return cls(
            summary=_coerce_text(data.get("summary"), "summary"),
            goals=_coerce_str_list(data.get("goals"), "goals"),
            work_style=_coerce_text(data.get("work_style"), "work_style"),
            preferences=_coerce_str_list(
                data.get("preferences"), "preferences"
            ),
            recommended_work_block_minutes=_coerce_block_minutes(
                data.get("recommended_work_block_minutes")
            ),
            break_preferences=_coerce_text(
                data.get("break_preferences"), "break_preferences"
            ),
            scheduling_notes=_coerce_text(
                data.get("scheduling_notes"), "scheduling_notes"
            ),
            is_fallback=data.get("is_fallback") is True,
        )


def _coerce_text(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ModelError(f"{field_name} 必须是字符串，收到 {type(value).__name__}")
    return value.strip()


def _coerce_str_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return _clean_str_list(value, field_name)


def _coerce_block_minutes(value: Any) -> int:
    if value is None:
        return 50
    if isinstance(value, bool):
        raise ModelError("recommended_work_block_minutes 必须是整数，收到 bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ModelError(
        "recommended_work_block_minutes 必须是整数，"
        f"收到 {type(value).__name__}"
    )


# ---------------------------------------------------------------------------
# 问卷（排程约束的唯一来源）
# ---------------------------------------------------------------------------


@dataclass
class QuestionnaireData:
    """用户问卷，是整条流程的事实来源（source of truth）。

    字段与 Member C 的问卷 UI 对齐：
    ``name / goals / tasks / fixed_commitments / rest_periods /
    predictable_routines / preferred_work_start / preferred_work_end / work_days /
    habits / challenges / energy_peak / notes``。

    ``week_start`` 是排程周的周一（构造时自动归一化），
    供调度器与 :class:`ScheduleResult` 使用。``rest_periods`` 是受保护的重复
    休息区间，调度器必须先扣除它们；``predictable_routines`` 是需要排进日历的
    重复活动，不是受保护区间，调度时应按原时长安排、不加缓冲。

    ``tasks`` 的列表顺序就是用户输入顺序，调度器用于同优先级时的决胜。
    """

    name: str = ""
    goals: list[str] = field(default_factory=list)
    tasks: list[TaskInput] = field(default_factory=list)
    fixed_commitments: list[FixedCommitment] = field(default_factory=list)
    preferred_work_start: str = "09:00"
    preferred_work_end: str = "22:00"
    work_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    habits: list[str] = field(default_factory=list)
    challenges: list[str] = field(default_factory=list)
    energy_peak: str = "unknown"
    notes: str = ""
    week_start: date = field(default_factory=lambda: monday_of(date.today()))
    rest_periods: list[RestPeriod] = field(default_factory=list)
    predictable_routines: list[PredictableRoutine] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.name = _require_text(self.name, "QuestionnaireData.name", allow_empty=True)
        self.goals = _clean_str_list(self.goals, "QuestionnaireData.goals")
        self.tasks = _require_typed_list(self.tasks, "QuestionnaireData.tasks", TaskInput)
        self.fixed_commitments = _require_typed_list(
            self.fixed_commitments,
            "QuestionnaireData.fixed_commitments",
            FixedCommitment,
        )
        self.rest_periods = _require_typed_list(
            self.rest_periods,
            "QuestionnaireData.rest_periods",
            RestPeriod,
        )
        self.predictable_routines = _require_typed_list(
            self.predictable_routines,
            "QuestionnaireData.predictable_routines",
            PredictableRoutine,
        )

        start_text = self.preferred_work_start.strip() if isinstance(
            self.preferred_work_start, str
        ) else self.preferred_work_start
        end_text = self.preferred_work_end.strip() if isinstance(
            self.preferred_work_end, str
        ) else self.preferred_work_end
        start_time = parse_hhmm(start_text)
        end_time = parse_hhmm(end_text)
        if start_time >= end_time:
            raise ModelError(
                "preferred_work_start 必须早于 preferred_work_end"
                "（V1 不支持跨夜工作时间窗）"
            )
        self.preferred_work_start = start_text
        self.preferred_work_end = end_text

        self.work_days = _clean_weekdays(
            self.work_days, "QuestionnaireData.work_days", allow_empty=True
        )
        self.habits = _clean_str_list(self.habits, "QuestionnaireData.habits")
        self.challenges = _clean_str_list(
            self.challenges, "QuestionnaireData.challenges"
        )
        self.energy_peak = _clean_energy_peak(self.energy_peak)
        self.notes = _require_text(
            self.notes, "QuestionnaireData.notes", allow_empty=True
        )

        self.week_start = monday_of(self.week_start)
        self._assign_task_ids()

    @property
    def work_window(self) -> tuple[time, time]:
        """把 ``"HH:MM"`` 转成调度器可直接使用的 ``(start, end)``。"""
        return (parse_hhmm(self.preferred_work_start), parse_hhmm(self.preferred_work_end))

    def _assign_task_ids(self) -> None:
        """为没有 id 的任务分配 ``t1..tn``；显式 id 重复时报错。"""
        used: set[str] = set()
        for task in self.tasks:
            if not task.id:
                continue
            if task.id in used:
                raise ModelError(f"task id 重复：{task.id!r}")
            used.add(task.id)

        counter = 1
        for task in self.tasks:
            if task.id:
                continue
            while f"t{counter}" in used:
                counter += 1
            task.id = f"t{counter}"
            used.add(task.id)
            counter += 1


# ---------------------------------------------------------------------------
# 排程结果
# ---------------------------------------------------------------------------


@dataclass
class ScheduledItem:
    """一个已经排进日历的任务块。

    直接持有 :class:`TaskInput` 对象作为唯一事实来源，不复制标题等字段，
    因此 UI 修改任务后日程展示会同步更新。

    ``locked`` 表示用户锁定了这个时间块：重新排程时应尽量保留原时间并
    占用该时段。锁定块不是 :class:`FixedCommitment`——它不能违反实际
    deadline、工作时间或与其他锁定块冲突；冲突时由调度器释放并在
    ``ScheduleResult.warnings`` 中说明。
    """

    task: TaskInput
    start: datetime
    end: datetime
    completed: bool = False
    locked: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.task, TaskInput):
            raise ModelError(
                f"ScheduledItem.task 必须是 TaskInput，收到 {type(self.task).__name__}"
            )
        start = _require_datetime(self.start, "ScheduledItem.start")
        end = _require_datetime(self.end, "ScheduledItem.end")
        if end <= start:
            raise ModelError(f"ScheduledItem 的结束时间必须晚于开始时间（{start} → {end}）")
        self.completed = _require_bool(self.completed, "ScheduledItem.completed")
        self.locked = _require_bool(self.locked, "ScheduledItem.locked")

    @property
    def task_id(self) -> str:
        return self.task.id

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def preferred_window_satisfied(self) -> bool | None:
        """任务是否落在软偏好窗口内；未设置任何偏好时返回 ``None``。

        偏好只是“尽量满足”，``False`` 表示这次排程没满足，UI 应提示用户，
        但不构成排程错误。
        """
        if not self.task.has_preferred_window:
            return None
        if self.task.preferred_days is not None:
            if self.start.weekday() not in self.task.preferred_days:
                return False
        if self.task.preferred_start is not None:
            window_start = parse_hhmm(self.task.preferred_start)
            window_end = parse_hhmm(self.task.preferred_end)
            if self.start.time() < window_start or self.end.time() > window_end:
                return False
        return True


@dataclass(frozen=True)
class UnscheduledTask:
    """没能排进本周的任务，以及原因（用于向用户解释）。"""

    task: TaskInput
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.task, TaskInput):
            raise ModelError(
                f"UnscheduledTask.task 必须是 TaskInput，"
                f"收到 {type(self.task).__name__}"
            )
        object.__setattr__(
            self, "reason", _require_text(self.reason, "UnscheduledTask.reason")
        )


@dataclass
class ScheduleResult:
    """调度器输出：本周安排 + 未排任务 + 警告。"""

    week_start: date
    items: list[ScheduledItem] = field(default_factory=list)
    unscheduled_tasks: list[UnscheduledTask] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.week_start = monday_of(self.week_start)
        self.items = _require_typed_list(
            self.items, "ScheduleResult.items", ScheduledItem
        )
        self.items.sort(key=lambda item: (item.start, item.end, item.task.id))
        self.unscheduled_tasks = _require_typed_list(
            self.unscheduled_tasks,
            "ScheduleResult.unscheduled_tasks",
            UnscheduledTask,
        )
        self.warnings = _clean_str_list(self.warnings, "ScheduleResult.warnings")

    def items_on(self, day: date) -> list[ScheduledItem]:
        """返回某一天的所有任务块（按时间排序）。"""
        day = _require_date(day, "ScheduleResult.items_on(day)")
        return [item for item in self.items if item.start.date() == day]

    @property
    def total_scheduled_minutes(self) -> int:
        return sum(item.duration_minutes for item in self.items)

    @property
    def is_empty(self) -> bool:
        return not self.items

"""B chat-frontend contract adapter (Phase 3A).

Pure functions only — no Streamlit, no HTTP, no JS.  Purpose:

* ``adapt_chat``        handle_chat_message result  ->  B's chat card shape
                         ``{reply, state, fields, ready, provider}``
* ``confirmed_fields_to_questionnaire``
                         B's confirmation card       ->  QuestionnaireData
* ``adapt_schedule``    build_confirmed_schedule result -> ``entries``
* ``plan_from_confirmed`` one-call path: card -> real schedule -> entries

Frontend contract (fixed by the Technical Lead):

* fields  = {goal, tasks, commitments, wake, bed, rest, workStart, workEnd,
             routine}
* entries items = {title, date, startTime, endTime, category, priority,
                   repeatWeekly}
* category in {"Study","Work","Exercise","Personal","Rest","Other"}
* priority  in {"High","Medium","Low"} — "Medium" is the SYSTEM default for
  entries without an explicit priority; it is never presented as something
  the AI identified.
* repeatWeekly is a real boolean; it is only set when a genuine weekly
  recurrence was confirmed (declared repeat words or a predictable routine).

Design decisions recorded here:

* The user-edited ``confirmed_fields`` is the authoritative input for the
  final schedule.  ``plan_from_confirmed`` builds the QuestionnaireData
  directly from the card and never consults chat facts.
* Task-specific date/time preferences are honoured by forcing the task to
  DurationType.PREDICTABLE (no buffer) when a specific day or time window is
  given, because the scheduler only applies preferred_days/preferred_start
  to PREDICTABLE tasks.  A warning is emitted when that happens.
* Loose period preferences (morning/afternoon/evening) are kept on the task
  but the scheduler does not use them yet; a warning says so explicitly.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from core.ai_consultant import (
    _normalise_hhmm,
    _parse_predictable_routine,
    _parse_rest_period,
)
from core.models import (
    DurationType,
    FixedCommitment,
    PredictableRoutine,
    Priority,
    QuestionnaireData,
    RestPeriod,
    TaskInput,
)
from ui.integration import plan_week

CATEGORIES = ("Study", "Work", "Exercise", "Personal", "Rest", "Other")

_PRIORITY_WORDS = {
    "high": "High",
    "高": "High",
    "medium": "Medium",
    "中": "Medium",
    "low": "Low",
    "低": "Low",
}

_CATEGORY_KEYWORDS = {
    "Study": ("学习", "作业", "上课", "复习", "课程", "读书", "study"),
    "Work": ("工作", "上班", "开会", "项目", "报告", "work"),
    "Exercise": ("锻炼", "运动", "健身", "跑步", "游泳", "exercise", "gym"),
    "Personal": ("个人", "生活", "家务", "购物", "personal"),
    "Rest": ("休息", "睡觉", "睡眠", "放松", "rest", "sleep"),
}

_HHMM_RE = re.compile(r"^(?:\d{1,2}):(\d{2})$")
_TIME_RANGE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2})\s*(?:-|–|—|~|～|至|到)\s*(?P<end>\d{1,2}:\d{2})"
)
_MINUTES_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>小时|h|hrs?|分钟|min(?:utes?)?)",
    re.IGNORECASE,
)
_DEADLINE_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DEADLINE_MD_RE = re.compile(r"(\d{1,2})月(\d{1,2})[日号]")
_DEADLINE_WEEKDAY_RE = re.compile(r"(?:周|星期)([一二三四五六日天])")
_WEEKDAY_MENTION_RE = re.compile(r"(?:周|星期)([一二三四五六日天])")
_EN_WEEKDAY_RE = re.compile(
    r"\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?"
    r"|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)
_LOOSE_PERIOD_RE = re.compile(r"(早上|早晨|上午|下午|晚上|傍晚)")
_REPEAT_RE = re.compile(r"(每周|every\s*week|weekly|每天|every\s*day|daily)", re.IGNORECASE)
_CATEGORY_LABEL_RE = re.compile(r"类别\s*[:：]?\s*([A-Za-z\u4e00-\u9fa5]+)")
_PRIORITY_LABEL_RE = re.compile(r"优先级\s*[:：]?\s*(high|medium|low|高|中|低)", re.IGNORECASE)
_DEADLINE_WORD_RE = re.compile(r"(截止|deadline|due|之前|前完成)", re.IGNORECASE)

_DAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_EN_DAY_INDEX = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}
_CN_DAY_INDEX = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

SLEEP_TITLE_WORDS = ("sleep", "睡")

REQUIRED_FIELDS = (
    "fixed_commitments",
    "rest_periods",
    "predictable_routines",
    "tasks",
    "preferred_work_start",
    "preferred_work_end",
    "work_days",
    "energy_peak",
    "goals",
)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{what} 必须是字典，收到 {type(value).__name__}")
    return value


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _next_monday(today: date | None = None) -> date:
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def _parse_iso_date(value: Any, what: str) -> date:
    text = _text(value)
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        raise ValueError(f"{what} 必须是 YYYY-MM-DD 日期，收到 {text!r}")
    return date(int(match[1]), int(match[2]), int(match[3]))


def _hhmm(value: Any, what: str) -> str | None:
    """Validate/normalise an HH:MM string; ``None``/"" passes through."""
    text = _text(value)
    if not text:
        return None
    normalised = _normalise_hhmm(text)
    if normalised is None:
        raise ValueError(f"{what} 必须是 HH:MM 时间，收到 {text!r}")
    return normalised


def _days_text(days: list[int]) -> str:
    if sorted(set(days)) == list(range(7)):
        return "每天"
    return "、".join(_DAY_NAMES[d] for d in sorted(set(days)))


def _is_sleep_title(title: str) -> bool:
    lowered = title.lower()
    return any(word in lowered for word in SLEEP_TITLE_WORDS)


def _map_priority(value: Any) -> str:
    """Explicit priority -> High/Medium/Low; anything else -> None."""
    text = _text(value).lower()
    return _PRIORITY_WORDS.get(text)


def _map_category(*texts: Any) -> str:
    """Map free text to one of the six frontend categories, else "Other"."""
    for raw in texts:
        text = _text(raw)
        if not text:
            continue
        lowered = text.lower()
        for category in CATEGORIES:
            if lowered == category.lower():
                return category
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                return category
    return "Other"


# --------------------------------------------------------------------------
# adapt_chat
# --------------------------------------------------------------------------

def _facts(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(value.get("facts") or {}, "state.facts")


def _sleep_period(facts: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for entry in facts.get("rest_periods") or []:
        if isinstance(entry, Mapping) and _is_sleep_title(_text(entry.get("title"))):
            return entry
    return None


def _task_card_details(entry: Mapping[str, Any]) -> str:
    parts: list[str] = []
    minutes = entry.get("estimated_minutes")
    if minutes:
        parts.append(f"时长 {minutes} 分钟")
    deadline = entry.get("deadline")
    if deadline:
        parts.append(f"截止 {deadline}")
    priority = entry.get("priority")
    if priority:
        parts.append(f"优先级 {priority}")
    category = entry.get("category")
    if category:
        parts.append(f"类别 {category}")
    period = entry.get("preferred_period")
    if period:
        parts.append(f"偏好 {period}")
    start, end = entry.get("preferred_start"), entry.get("preferred_end")
    if start and end:
        parts.append(f"时间 {start}-{end}")
    days = entry.get("preferred_days")
    if days:
        parts.append(f"日期 {_days_text(list(days))}")
    notes = entry.get("notes")
    if notes:
        parts.append(_text(notes))
    return "；".join(parts)


def _routine_card_text(entry: Mapping[str, Any]) -> str:
    title = _text(entry.get("title"))
    minutes = entry.get("estimated_minutes")
    # The confirmation parser takes the text before the duration as the title.
    label = f"{title} {minutes} 分钟" if minutes else title
    details = []
    days = entry.get("weekdays")
    if days:
        details.append(_days_text(list(days)))
    start, end = entry.get("preferred_start"), entry.get("preferred_end")
    if start and end:
        details.append(f"{start}-{end}")
    return f"{label}（{'，'.join(details)}）" if details else label


def _rest_card_text(entry: Mapping[str, Any]) -> str:
    return (
        f"{_text(entry.get('title'))} {entry.get('start_time')}-{entry.get('end_time')}"
        f"（{_days_text(list(entry.get('days') or []))}）"
    )


def adapt_chat(result: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt ``handle_chat_message`` output to B's chat card contract.

    ``fields`` is always built from the FULL accumulated ``facts`` snapshot —
    never from the current round's extraction — so ``ready=true`` returns the
    complete picture the user is about to confirm.
    """
    result = _mapping(result, "handle_chat_message 结果")
    state = _mapping(result.get("state") or {}, "state")
    facts = _facts(state)
    week_start = _parse_iso_date(state.get("week_start"), "week_start")

    goals = facts.get("goals") or []
    tasks = [
        {"title": _text(entry.get("title")), "details": _task_card_details(entry)}
        for entry in (facts.get("tasks") or [])
        if isinstance(entry, Mapping) and _text(entry.get("title"))
    ]

    commitments: list[dict[str, str]] = []
    for entry in facts.get("fixed_commitments") or []:
        if not isinstance(entry, Mapping):
            continue
        day_of_week = entry.get("day_of_week")
        if not isinstance(day_of_week, int) or not 0 <= day_of_week <= 6:
            continue
        commitments.append(
            {
                "title": _text(entry.get("title")),
                "date": (week_start + timedelta(days=day_of_week)).isoformat(),
                "startTime": _text(entry.get("start")),
                "endTime": _text(entry.get("end")),
            }
        )

    wake = bed = ""
    sleep = _sleep_period(facts)
    if sleep is not None:
        bed = _text(sleep.get("start_time"))
        wake = _text(sleep.get("end_time"))

    rest_lines = [
        _rest_card_text(entry)
        for entry in (facts.get("rest_periods") or [])
        if isinstance(entry, Mapping) and not _is_sleep_title(_text(entry.get("title")))
    ]

    routine_lines = [
        _routine_card_text(entry)
        for entry in (facts.get("predictable_routines") or [])
        if isinstance(entry, Mapping) and _text(entry.get("title"))
    ]

    return {
        "reply": result.get("reply", ""),
        "state": state,
        "fields": {
            "goal": "\n".join(_text(goal) for goal in goals),
            "tasks": tasks,
            "commitments": commitments,
            "wake": wake,
            "bed": bed,
            "rest": "\n".join(rest_lines),
            "workStart": _text(facts.get("preferred_work_start")) or "09:00",
            "workEnd": _text(facts.get("preferred_work_end")) or "22:00",
            "routine": "\n".join(routine_lines),
        },
        "ready": bool(result.get("ready_for_confirmation")),
        "provider": result.get("provider"),
    }


# --------------------------------------------------------------------------
# confirmed_fields -> QuestionnaireData
# --------------------------------------------------------------------------

def _resolve_weekday_date(mention: str, week_start: date) -> date:
    """周一..周日 -> a concrete date inside the target week."""
    index = _CN_DAY_INDEX[mention]
    return week_start + timedelta(days=index)


def _parse_task_details(
    title: str, details: str, week_start: date
) -> tuple[dict[str, Any], list[str]]:
    """Best-effort deterministic parse of B's task ``details`` string.

    Returns ``(task_kwargs, warnings)``.  Unparseable text is never dropped:
    the raw details become ``notes`` and anything we could not pin down is
    reported through warnings instead of being invented.
    """
    warnings: list[str] = []
    kwargs: dict[str, Any] = {"title": title, "notes": _text(details)}

    minutes: int | None = None
    for match in _MINUTES_RE.finditer(details):
        number = float(match.group("num"))
        minutes = int(number * 60 if match.group("unit") in ("小时", "h", "hrs") else number)
        break
    if minutes is not None:
        kwargs["estimated_minutes"] = min(480, max(1, minutes))

    deadline: date | None = None
    iso = _DEADLINE_ISO_RE.search(details)
    if iso:
        deadline = date(int(iso[1]), int(iso[2]), int(iso[3]))
    else:
        md = _DEADLINE_MD_RE.search(details)
        if md:
            deadline = date(week_start.year, int(md[1]), int(md[2]))
        else:
            wd = _DEADLINE_WEEKDAY_RE.search(details)
            if wd:
                deadline = _resolve_weekday_date(wd[1], week_start)
    if deadline is not None:
        kwargs["deadline"] = datetime.combine(deadline, datetime.min.time())

    window = _TIME_RANGE_RE.search(details)
    if window:
        start = _normalise_hhmm(window.group("start"))
        end = _normalise_hhmm(window.group("end"))
        if start and end and start < end:
            kwargs["preferred_start"] = start
            kwargs["preferred_end"] = end
            if minutes is None:
                sh, sm = map(int, start.split(":"))
                eh, em = map(int, end.split(":"))
                kwargs["estimated_minutes"] = min(480, max(1, (eh * 60 + em) - (sh * 60 + sm)))
        else:
            warnings.append(f"任务「{title}」的时间窗口无法解析或无效：{window.group(0)!r}")

    days: list[int] = []
    for mention in _WEEKDAY_MENTION_RE.finditer(details):
        days.append(_CN_DAY_INDEX[mention[1]])
    for mention in _EN_WEEKDAY_RE.finditer(details):
        days.append(_EN_DAY_INDEX[mention[1].lower()])
    days = sorted(set(days))
    if days:
        kwargs["preferred_days"] = days

    period = _LOOSE_PERIOD_RE.search(details)
    if period:
        kwargs["preferred_period"] = {
            "早上": "morning", "早晨": "morning", "上午": "morning",
            "下午": "afternoon", "晚上": "evening", "傍晚": "evening",
        }[period[1]]

    repeat = _REPEAT_RE.search(details)
    if repeat:
        kwargs["repeat_weekly"] = True

    category = _CATEGORY_LABEL_RE.search(details)
    if category:
        kwargs["category"] = category[1]
    priority = _PRIORITY_LABEL_RE.search(details)
    if priority:
        mapped = _PRIORITY_WORDS.get(priority[1].lower())
        if mapped:
            kwargs["priority"] = mapped

    # Decide the duration type.  The scheduler honours preferred_days /
    # preferred_start only for PREDICTABLE tasks, so any task that pins down
    # a specific day or time window must be PREDICTABLE — otherwise the
    # user's requirement would be silently dropped.
    has_specific_time = bool(window) or bool(days)
    has_explicit_minutes = minutes is not None or bool(window)
    if has_specific_time:
        kwargs["duration_type"] = "predictable"
        warnings.append(
            f"任务「{title}」指定了具体日期/时间，按 PREDICTABLE 排程以尊重该偏好"
            "（不加 20% 缓冲）。"
        )
    elif has_explicit_minutes:
        kwargs["duration_type"] = "predictable"
    else:
        kwargs["duration_type"] = "uncertain"
    if period and not has_specific_time:
        warnings.append(
            f"任务「{title}」的偏好时段（{kwargs['preferred_period']}）"
            "暂不被调度器使用，任务将排入最早可用空档。"
        )
    return kwargs, warnings


def _commitments_from_card(
    card: Mapping[str, Any],
) -> tuple[list[FixedCommitment], list[str]]:
    warnings: list[str] = []
    commitments: list[FixedCommitment] = []
    raw = card.get("commitments")
    if raw is None:
        return commitments, warnings
    if not isinstance(raw, list):
        raise ValueError("confirmed_fields.commitments 必须是列表")
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"commitments[{index}] 必须是字典")
        title = _text(item.get("title"))
        if not title:
            raise ValueError(f"commitments[{index}].title 不能为空")
        day = _parse_iso_date(item.get("date"), f"commitments[{index}].date")
        start = _hhmm(item.get("startTime"), f"commitments[{index}].startTime")
        end = _hhmm(item.get("endTime"), f"commitments[{index}].endTime")
        if start is None or end is None:
            raise ValueError(f"commitments[{index}] 的 startTime/endTime 不能为空")
        start_dt = datetime.combine(day, datetime.strptime(start, "%H:%M").time())
        end_dt = datetime.combine(day, datetime.strptime(end, "%H:%M").time())
        if end_dt <= start_dt:
            raise ValueError(
                f"commitments[{index}]「{title}」结束时间必须晚于开始时间"
                "（不支持跨午夜固定承诺）"
            )
        commitments.append(FixedCommitment(title=title, start=start_dt, end=end_dt))
    return commitments, warnings


def _sleep_from_card(
    card: Mapping[str, Any],
) -> tuple[RestPeriod | None, list[str]]:
    warnings: list[str] = []
    wake = _hhmm(card.get("wake"), "wake")
    bed = _hhmm(card.get("bed"), "bed")
    if wake is None and bed is None:
        return None, warnings
    if wake is None or bed is None:
        warnings.append("wake 与 bed 必须同时提供，睡眠安排已跳过。")
        return None, warnings
    if wake == bed:
        raise ValueError("wake 与 bed 不能相同")
    return (
        RestPeriod(title="Sleep", days=list(range(7)), start_time=bed, end_time=wake),
        warnings,
    )


def _rest_periods_from_card(card: Mapping[str, Any]) -> tuple[list[RestPeriod], list[str]]:
    warnings: list[str] = []
    rest_periods: list[RestPeriod] = []
    text = _text(card.get("rest"))
    if not text:
        return rest_periods, warnings
    for chunk in re.split(r"[\n;；]+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        parsed = _parse_rest_period(chunk)
        if parsed is None:
            warnings.append(f"休息安排无法解析，已保留原文：{chunk}")
            continue
        rest_periods.append(RestPeriod(**parsed))
    return rest_periods, warnings


def _routines_from_card(
    card: Mapping[str, Any],
) -> tuple[list[PredictableRoutine], list[str], tuple[str, str] | None]:
    """Parse the routine text.  Returns (routines, warnings, work_hours).

    ``work_hours`` carries a (start, end) override when the text describes a
    work-hour preference instead of a real recurring activity.
    """
    warnings: list[str] = []
    routines: list[PredictableRoutine] = []
    work_hours: tuple[str, str] | None = None
    text = _text(card.get("routine"))
    if not text:
        return routines, warnings, work_hours
    for chunk in re.split(r"[\n;；]+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "工作" in chunk and "分钟" not in chunk:
            # Work-hour preference, not an activity: handled via workStart/end.
            window = _TIME_RANGE_RE.search(chunk)
            if window:
                start = _normalise_hhmm(window.group("start"))
                end = _normalise_hhmm(window.group("end"))
                if start and end and start < end:
                    work_hours = (start, end)
                    continue
            warnings.append(f"日常规律无法解析（不视为工作时段）：{chunk}")
            continue
        parsed = _parse_predictable_routine(chunk)
        if parsed is None:
            warnings.append(f"日常规律无法解析，已保留原文：{chunk}")
            continue
        routines.append(PredictableRoutine(**parsed))
    return routines, warnings, work_hours


def confirmed_fields_to_questionnaire(
    confirmed_fields: Mapping[str, Any],
    *,
    week_start: date | None = None,
) -> tuple[QuestionnaireData, list[str], dict[str, dict[str, Any]]]:
    """Convert B's confirmation card into V1.2 models.

    Returns ``(questionnaire, warnings, task_meta)``.  ``task_meta`` maps the
    final schedule ids ("t1".."tN") to explicit card facts
    (``priority``/``category``/``repeat_weekly``) so ``adapt_schedule`` never
    invents values.
    """
    card = _mapping(confirmed_fields, "confirmed_fields")
    week_start = week_start or _next_monday()
    warnings: list[str] = []
    task_meta: dict[str, dict[str, Any]] = {}

    # goal
    raw_goal = card.get("goal")
    if raw_goal is None:
        goals: list[str] = []
    elif isinstance(raw_goal, str):
        goals = [raw_goal.strip()] if raw_goal.strip() else []
    elif isinstance(raw_goal, list) and all(isinstance(g, str) for g in raw_goal):
        goals = [g.strip() for g in raw_goal if g.strip()]
    else:
        raise ValueError("confirmed_fields.goal 必须是字符串或字符串列表")

    # tasks
    tasks: list[TaskInput] = []
    raw_tasks = card.get("tasks")
    if raw_tasks is None:
        raw_tasks = []
    if not isinstance(raw_tasks, list):
        raise ValueError("confirmed_fields.tasks 必须是列表")
    for index, item in enumerate(raw_tasks, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"tasks[{index}] 必须是字典")
        title = _text(item.get("title"))
        if not title:
            raise ValueError(f"tasks[{index}].title 不能为空")
        kwargs, task_warnings = _parse_task_details(title, _text(item.get("details")), week_start)
        warnings.extend(task_warnings)
        repeat_weekly = kwargs.pop("repeat_weekly", False)
        priority = kwargs.pop("priority", None)
        category = kwargs.pop("category", None)
        tasks.append(
            TaskInput(
                title=title,
                estimated_minutes=kwargs.get("estimated_minutes", 45),
                deadline=kwargs.get("deadline"),
                category=category or "",
                preferred_period=kwargs.get("preferred_period") or "",
                notes=kwargs.get("notes") or "",
                duration_type=(
                    DurationType.PREDICTABLE
                    if kwargs.get("duration_type") == "predictable"
                    else DurationType.UNCERTAIN
                ),
                preferred_start=kwargs.get("preferred_start"),
                preferred_end=kwargs.get("preferred_end"),
                preferred_days=kwargs.get("preferred_days"),
            )
        )
        task_meta[f"t{index}"] = {
            "priority": priority,
            "category": category,
            "repeat_weekly": bool(repeat_weekly),
        }

    commitments, fixed_warnings = _commitments_from_card(card)
    warnings.extend(fixed_warnings)

    sleep, sleep_warnings = _sleep_from_card(card)
    warnings.extend(sleep_warnings)

    rest_periods, rest_warnings = _rest_periods_from_card(card)
    warnings.extend(rest_warnings)

    routines, routine_warnings, work_hours = _routines_from_card(card)
    warnings.extend(routine_warnings)
    for routine_index, routine in enumerate(routines, start=1):
        for weekday in routine.weekdays:
            task_meta[f"routine-{routine_index}-{weekday}"] = {
                "repeat_weekly": True,
                "category": _map_category(routine.title),
            }

    work_start = _hhmm(card.get("workStart"), "workStart")
    work_end = _hhmm(card.get("workEnd"), "workEnd")
    if work_hours is not None:
        work_start, work_end = work_hours
    if work_start is None and work_end is None:
        work_start, work_end = "09:00", "22:00"
    elif work_start is None or work_end is None:
        warnings.append("workStart 与 workEnd 必须同时提供，已使用默认 09:00-22:00。")
        work_start, work_end = "09:00", "22:00"
    elif work_start >= work_end:
        raise ValueError("workStart 必须早于 workEnd")

    rest_periods = ([sleep] if sleep is not None else []) + rest_periods
    questionnaire = QuestionnaireData(
        name="",
        goals=goals,
        tasks=tasks,
        fixed_commitments=commitments,
        preferred_work_start=work_start,
        preferred_work_end=work_end,
        week_start=week_start,
        rest_periods=rest_periods,
        predictable_routines=routines,
    )
    return questionnaire, warnings, task_meta


# --------------------------------------------------------------------------
# adapt_schedule
# --------------------------------------------------------------------------

def task_meta_from_facts(facts: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Explicit facts per final schedule id for the chat-state path.

    Chat facts never invent a weekly recurrence for one-time tasks, so only
    routine-derived entries get ``repeat_weekly=True`` here.
    """
    meta: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(facts.get("tasks") or [], start=1):
        if not isinstance(entry, Mapping):
            continue
        meta[f"t{index}"] = {
            "priority": entry.get("priority"),
            "category": entry.get("category"),
            "repeat_weekly": False,
        }
    for routine_index, entry in enumerate(
        facts.get("predictable_routines") or [], start=1
    ):
        if not isinstance(entry, Mapping):
            continue
        weekdays = entry.get("weekdays") or []
        for weekday in weekdays:
            meta[f"routine-{routine_index}-{weekday}"] = {
                "repeat_weekly": True,
                "category": _map_category(entry.get("title")),
            }
    return meta


def adapt_schedule(
    plan: Mapping[str, Any],
    *,
    meta: Mapping[str, Mapping[str, Any]] | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Convert a build_confirmed_schedule result into B's ``entries`` shape.

    Every entry has exactly: title, date, startTime, endTime, category,
    priority, repeatWeekly.  No legacy keys (id/start/end/is_fixed) leak out.
    """
    plan = _mapping(plan, "排程结果")
    meta = _mapping(meta or {}, "meta")
    schedule = plan.get("schedule")
    if not isinstance(schedule, list):
        raise ValueError("排程结果缺少 schedule 列表")

    entries: list[dict[str, Any]] = []
    for item in schedule:
        if not isinstance(item, Mapping):
            continue
        item_meta = meta.get(_text(item.get("id")), {})
        entries.append(
            {
                "title": _text(item.get("title")),
                "date": _text(item.get("date")),
                "startTime": _text(item.get("start")),
                "endTime": _text(item.get("end")),
                "category": _map_category(
                    item_meta.get("category"), item.get("category"), item.get("title")
                ),
                "priority": _map_priority(item_meta.get("priority")) or "Medium",
                "repeatWeekly": bool(item_meta.get("repeat_weekly")),
            }
        )
    entries.sort(key=lambda e: (e["date"], e["startTime"], e["endTime"], e["title"]))
    return {
        "entries": entries,
        "unscheduled": plan.get("unscheduled") or [],
        "warnings": list(plan.get("warnings") or []),
        "provider": provider,
    }


def plan_from_confirmed(
    confirmed_fields: Mapping[str, Any],
    *,
    week_start: date | None = None,
    now: datetime | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """One call: B's card -> V1.2 models -> real scheduler -> entries."""
    questionnaire, parse_warnings, task_meta = confirmed_fields_to_questionnaire(
        confirmed_fields, week_start=week_start
    )
    plan = plan_week(questionnaire, now=now)
    adapted = adapt_schedule(
        {"schedule": plan.schedule, "unscheduled": plan.unscheduled, "warnings": plan.warnings},
        meta=task_meta,
        provider=provider,
    )
    adapted["warnings"] = parse_warnings + adapted["warnings"]
    return adapted

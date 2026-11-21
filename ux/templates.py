"""Deterministic Guru Template catalog and pure upsell state.

This module deliberately has no Streamlit import: the catalog, access rules and
state transitions can be unit-tested without starting a web server.  All data is
local mock data; no payment provider is involved.
"""

from dataclasses import dataclass
from typing import Literal

Tier = Literal["free", "premium"]
UpsellContext = Literal["schedule_generated", "browse_premium", "advanced_features"]

PREMIUM_PRICE = "$12 / month (simulated)"
FREE_PLAN_NAME = "Free plan"
PREMIUM_PLAN_NAME = "Guru Premium"


@dataclass(frozen=True)
class GuruTemplate:
    """One template card in the marketplace."""

    template_id: str
    name: str
    description: str
    tier: Tier
    tagline: str
    benefits: tuple[str, ...]
    preview: tuple[str, ...]

    @property
    def is_premium(self) -> bool:
        return self.tier == "premium"


@dataclass(frozen=True)
class AdvancedFeature:
    """A premium-only capability advertised in the marketplace."""

    feature_id: str
    name: str
    description: str
    benefit: str


@dataclass
class MarketplaceState:
    """Small, serialisable UI state for the simulated upgrade flow."""

    is_premium: bool = False
    selected_template_id: str | None = None
    paywall_template_id: str | None = None
    applied_template_id: str | None = None
    paywall_count: int = 0

    def open_preview(self, template_id: str) -> None:
        """Select a template; premium templates also open the paywall."""
        template = get_template(template_id)
        self.selected_template_id = template_id
        if template.is_premium and not self.is_premium:
            self.paywall_template_id = template_id
            self.paywall_count += 1

    def close_paywall(self) -> None:
        self.paywall_template_id = None

    def upgrade(self) -> None:
        """Simulate a successful upgrade; no payment is performed."""
        self.is_premium = True
        self.paywall_template_id = None

    def return_to_free(self) -> None:
        """Return to the free plan and close any open paywall."""
        self.is_premium = False
        self.paywall_template_id = None

    def apply(self, template_id: str) -> None:
        """Record a template as applied only when the current plan allows it."""
        template = get_template(template_id)
        if not can_use(template, self.is_premium):
            self.open_preview(template_id)
            return
        self.selected_template_id = template_id
        self.applied_template_id = template_id


TEMPLATES: tuple[GuruTemplate, ...] = (
    GuruTemplate(
        template_id="deep-work-master-plan",
        name="Deep Work Master Plan",
        description=(
            "Protect two long focus blocks each day and let shallow work fill the gaps."
        ),
        tier="free",
        tagline="Best for writing, coding and exam revision",
        benefits=(
            "Two protected focus blocks per workday",
            "Shallow-work window after lunch",
            "Weekly review checklist",
        ),
        preview=(
            "Mon · 09:00–11:00 · Deep work sprint",
            "Mon · 14:00–15:00 · Shallow work batch",
            "Tue · 09:00–11:00 · Deep work sprint",
            "Wed · 09:00–10:30 · Deep work sprint",
        ),
    ),
    GuruTemplate(
        template_id="exam-preparation-system",
        name="Exam Preparation System",
        description=(
            "Turn a syllabus into spaced revision sessions with protected practice time."
        ),
        tier="premium",
        tagline="Built for the final four weeks before exams",
        benefits=(
            "Spaced repetition across every subject",
            "Practice-test blocks with review buffers",
            "Daily minimum revision target",
            "Exam-week fallback plan",
        ),
        preview=(
            "Mon · 18:00–19:30 · Calculus practice set",
            "Tue · 07:30–08:15 · Flashcards review",
            "Wed · 18:00–19:30 · Mock paper",
            "Thu · 07:30–08:15 · Error log review",
        ),
    ),
    GuruTemplate(
        template_id="ultimate-productivity-routine",
        name="Ultimate Productivity Routine",
        description=(
            "A high-intensity weekly routine that balances deep work, admin and recovery."
        ),
        tier="premium",
        tagline="For weeks with several competing deadlines",
        benefits=(
            "Adaptive priority triage",
            "Recovery and buffer blocks",
            "Deadline risk radar",
            "Friday shutdown ritual",
        ),
        preview=(
            "Mon · 08:30–10:30 · Priority deep work",
            "Mon · 16:30–17:00 · Admin sweep",
            "Tue · 08:30–10:30 · Priority deep work",
            "Fri · 16:00–16:45 · Weekly shutdown",
        ),
    ),
    GuruTemplate(
        template_id="elite-weekly-planner",
        name="Elite Weekly Planner",
        description=(
            "Start every week with a realistic capacity check and a clear top-three list."
        ),
        tier="free",
        tagline="A calm weekly reset that takes fifteen minutes",
        benefits=(
            "Top-three weekly outcomes",
            "Capacity check before committing",
            "Sunday planning ritual",
        ),
        preview=(
            "Sun · 19:00–19:30 · Weekly reset",
            "Mon · 08:45–09:00 · Top-three review",
            "Wed · 17:00–17:15 · Midweek check-in",
            "Fri · 16:30–16:45 · Close the week",
        ),
    ),
)

TEMPLATES_BY_ID = {template.template_id: template for template in TEMPLATES}

ADVANCED_FEATURES: tuple[AdvancedFeature, ...] = (
    AdvancedFeature(
        feature_id="auto-replan",
        name="Auto-replan my week",
        description="Rebuild the remaining week when a deadline or meeting changes.",
        benefit="Never manually rebuild a broken plan again",
    ),
    AdvancedFeature(
        feature_id="energy-aware",
        name="Energy-aware scheduling",
        description="Place hard work in your personal peak-energy window.",
        benefit="Match demanding tasks to your best hours",
    ),
    AdvancedFeature(
        feature_id="exam-mode",
        name="Exam countdown mode",
        description="Increase revision frequency as an exam gets closer.",
        benefit="A revision plan that tightens at the right time",
    ),
)

UPSELL_COPY: dict[UpsellContext, dict[str, str]] = {
    "schedule_generated": {
        "eyebrow": "Your free plan is ready",
        "title": "Want the plan that does the heavy lifting?",
        "body": (
            "Guru Premium adds adaptive replanning, energy-aware blocks and a "
            "deadline risk radar. Simulated upgrade — no payment is taken."
        ),
        "cta": "Explore Guru Templates",
    },
    "browse_premium": {
        "eyebrow": "Premium template",
        "title": "Unlock the complete playbook",
        "body": (
            "See the full routine, every benefit and the advanced planning tools. "
            "You can return to the Free plan at any time."
        ),
        "cta": "Unlock with Premium",
    },
    "advanced_features": {
        "eyebrow": "Advanced features",
        "title": "Put your week on autopilot",
        "body": (
            "Premium planning tools react to changes and protect your focus time. "
            "This is a product demo; no real payment is required."
        ),
        "cta": "See Premium options",
    },
}


def get_template(template_id: str) -> GuruTemplate:
    """Return a template or raise KeyError for an unknown id."""
    return TEMPLATES_BY_ID[template_id]


def can_use(template: GuruTemplate, is_premium: bool) -> bool:
    """Free templates are always usable; premium ones need the simulated plan."""
    return not template.is_premium or is_premium


def template_status(template: GuruTemplate, is_premium: bool) -> str:
    """Short status label shown on a marketplace card."""
    if can_use(template, is_premium):
        return "Unlocked" if template.is_premium else "Included in Free"
    return "Premium"


def preview_lines(template: GuruTemplate, is_premium: bool) -> tuple[str, ...]:
    """Show a locked teaser for premium templates until upgraded."""
    if can_use(template, is_premium):
        return template.preview
    return template.preview[:2]


def paywall_benefits(template: GuruTemplate) -> tuple[str, ...]:
    """Benefits plus the plan-level promise shown in the paywall."""
    return template.benefits + (
        "Replan without losing locked blocks",
        "Cancel or return to Free plan in one click",
    )

"""Tests for the pure Feature 02 catalog and upsell state."""

import unittest

from ux.templates import (
    ADVANCED_FEATURES,
    PREMIUM_PRICE,
    TEMPLATES,
    UPSELL_COPY,
    MarketplaceState,
    can_use,
    get_template,
    paywall_benefits,
    preview_lines,
    template_status,
)


class CatalogTests(unittest.TestCase):
    def test_catalog_is_deterministic_and_ordered(self) -> None:
        names = [template.name for template in TEMPLATES]
        self.assertEqual(
            names,
            [
                "Deep Work Master Plan",
                "Exam Preparation System",
                "Ultimate Productivity Routine",
                "Elite Weekly Planner",
            ],
        )
        self.assertEqual(len({template.template_id for template in TEMPLATES}), 4)

    def test_catalog_contains_free_and_premium(self) -> None:
        tiers = [template.tier for template in TEMPLATES]
        self.assertEqual(tiers.count("free"), 2)
        self.assertEqual(tiers.count("premium"), 2)

    def test_get_template_unknown_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            get_template("does-not-exist")

    def test_every_template_has_preview_and_benefits(self) -> None:
        for template in TEMPLATES:
            self.assertGreaterEqual(len(template.preview), 2)
            self.assertTrue(template.benefits)
            self.assertTrue(template.tagline)

    def test_can_use_free_template_without_premium(self) -> None:
        free = get_template("deep-work-master-plan")
        self.assertTrue(can_use(free, is_premium=False))
        self.assertTrue(can_use(free, is_premium=True))

    def test_premium_template_requires_premium(self) -> None:
        premium = get_template("exam-preparation-system")
        self.assertFalse(can_use(premium, is_premium=False))
        self.assertTrue(can_use(premium, is_premium=True))

    def test_status_labels(self) -> None:
        free = get_template("elite-weekly-planner")
        premium = get_template("ultimate-productivity-routine")
        self.assertEqual(template_status(free, False), "Included in Free")
        self.assertEqual(template_status(premium, False), "Premium")
        self.assertEqual(template_status(premium, True), "Unlocked")

    def test_locked_preview_is_a_teaser(self) -> None:
        premium = get_template("exam-preparation-system")
        self.assertEqual(len(preview_lines(premium, False)), 2)
        self.assertEqual(preview_lines(premium, True), premium.preview)

    def test_paywall_benefits_include_return_promise(self) -> None:
        benefits = paywall_benefits(get_template("exam-preparation-system"))
        self.assertIn("Cancel or return to Free plan in one click", benefits)

    def test_price_is_labelled_simulated(self) -> None:
        self.assertIn("simulated", PREMIUM_PRICE.lower())


class MarketplaceStateTests(unittest.TestCase):
    def test_default_state_is_free(self) -> None:
        state = MarketplaceState()
        self.assertFalse(state.is_premium)
        self.assertIsNone(state.paywall_template_id)

    def test_opening_premium_template_opens_paywall(self) -> None:
        state = MarketplaceState()
        state.open_preview("ultimate-productivity-routine")
        self.assertEqual(state.selected_template_id, "ultimate-productivity-routine")
        self.assertEqual(state.paywall_template_id, "ultimate-productivity-routine")
        self.assertEqual(state.paywall_count, 1)

    def test_opening_free_template_does_not_open_paywall(self) -> None:
        state = MarketplaceState()
        state.open_preview("deep-work-master-plan")
        self.assertIsNone(state.paywall_template_id)
        self.assertEqual(state.paywall_count, 0)

    def test_upgrade_unlocks_and_closes_paywall(self) -> None:
        state = MarketplaceState()
        state.open_preview("exam-preparation-system")
        state.upgrade()
        self.assertTrue(state.is_premium)
        self.assertIsNone(state.paywall_template_id)
        self.assertTrue(can_use(get_template("exam-preparation-system"), state.is_premium))

    def test_return_to_free_closes_paywall(self) -> None:
        state = MarketplaceState(is_premium=True, paywall_template_id="exam-preparation-system")
        state.return_to_free()
        self.assertFalse(state.is_premium)
        self.assertIsNone(state.paywall_template_id)

    def test_apply_locked_template_opens_paywall_instead(self) -> None:
        state = MarketplaceState()
        state.apply("exam-preparation-system")
        self.assertIsNone(state.applied_template_id)
        self.assertEqual(state.paywall_template_id, "exam-preparation-system")

    def test_apply_free_template_records_selection(self) -> None:
        state = MarketplaceState()
        state.apply("deep-work-master-plan")
        self.assertEqual(state.applied_template_id, "deep-work-master-plan")
        self.assertIsNone(state.paywall_template_id)

    def test_apply_premium_template_after_upgrade(self) -> None:
        state = MarketplaceState(is_premium=True)
        state.apply("ultimate-productivity-routine")
        self.assertEqual(state.applied_template_id, "ultimate-productivity-routine")


class UpsellCopyTests(unittest.TestCase):
    def test_all_three_touchpoints_have_copy(self) -> None:
        self.assertEqual(
            set(UPSELL_COPY),
            {"schedule_generated", "browse_premium", "advanced_features"},
        )
        for copy in UPSELL_COPY.values():
            self.assertTrue(copy["title"])
            self.assertTrue(copy["body"])
            self.assertTrue(copy["cta"])

    def test_advanced_features_are_premium(self) -> None:
        self.assertEqual(len(ADVANCED_FEATURES), 3)
        for feature in ADVANCED_FEATURES:
            self.assertTrue(feature.name)
            self.assertTrue(feature.description)


if __name__ == "__main__":
    unittest.main()

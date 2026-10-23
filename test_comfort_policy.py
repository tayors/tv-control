import copy
import unittest
from unittest.mock import patch

from comfort_policy import plan_feedback, remembered_point
from sensor_policy import evaluate


def sample(**changes):
    return {'awake': True, 'lux': 10, 'sensor_age_seconds': 0, 'picture_mode': 3,
            'hdr_setting': 1, 'adaptive_brightness': 1, 'backlight': 40, **changes}


class ComfortPolicyTests(unittest.TestCase):
    def teach(self, lux=10, brightness=40, memory=None, context=1):
        return plan_feedback(memory or {'points': []}, sample(lux=lux, backlight=brightness, hdr_setting=context),
                             'comfortable', 100, 'confirmed')[0]

    def test_no_preference_never_falls_back_to_old_curve(self):
        with patch('sensor_policy.target_for_lux', side_effect=AssertionError('Must not guess')):
            _, decision = evaluate({'strategy': 'learned'}, {}, sample(), 100)
        self.assertEqual(decision, {'action': 'skip', 'reason': 'unlearned_light'})

    def test_directional_feedback_is_trial_until_confirmed(self):
        memory, target, _ = plan_feedback({}, sample(), 'too-bright', 100, 'trial')
        self.assertEqual(target, 37)
        self.assertEqual(memory['points'], [])
        _, decision = evaluate({'strategy': 'learned'}, {'comfort': memory}, sample(backlight=37), 101)
        self.assertEqual(decision['reason'], 'awaiting_comfort')
        confirmed = self.teach(brightness=37, memory=memory)
        self.assertNotIn('pending', confirmed)
        self.assertEqual(remembered_point(confirmed, 12, [3, 1])['brightness'], 37)

    def test_only_similar_light_and_matching_picture_context_are_reused(self):
        memory = self.teach()
        self.assertIsNotNone(remembered_point(memory, 16, [3, 1]))
        self.assertIsNone(remembered_point(memory, 175, [3, 1]))
        self.assertIsNone(remembered_point(memory, 10, [3, 0]))
        self.assertIsNone(remembered_point(memory, 10, [53, 1]))

    def test_automatic_adjustment_reuses_confirmed_point_with_bounded_steps(self):
        memory = self.teach(brightness=50)
        _, decision = evaluate({'strategy': 'learned'}, {'comfort': memory}, sample(backlight=40), 101)
        self.assertEqual(decision['target'], 43)
        self.assertEqual(decision['curve_target'], 50)
        self.assertEqual(decision['target_source'], 'comfort_feedback')

    def test_unknown_light_leaves_picture_alone_even_with_other_preferences(self):
        _, decision = evaluate({'strategy': 'learned'}, {'comfort': self.teach()}, sample(lux=175), 101)
        self.assertEqual(decision['reason'], 'unlearned_light')

    def test_later_confirmation_updates_nearby_preference_but_preserves_other_conditions(self):
        memory = self.teach()
        memory = self.teach(lux=175, brightness=55, memory=memory)
        memory = self.teach(lux=12, brightness=35, memory=memory)
        self.assertEqual(len(memory['points']), 2)
        self.assertEqual(remembered_point(memory, 10, [3, 1])['brightness'], 35)
        self.assertEqual(remembered_point(memory, 175, [3, 1])['brightness'], 55)

    def test_interrupted_feedback_blocks_automatic_writes(self):
        _, decision = evaluate({'strategy': 'learned'}, {'comfort': self.teach(), 'feedback_in_flight': True}, sample(), 101)
        self.assertEqual(decision['reason'], 'feedback_incomplete')

    def test_nudges_are_bounded_and_inputs_unchanged(self):
        memory = self.teach()
        original = copy.deepcopy(memory)
        _, target, _ = plan_feedback(memory, sample(backlight=84), 'too-dark', 101, 'new')
        self.assertEqual(target, 85)
        self.assertEqual(memory, original)
        with self.assertRaises(ValueError):
            plan_feedback(memory, sample(backlight=5), 'too-bright', 101, 'new')

    def test_manual_change_still_takes_priority_in_learned_mode(self):
        state = {'comfort': self.teach(), 'last_context': [3, 1], 'last_expected': 40}
        changed, decision = evaluate({'strategy': 'learned'}, state, sample(backlight=45), 101)
        self.assertEqual(decision['reason'], 'manual_override')
        self.assertGreater(changed['hold_until'], 101)

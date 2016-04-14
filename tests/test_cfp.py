
from __future__ import absolute_import
import unittest
from apps.majority_judgement import get_floor_median, calculate_score, MajorityJudgementException

# TODO throw hypothesis tests at this, then sob
class CFPRankingTestCase(unittest.TestCase):
    def test_get_floor_median(self):
        assert get_floor_median([1]) == 1
        assert get_floor_median([1, 2]) == 1
        assert get_floor_median([1, 2, 3]) == 2
        assert get_floor_median([1, 2, 3, 4]) == 2
        assert get_floor_median([1, 2, 3, 4, 5]) == 3

    def test_calculate_score(self):
        score_set = [0, 0]
        assert calculate_score(score_set) == 0
        # Check it's non-destructive
        assert score_set == [0, 0]

        assert calculate_score([0, 1]) == 1
        # Check that it's sort-agnostic
        assert calculate_score([0, 1]) == calculate_score([1, 0])
        assert calculate_score([2, 2]) == 8

        # Because we take the median value out each time this is calculated
        # as 2 * 9 + 2 * 1
        assert calculate_score([2, 2, 0]) == 20
        assert calculate_score([2, 1, 2, 0]) == 47

        with self.assertRaises(MajorityJudgementException):
            calculate_score([2, 3])

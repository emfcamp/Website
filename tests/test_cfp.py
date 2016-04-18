
from __future__ import absolute_import
import unittest
from apps.majority_judgement import (
    get_floor_median, calculate_score, calculate_normalised_score,
    MajorityJudgementException
)


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

        # Check different bases work
        assert calculate_score([0, 1], 2) == 1
        assert calculate_score([0, 3], 4) == 3
        assert calculate_score([1, 0, 3], 4) == 19

        # Votes outside of the range [0, base) should fail (i.e. 0<= v < 3)
        with self.assertRaises(MajorityJudgementException):
            calculate_score([3])

        with self.assertRaises(MajorityJudgementException):
            calculate_score([-1])

    def test_calculate_normalised_score(self):
        # Basic tests
        assert calculate_normalised_score([1], 1) == 1
        assert calculate_normalised_score([1], 2) == 4

        expected = calculate_score([2, 2, 1])
        assert calculate_normalised_score([2, 2], 3) == expected

        expected = calculate_score([2, 2, 0])
        assert calculate_normalised_score([2, 2], 3, default_vote=0) == expected

        # Basic length checks
        with self.assertRaises(MajorityJudgementException):
            calculate_normalised_score([2, 2], 1)

        # Fail fast if default vote is out of bounds
        with self.assertRaises(MajorityJudgementException):
            calculate_normalised_score([2, 2], 1, default_vote=3)

        with self.assertRaises(MajorityJudgementException):
            calculate_normalised_score([2, 2], 1, default_vote=-1)



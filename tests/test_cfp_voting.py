import pytest
from hypothesis import given
from hypothesis.strategies import integers, lists, data
from apps.cfp_review.majority_judgement import (
    get_floor_median,
    calculate_score,
    calculate_normalised_score,
    calculate_max_normalised_score,
    MajorityJudgementException,
)


def test_get_floor_median():
    assert get_floor_median([1]) == 1
    assert get_floor_median([1, 2]) == 1
    assert get_floor_median([1, 2, 3]) == 2
    assert get_floor_median([1, 2, 3, 4]) == 2
    assert get_floor_median([1, 2, 3, 4, 5]) == 3
    with pytest.raises(Exception):
        get_floor_median([])


@given(lists(integers(), min_size=1))
def test_get_floor_median_2(values):
    result = get_floor_median(values)
    assert type(result) == int


def test_calculate_score():
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
    with pytest.raises(MajorityJudgementException):
        calculate_score([3])

    with pytest.raises(MajorityJudgementException):
        calculate_score([-1])


@given(data())
def test_calculate_score_2(data):
    base = data.draw(integers(min_value=2, max_value=36))
    score_list = data.draw(lists(integers(min_value=0, max_value=base - 1)))
    calculate_score(score_list, base)


def test_calculate_normalised_score():
    # Basic tests
    assert calculate_normalised_score([1], 1) == 1
    assert calculate_normalised_score([1], 2) == 4

    expected = calculate_score([2, 2, 1])
    assert calculate_normalised_score([2, 2], 3) == expected

    expected = calculate_score([2, 2, 0])
    assert calculate_normalised_score([2, 2], 3, default_vote=0) == expected

    # Basic length checks
    with pytest.raises(MajorityJudgementException):
        calculate_normalised_score([2, 2], 1)

    # Fail fast if default vote is out of bounds
    with pytest.raises(MajorityJudgementException):
        calculate_normalised_score([2, 2], 1, default_vote=3)

    with pytest.raises(MajorityJudgementException):
        calculate_normalised_score([2, 2], 1, default_vote=-1)


def test_calculate_max_normalised_score():
    def assert_within_delta(test, expected):
        result = calculate_max_normalised_score(test)
        assert -0.01 < result - expected < 0.01

    assert calculate_max_normalised_score([]) == 0
    assert_within_delta([0], 0.0)
    assert_within_delta([2], 1.0)

    assert_within_delta([0, 1], 0.125)
    assert_within_delta([2, 1], 0.625)
    assert_within_delta([2, 2, 1], 0.885)
    assert_within_delta([1, 2, 2, 1], 0.625)


def test_ordering():
    expected = [[2, 1], [1, 2, 2, 0], [1, 1], [2, 1, 0], [0, 2, 0]]
    test = [[0, 2, 0], [1, 2, 2, 0], [2, 1, 0], [2, 1], [1, 1]]

    # Sort test using the max normalised score
    result = sorted(test, key=lambda x: calculate_max_normalised_score(x), reverse=True)

    assert expected == result

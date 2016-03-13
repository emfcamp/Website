"""
Majority judgement is a voting system that aims to produce a ranking of all
candidates (from here-on 'submissions'). For a horrible wiki-hole on voting
theory, please see: https://en.wikipedia.org/wiki/Majority_judgment

This is designed to provide basic tools to play around with this voting system.

It has been set up with assumed use in ranking submissions to a CFP hence the
slightly odd terminology. The following substitutions are used:
    - Submission < - > candidate
    - Reviewer   < - > voter
    - Rating     < - > rank

A submissions score is its particular combination of ratings from the reviewers
(e.g. if there are 3 reviewers who rate 1, 0, and 1 respectively the
submissions' score is 0-1-1).

The majority judgement algorithm is this:
    1. Sort all submissions' ratings (to produce a score)
    2. Find the median rating of the score
    3. Group submissions by their median rating
    4. For each member of a group remove one instance of that group's
       median rating from the member's score
    5. Repeat steps 2-4 until the submissions are sorted or each group is empty
"""

class MajorityJudgementException(Exception):
    pass


def get_floor_median(values):
    """
    Return the middle element (rounding down) from a sorted list of values
    """
    if len(values) == 1:
        return values[0]
    elif len(values) == 0:
        raise Exception('Cannot find median of empty list')
    median_index = int((len(values) - 0.5) // 2)
    return values[median_index]

def calculate_score(score_list, base=3):
    """
    Using the majority judgement (MJ) algorithm (i.e. taking the median as the score
    for any round) calculate a score.

    The score is calculated by using the MJ sorted list of scores as the digits
    of a number in the base of the maximum score + 1 (e.g. if the max score that
    can be given by an individual is 2 the base is 3).

    e.g. the score list [2, 1, 2, 0] is scored as 47 (in base 3)
        [2, 1, 2, 0]              ->
        (sort)                    -> [0, 1, 2, 2]
        (MJ sort)                 -> [1, 2, 0, 2]
        (convert to base 3 value) -> [1*27, 2*9, 0*3, 2*1]
        (sum)                     -> 47
    """
    score_list = sorted(score_list[:])
    # Calculate our initial unit
    power = base ** (len(score_list) - 1)
    res = 0
    while score_list:
        score = get_floor_median(score_list)
        if score >= base:
            msg = 'Incorrectly set base. Got %d, expected values <%d' % (score, base)
            raise MajorityJudgementException(msg)
        res += score * power
        power = int(power / base)
        score_list.remove(score)
    return res

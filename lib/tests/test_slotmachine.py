import unittest
from collections import defaultdict

from slotmachine import SlotMachine, Unsatisfiable
Talk = SlotMachine.Talk


def unzip(l):
    return zip(*l)


class UtilTestCase(unittest.TestCase):
    def test_calculate_slots(self):
        event_start = '2016-08-05 13:00'
        slots_minimal = SlotMachine.calculate_slots(event_start, '2016-08-05 13:00', '2016-08-05 14:00')
        # the final slot is because all talks are made one slot longer for changeover
        assert slots_minimal == range(0, 6 + 1)
        slots_sat_13_16 = SlotMachine.calculate_slots(event_start, '2016-08-06 13:00', '2016-08-06 16:00')
        assert slots_sat_13_16 == range(144, 144 + 18 + 1)

class ScheduleTalksTestCase(unittest.TestCase):

    def setUp(self):
        # Due to @cached, we need to recreate SlotMachine each time
        pass

    def tearDown(self):
        pass

    def schedule_and_basic_asserts(self, talk_defs, talk_permissions, avail_slots, old_talks=None):
        if old_talks is None:
            old_talks = []

        talk_ids = [t.id for t in talk_defs]
        talk_defs_by_id = {t.id: t for t in talk_defs}

        sm = SlotMachine()
        sm.talk_permissions = talk_permissions

        solved = sm.schedule_talks(talk_defs, avail_slots, old_talks=old_talks)
        slots, talks, venues = unzip(solved)

        # All talks must be represented
        self.assertEqual(sorted(talks), sorted(talk_ids))
        # All slots/venue tuples must be different
        slot_venues = zip(slots, venues)
        self.assertEqual(sorted(set(slot_venues)), sorted(slot_venues))
        # Check slots are valid
        self.assertTrue(all(s in avail_slots for s in slots))

        used_slots = defaultdict(set)
        for slot, talk, venue in solved:
            talk_def = talk_defs_by_id[talk]
            talk_perms = talk_permissions[talk]

            self.assertIn(venue, talk_def.venues)

            self.assertIn(slot, talk_perms['slots'])
            self.assertIn(venue, talk_perms['venues'])

            for i in range(talk_def.duration):
                self.assertNotIn(slot + i, used_slots[venue])
                used_slots[venue].add(slot + i)

        return solved

    def schedule_and_assert_fails(self, talk_defs, talk_permissions, avail_slots, old_talks=None):
        if old_talks is None:
            old_talks = []

        sm = SlotMachine()
        sm.talk_permissions = talk_permissions

        with self.assertRaises(Unsatisfiable):
            solved = sm.schedule_talks(talk_defs, avail_slots, old_talks=old_talks)
            print(solved)

    def test_simple(self):
        talk_defs = [
            Talk(id=1, duration=3 + 1, venues=[101], speakers=['Speaker 1']),
            Talk(id=2, duration=3 + 1, venues=[101], speakers=['Speaker 2']),
            Talk(id=3, duration=3 + 1, venues=[101], speakers=['Speaker 3']),
        ]
        avail_slots = SlotMachine.calculate_slots('2016-08-06 13:00', '2016-08-06 13:00', '2016-08-06 15:00')
        talk_permissions = {  # why isn't this on the Talk object?
            1: {'slots': avail_slots[:], 'venues': [101]},  # why is venues in two places?
            2: {'slots': avail_slots[:], 'venues': [101]},
            3: {'slots': avail_slots[:], 'venues': [101]},
        }

        solved = self.schedule_and_basic_asserts(talk_defs, talk_permissions, avail_slots)

        # Solution should be stable
        solved_second = self.schedule_and_basic_asserts(talk_defs, talk_permissions, avail_slots, old_talks=solved)
        self.assertEqual(solved, solved_second)

    def test_too_many_talks(self):
        # This should just exceed the number of available slots (12 + 1)
        talk_defs = [
            Talk(id=1, duration=4 + 1, venues=[101], speakers=['Speaker 1']),
            Talk(id=2, duration=4 + 1, venues=[101], speakers=['Speaker 2']),
            Talk(id=3, duration=3 + 1, venues=[101], speakers=['Speaker 3']),
        ]
        avail_slots = SlotMachine.calculate_slots('2016-08-06 13:00', '2016-08-06 13:00', '2016-08-06 15:00')
        talk_permissions = {
            1: {'slots': avail_slots[:], 'venues': [101]},
            2: {'slots': avail_slots[:], 'venues': [101]},
            3: {'slots': avail_slots[:], 'venues': [101]},
        }

        self.schedule_and_assert_fails(talk_defs, talk_permissions, avail_slots)

    def test_two_venues(self):
        # talk 3 should end up in venue 102
        talk_defs = [
            Talk(id=1, duration=5 + 1, venues=[101], speakers=['Speaker 1']),
            Talk(id=2, duration=2 + 1, venues=[102], speakers=['Speaker 2']),
            Talk(id=3, duration=2 + 1, venues=[101, 102], speakers=['Speaker 3']),
        ]
        avail_slots = SlotMachine.calculate_slots('2016-08-06 13:00', '2016-08-06 13:00', '2016-08-06 14:00')
        talk_permissions = {
            1: {'slots': avail_slots[:], 'venues': [101]},
            2: {'slots': avail_slots[:], 'venues': [102]},
            3: {'slots': avail_slots[:], 'venues': [101, 102]},
        }

        solved = self.schedule_and_basic_asserts(talk_defs, talk_permissions, avail_slots)

        talk_venues = dict([(t, v) for s, t, v in solved])
        self.assertEqual(talk_venues[3], 102)

    def test_venue_too_full(self):
        # Talks 1 and 3 won't fit into 101 together, and 3 and 4 won't fit in 102 together
        talk_defs = [
            Talk(id=1, duration=7 + 1, venues=[101], speakers=['Speaker 1']),
            Talk(id=2, duration=4 + 1, venues=[101, 102], speakers=['Speaker 2']),
            Talk(id=3, duration=5 + 1, venues=[101, 102], speakers=['Speaker 3']),
            Talk(id=4, duration=7 + 1, venues=[102], speakers=['Speaker 4']),
        ]
        avail_slots = SlotMachine.calculate_slots('2016-08-06 13:00', '2016-08-06 13:00', '2016-08-06 15:00')
        talk_permissions = {
            1: {'slots': avail_slots[:], 'venues': [101]},
            2: {'slots': avail_slots[:], 'venues': [101, 102]},
            3: {'slots': avail_slots[:], 'venues': [101, 102]},
            4: {'slots': avail_slots[:], 'venues': [102]},
        }

        self.schedule_and_assert_fails(talk_defs, talk_permissions, avail_slots)

    def test_venue_clash(self):
        # Talks 2 and 3 must move to accommodate talk 4
        talk_defs = [
            Talk(id=1, duration=7 + 1, venues=[101], speakers=['Speaker 1']),
            Talk(id=2, duration=4 + 1, venues=[101, 102], speakers=['Speaker 2']),
            Talk(id=3, duration=4 + 1, venues=[101, 102], speakers=['Speaker 3']),
            Talk(id=4, duration=7 + 1, venues=[102], speakers=['Speaker 4']),
        ]
        avail_slots = SlotMachine.calculate_slots('2016-08-06 13:00', '2016-08-06 13:00', '2016-08-06 15:00')
        talk_permissions = {
            1: {'slots': avail_slots[:], 'venues': [101]},
            2: {'slots': avail_slots[:], 'venues': [101, 102]},
            3: {'slots': avail_slots[:], 'venues': [101, 102]},
            4: {'slots': avail_slots[:], 'venues': [102]},
        }

        old_talks = [
            (0, 1, 101),
            (2, 2, 102),
            (7, 3, 102),
        ]
        solved = self.schedule_and_basic_asserts(talk_defs, talk_permissions, avail_slots, old_talks=old_talks)

        # Talk 1 shouldn't move
        self.assertIn((0, 1, 101), solved)

    def test_speaker_clash(self):
        # Talk 4 is by Speaker 1
        talk_defs = [
            Talk(id=1, duration=7 + 1, venues=[101], speakers=['Speaker 1']),
            Talk(id=2, duration=7 + 1, venues=[102], speakers=['Speaker 2']),
            Talk(id=3, duration=4 + 1, venues=[101, 102], speakers=['Speaker 3']),
            Talk(id=4, duration=4 + 1, venues=[101, 102], speakers=['Speaker 1']),
        ]
        avail_slots = SlotMachine.calculate_slots('2016-08-06 13:00', '2016-08-06 13:00', '2016-08-06 15:00')
        talk_permissions = {
            1: {'slots': avail_slots[:], 'venues': [101]},
            2: {'slots': avail_slots[:], 'venues': [101, 102]},
            3: {'slots': avail_slots[:], 'venues': [101, 102]},
            4: {'slots': avail_slots[:], 'venues': [102]},
        }

        # Either talk 2 or 3 will have to move
        old_talks = [
            (0, 1, 101),
            (5, 2, 102),
            (8, 3, 101),
        ]
        solved = self.schedule_and_basic_asserts(talk_defs, talk_permissions, avail_slots, old_talks=old_talks)

        slots, talks, venues = unzip(solved)
        talks_slots = dict(zip(talks, slots))

        # There's no reason to move talk 1, so the speaker's only available afterwards
        self.assertTrue(talks_slots[4] >= 8)

    def test_talk_clash(self):
        # Talk 4 now has to precede talk 1. Talks 2 and 3 must remain in 102
        talk_defs = [
            Talk(id=1, duration=7 + 1, venues=[101], speakers=['Speaker 1']),
            Talk(id=2, duration=5 + 1, venues=[101, 102], speakers=['Speaker 2']),
            Talk(id=3, duration=5 + 1, venues=[101, 102], speakers=['Speaker 3']),
            Talk(id=4, duration=2 + 1, venues=[101, 102], speakers=['Speaker 4']),
        ]
        avail_slots = SlotMachine.calculate_slots('2016-08-06 13:00', '2016-08-06 13:00', '2016-08-06 15:00')
        talk_permissions = {
            1: {'slots': avail_slots[:], 'venues': [101]},
            2: {'slots': avail_slots[:], 'venues': [101, 102]},
            3: {'slots': avail_slots[:], 'venues': [101, 102]},
            4: {'slots': [0, 1, 2], 'venues': [101, 102]},
        }

        # Talk 4 was previously scheduled after talk 1
        old_talks = [
            (0, 1, 101),
            (0, 2, 102),
            (6, 3, 102),
            (8, 4, 101),
        ]
        solved = self.schedule_and_basic_asserts(talk_defs, talk_permissions, avail_slots, old_talks=old_talks)

        slots, talks, venues = unzip(solved)
        talks_slots = dict(zip(talks, slots))

        # Talk 1 must now be in slot 3 or 4
        self.assertIn(talks_slots[1], [3, 4])



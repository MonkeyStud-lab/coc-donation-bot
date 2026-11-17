import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from coc_bot.donation.capacity_parser import RequestCapacity
from coc_bot.donation.chat_monitor import ChatMonitor, DonateRequest


class DonationReceipts(unittest.TestCase):
    def setUp(self):
        self.monitor = ChatMonitor.__new__(ChatMonitor)
        self.monitor.capture = Mock()
        self.monitor.capacity_parser = Mock()
        self.monitor.config = SimpleNamespace(handled_request_ttl_seconds=300)
        self.monitor._seen = {}
        self.monitor._handled = {}
        self.request = DonateRequest(Mock(), 'sig', capacity=RequestCapacity(5, 20, 1, 2, 0, 0),
                                     first_seen=10, card_header='same', full_capacity_read=True)

    def test_partial_wrong_card_and_changed_totals_do_not_verify_fill(self):
        full = RequestCapacity(0, 20, 0, 2, 0, 0)
        for header, readings, expected in [
            ('other', [], False), ('same', [full, self.request.capacity], False),
            ('same', [RequestCapacity(0, 20, 0, 0, 0, 0)], False), ('same', [full, full], True)
        ]:
            self.monitor._card_header = Mock(return_value=header)
            self.monitor.capacity_parser.parse.side_effect = readings
            self.assertEqual(self.monitor.verified_fill(self.request), expected)

    def test_unfilled_card_is_eligible_again_after_ten_seconds(self):
        with patch('time.time', return_value=100):
            self.monitor.retry_later(self.request)
        with patch('time.time', return_value=109):
            self.monitor._prune_handled()
            self.assertIn('sig', self.monitor._handled)
        with patch('time.time', return_value=110):
            self.monitor._prune_handled()
            self.assertNotIn('sig', self.monitor._handled)

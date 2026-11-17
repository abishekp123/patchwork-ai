import time
import unittest


class TimeoutTests(unittest.TestCase):
    def test_deliberately_exceeds_the_sandbox_deadline(self) -> None:
        time.sleep(30)

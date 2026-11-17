import unittest


class OutputBoundTests(unittest.TestCase):
    def test_output_is_bounded_by_the_host_adapter(self) -> None:
        print("x" * 200_000)
        self.assertTrue(True)

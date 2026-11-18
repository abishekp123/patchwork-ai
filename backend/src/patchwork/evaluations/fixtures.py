"""Small, standard-library-only datasets. Source strings are never executed on the host."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RepairFixture:
    name: str
    description: str
    source: str
    assertions: tuple[str, ...]

    @property
    def files(self) -> dict[str, str]:
        tests = (
            "import unittest\nfrom subject import repair\n\nclass RepairTests(unittest.TestCase):\n"
        )
        for index, assertion in enumerate(self.assertions):
            tests += f"    def test_{index}(self):\n        {assertion}\n"
        return {"subject.py": self.source, "fixture_test_repair.py": tests}


FIXTURES = (
    RepairFixture(
        "arithmetic",
        "repair(a, b) should add two integers, including zero and negatives.",
        "def repair(a, b):\n    return a - b\n",
        (
            "self.assertEqual(repair(2, 3), 5)",
            "self.assertEqual(repair(0, 4), 4)",
            "self.assertEqual(repair(-3, -2), -5)",
        ),
    ),
    RepairFixture(
        "off_by_one",
        "repair(n) should return all integers from zero through n, inclusive.",
        "def repair(n):\n    return list(range(n))\n",
        (
            "self.assertEqual(repair(0), [0])",
            "self.assertEqual(repair(2), [0, 1, 2])",
            "self.assertEqual(repair(-1), [])",
        ),
    ),
    RepairFixture(
        "boolean",
        "repair(active, verified) grants access only when both flags are true.",
        "def repair(active, verified):\n    return active or verified\n",
        (
            "self.assertFalse(repair(True, False))",
            "self.assertFalse(repair(False, True))",
            "self.assertTrue(repair(True, True))",
            "self.assertFalse(repair(False, False))",
        ),
    ),
    RepairFixture(
        "dictionary",
        "repair(mapping, key) returns its value, or None when the key is absent.",
        "def repair(mapping, key):\n    return mapping[key]\n",
        (
            "self.assertIsNone(repair({}, 'missing'))",
            "self.assertEqual(repair({'a': 3}, 'a'), 3)",
            "self.assertEqual(repair({'a': 0}, 'a'), 0)",
        ),
    ),
    RepairFixture(
        "conversion",
        "repair(value) converts text to an integer, returning None on invalid text.",
        "def repair(value):\n    try:\n        return int(value)\n"
        "    except TypeError:\n        return None\n",
        (
            "self.assertIsNone(repair('invalid'))",
            "self.assertEqual(repair('12'), 12)",
            "self.assertEqual(repair('-2'), -2)",
        ),
    ),
)

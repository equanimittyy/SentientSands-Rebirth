import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core import settings


class ProfitTargetMigrationTest(unittest.TestCase):
    def target(self, *lines):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "SentientSands_Config.ini")
            with open(path, "w") as f:
                f.write("\n".join(("[Settings]",) + lines) + "\n")
            with mock.patch.object(settings, "INI_PATH", path):
                return settings.load_settings()["barter_profit_target"]

    def test_the_old_default_under_the_old_key_takes_the_new_default(self):
        self.assertEqual(self.target("BarterProfitTarget = 70"), 400)

    def test_a_choice_under_the_old_key_stays(self):
        self.assertEqual(self.target("BarterProfitTarget = 150"), 150)

    def test_a_choice_of_70_under_the_new_key_stays(self):
        self.assertEqual(self.target("BarterProfitTarget = 70", "BarterProfitTargetPercent = 70"), 70)


if __name__ == "__main__":
    unittest.main()

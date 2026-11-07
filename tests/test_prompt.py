"""Keep the user-approved reading instructions unchanged during storage/UI changes."""
import hashlib
from pathlib import Path
import re
import unittest


class ReadingPromptTests(unittest.TestCase):
    def test_user_prompt_is_unchanged(self):
        skill = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
        blocks = re.findall(r'^<system_prompt>\n\n(.*?)\n\n</system_prompt>$', skill, re.M | re.S)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(hashlib.sha256(blocks[0].encode()).hexdigest(),
                         "3ac167d2f58ffd25b41dbc9b2435212e14618d80de4eb18e8304e50c6a04cba8")


if __name__ == "__main__":
    unittest.main()

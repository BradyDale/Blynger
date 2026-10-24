import subprocess
import unittest
from pathlib import Path


class OpenerTimestampTests(unittest.TestCase):
    def test_new_openers_use_central_time_without_renumbering_old_headings(self):
        source = Path("static/fragments.js").read_text(encoding="utf-8")
        checks = r"""
const methods = FragmentEditor.prototype;
const summer = methods.openerStamp.call(methods, new Date('2026-10-23T19:35:00Z'));
const winter = methods.openerStamp.call(methods, new Date('2026-12-23T20:35:00Z'));
if (summer !== 'October 23, 2026, 2:35 PM') throw new Error(summer);
if (winter !== 'December 23, 2026, 2:35 PM') throw new Error(winter);
"""
        subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-"],
            input=source + checks,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertNotIn("roman(number)", source)
        self.assertNotIn("sameDay", source)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from scripts.check_comments import violations


class CommentPolicyTests(unittest.TestCase):
    def check(self, suffix: str, content: str) -> list[int]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"sample{suffix}"
            path.write_text(content, encoding="utf-8")
            return violations(path)

    def test_accepts_urls_strings_and_operators(self) -> None:
        self.assertEqual(self.check(".ts", 'const url = "https://example.com/a#b";\nconst n = 8 / 2;\n'), [])

    def test_rejects_javascript_line_and_block_comments(self) -> None:
        self.assertEqual(self.check(".ts", "const value = 1; // forbidden\n/* forbidden */\n"), [1, 2])

    def test_rejects_python_comments_and_docstrings(self) -> None:
        self.assertEqual(self.check(".py", '"""forbidden"""\nvalue = 1 # forbidden\n'), [1, 2])

    def test_accepts_python_strings_and_shebang(self) -> None:
        self.assertEqual(self.check(".py", '#!/usr/bin/env python\nvalue = "# text"\n'), [])

    def test_rejects_yaml_comments(self) -> None:
        self.assertEqual(self.check(".yml", 'url: "https://example.com/#ok"\nvalue: yes # forbidden\n'), [2])

    def test_rejects_html_css_sql_and_docker_comments(self) -> None:
        self.assertEqual(self.check(".html", "<!-- forbidden -->\n"), [1])
        self.assertEqual(self.check(".css", "/* forbidden */\n"), [1])
        self.assertEqual(self.check(".sql", "SELECT 1; -- forbidden\n"), [1])


if __name__ == "__main__":
    unittest.main()

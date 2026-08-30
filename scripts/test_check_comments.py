import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.check_comments import main, violations


class CommentPolicyTests(unittest.TestCase):
    def check(self, suffix: str, content: str) -> list[int]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"sample{suffix}"
            path.write_text(content, encoding="utf-8")
            return violations(path)

    def named(self, name: str, content: str) -> list[int]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / name
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

    def test_rejects_config_names_with_hash_comments(self) -> None:
        names = (
            ".trivyignore",
            ".trivyignore-minio",
            ".trivyignore-web",
            ".gitignore",
            ".dockerignore",
            ".prettierignore",
            ".eslintignore",
            ".env.example",
            ".gitattributes",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(self.named(name, "# forbidden\nCVE-2024-1\n"), [1])

    def test_rejects_toml_comments(self) -> None:
        self.assertEqual(self.check(".toml", 'value = "a" # forbidden\n'), [1])

    def test_rejects_ini_cfg_and_conf_comments(self) -> None:
        self.assertEqual(self.check(".ini", "; forbidden\nkey = value\n"), [1])
        self.assertEqual(self.check(".cfg", "# forbidden\nkey = value\n"), [1])
        self.assertEqual(self.check(".conf", "; forbidden\nkey = value\n"), [1])

    def test_accepts_config_without_comments(self) -> None:
        self.assertEqual(self.named(".trivyignore-minio", "CVE-2024-1 exp:2026-12-31\n"), [])
        self.assertEqual(self.named(".gitignore", "node_modules/\n"), [])
        self.assertEqual(self.named(".env.example", "KEY=value\n"), [])
        self.assertEqual(self.check(".toml", 'value = "a"\n'), [])

    def test_toml_strings_with_hash_are_not_comments(self) -> None:
        self.assertEqual(self.check(".toml", 'value = "a#b"\n'), [])

    def test_unknown_explicit_file_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.bin"
            path.write_text("whatever\n", encoding="utf-8")
            with mock.patch("sys.argv", ["check_comments.py", str(path)]):
                with self.assertRaises(SystemExit) as raised:
                    main()
            self.assertEqual(raised.exception.code, 2)

    def test_unknown_tracked_file_errors(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "init", "-q"], cwd=directory, check=True)
            sample = Path(directory) / "sample.bin"
            sample.write_text("data\n", encoding="utf-8")
            subprocess.run(["git", "add", "sample.bin"], cwd=directory, check=True)
            os.chdir(directory)
            try:
                with mock.patch("sys.argv", ["check_comments.py"]):
                    with self.assertRaises(SystemExit) as raised:
                        main()
            finally:
                os.chdir(original)
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

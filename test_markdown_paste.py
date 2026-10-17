import unittest

from bs4 import BeautifulSoup

from markdown_paste import render_pasted_markdown


class MarkdownPasteTests(unittest.TestCase):
    def test_common_typora_and_obsidian_markdown(self):
        source = """## A heading

Ordinary **bold**, *italic*, and [linked](https://example.com) text.

> A quotation

- one
- two

```python
print('safe')
```

| Name | Value |
| --- | ---: |
| One | 1 |
"""
        soup = BeautifulSoup(render_pasted_markdown(source), "html.parser")
        self.assertEqual(soup.h2.get_text(), "A heading")
        self.assertEqual(soup.strong.get_text(), "bold")
        self.assertEqual(soup.em.get_text(), "italic")
        self.assertEqual(soup.a["href"], "https://example.com")
        self.assertEqual([li.get_text() for li in soup.ul.find_all("li")], ["one", "two"])
        self.assertIn("print('safe')", soup.pre.get_text())
        self.assertEqual(soup.table.find("th").get_text(), "Name")

    def test_active_html_is_removed(self):
        rendered = render_pasted_markdown("Hello <script>alert(1)</script> **world**")
        soup = BeautifulSoup(rendered, "html.parser")
        self.assertIsNone(soup.script)
        self.assertEqual(soup.strong.get_text(), "world")

    def test_size_limit(self):
        with self.assertRaisesRegex(ValueError, "too large"):
            render_pasted_markdown("x" * 500_001)


if __name__ == "__main__":
    unittest.main()

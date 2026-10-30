import json
import unittest

from chatgpt_share import _turns, import_share, parse_share_html


def message(role, text, *, hidden=False, final=True):
    metadata = {"is_visually_hidden_from_conversation": hidden}
    if role == "assistant" and final:
        metadata["finish_details"] = {"type": "stop"}
    return {
        "author": {"role": role},
        "content": {"content_type": "text", "parts": [text]},
        "end_turn": bool(final),
        "metadata": metadata,
        "recipient": "all",
    }


def flattened(value):
    values = []

    def add(item):
        index = len(values)
        values.append(None)
        if isinstance(item, dict):
            values[index] = {"_" + str(add(str(key))): add(child) for key, child in item.items()}
        elif isinstance(item, list):
            values[index] = [add(child) for child in item]
        else:
            values[index] = item
        return index

    add(value)
    return values


def share_page(turns):
    root = {
        "loaderData": {
            "routes/share.$shareId.($action)": {
                "serverResponse": {"data": {"linear_conversation": turns}}
            }
        }
    }
    serialized = json.dumps(flattened(root)) + "\n"
    script = (
        "window.__reactRouterContext.streamController.enqueue("
        + json.dumps(serialized)
        + ");"
    )
    return ("<html><script>" + script + "</script></html>").encode()


class ChatGPTShareTests(unittest.TestCase):
    def records(self):
        return [
            message("user", "First question."),
            message("user", "Private setup.", hidden=True),
            message("assistant", "Searching…", final=False),
            message("assistant", "First answer.\n\nSecond paragraph."),
            message("user", "One more thought."),
            message("user", "And another message."),
            message("assistant", "Final answer."),
        ]

    def test_visible_complete_turns_preserve_real_boundaries(self):
        turns = _turns({"linear_conversation": self.records()})
        self.assertEqual(
            [(turn["role"], turn["text"]) for turn in turns],
            [
                ("author", "First question."),
                ("assistant", "First answer.\n\nSecond paragraph."),
                ("author", "One more thought."),
                ("author", "And another message."),
                ("assistant", "Final answer."),
            ],
        )

    def test_react_router_share_payload_is_inflated(self):
        turns = parse_share_html(share_page(self.records()))
        self.assertEqual(len(turns), 5)
        self.assertEqual(turns[1]["role"], "assistant")
        self.assertIn("Second paragraph", turns[1]["text"])

    def test_fetch_is_bounded_and_restricted_to_chatgpt_share_urls(self):
        calls = []

        def fetcher(url, **options):
            calls.append((url, options))
            return url, share_page(self.records()), {"Content-Type": "text/html"}, 200

        url = "https://chatgpt.com/share/6ae37b48-dd14-83e9-b34a-90957c072e3a"
        result = import_share(url, fetcher)
        self.assertEqual(len(result["turns"]), 5)
        self.assertEqual(calls[0][1]["redirects"], 0)
        self.assertLessEqual(calls[0][1]["limit"], 6 * 1024 * 1024)
        for invalid in (
            "http://chatgpt.com/share/6ae37b48-dd14-83e9-b34a-90957c072e3a",
            "https://example.com/share/6ae37b48-dd14-83e9-b34a-90957c072e3a",
            "https://chatgpt.com.evil.test/share/6ae37b48-dd14-83e9-b34a-90957c072e3a",
            "https://chatgpt.com/share/not-an-id",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                import_share(invalid, fetcher)


if __name__ == "__main__":
    unittest.main()

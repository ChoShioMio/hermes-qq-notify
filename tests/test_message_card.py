"""Offline renderer tests: no notifier import, network, or private artifacts."""
import io
import unittest
from unittest.mock import patch

from PIL import Image


class MessageCardTests(unittest.TestCase):
    def test_vscode_dark_background_has_no_top_accent_stripe(self):
        from message_card import render_card
        with Image.open(io.BytesIO(render_card('# 深色通知\n\n正文'))) as image:
            self.assertEqual(image.getpixel((0, 0)), (30, 30, 30))
            self.assertEqual(image.getpixel((500, 3)), (30, 30, 30))
            self.assertEqual(image.getpixel((999, image.height - 1)), (30, 30, 30))
            colors = {color for count, color in image.getcolors(image.width * image.height)}
            self.assertIn((212, 212, 212), colors)

    def test_notification_emoji_do_not_become_missing_font_rectangles(self):
        from message_card import parse_blocks

        source = '⏱ 时间　✅ 任务完成\n\n🗂 会话：测试\n🏷 desktop\n📁 项目\n⚠️ 需要审批\n❓ 需要回答'
        visible = '\n'.join(span.text for block in parse_blocks(source) for span in block.spans)
        for symbol in ('⏱', '✅', '🗂', '🏷', '📁', '⚠', '\ufe0f', '❓'):
            self.assertNotIn(symbol, visible)
        for label in ('时间', '任务完成', '会话', '需要审批', '需要回答'):
            self.assertIn(label, visible)

    def test_missing_bold_face_can_use_regular_chinese_font(self):
        from message_card import _font
        from PIL import ImageFont

        original = ImageFont.truetype
        attempted = []

        def missing_bold(path, size, *args, **kwargs):
            attempted.append(path)
            if path != "C:/Windows/Fonts/msyh.ttc":
                raise OSError("font unavailable")
            return original(path, size, *args, **kwargs)

        _font.cache_clear()
        try:
            with patch.object(ImageFont, "truetype", missing_bold):
                font = _font(30, True)
            self.assertIn("C:/Windows/Fonts/msyh.ttc", attempted)
            self.assertNotEqual(bytes(font.getmask("中")), bytes(font.getmask("文")))
        finally:
            _font.cache_clear()

    def test_rich_card_never_fetches_links_or_images(self):
        from message_card import render_card

        markdown = "# 中文标题\n\n**粗体** [链接](https://invalid.example)\n\n![图片](https://invalid.example/a.png)\n\n```\nDO_NOT_DISPLAY\n```\n\n> 引用\n\n- 列表\n\n| 名称 | 状态 |\n| --- | --- |\n| 中文 | 完成 |"
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            result = render_card(markdown)
        with Image.open(io.BytesIO(result)) as image:
            image.load()
            self.assertGreater(image.height, 400)
            self.assertLessEqual(image.height, 6000)

    def test_chinese_wraps_and_styles_fit_inside_the_card(self):
        from message_card import FONT_SIZE, WIDTH, _font, _layout, parse_blocks

        lines, height = _layout(parse_blocks("# 中文标题\n\n" + "中文易读正文" * 35 + " **重点**\n\n> 引用内容"))
        self.assertGreater(len(lines), 5)
        self.assertGreaterEqual(FONT_SIZE, 28)
        self.assertTrue(any(line.size > FONT_SIZE for line in lines))
        self.assertTrue(any(span.bold for line in lines for span in line.spans))
        for line in lines:
            width = sum(_font(line.size, s.bold).getlength(s.text) for s in line.spans)
            self.assertLessEqual(width, WIDTH - 96)
            self.assertLess(line.y + line.size, height)

    def test_input_is_bounded_before_parsing_and_truncation_is_visible(self):
        from markdown_it import MarkdownIt
        from message_card import MAX_TEXT_CHARS, parse_blocks

        seen = []
        original = MarkdownIt.parse

        def record(parser, text, *args, **kwargs):
            seen.append(len(text))
            return original(parser, text, *args, **kwargs)

        with patch.object(MarkdownIt, "parse", record):
            blocks = parse_blocks("```\n" + "保密代码" * 100000)
        self.assertLessEqual(max(seen), MAX_TEXT_CHARS)
        visible = "".join(s.text for b in blocks for s in b.spans)
        self.assertIn("已截断", visible)
        self.assertIn("代码块已省略", visible)
        self.assertNotIn("保密代码", visible)

    def test_height_budget_also_marks_truncation_without_saving_or_network(self):
        from message_card import MAX_HEIGHT, _layout, parse_blocks, render_card

        source = "\n\n".join("第%d段中文通知" % i for i in range(500))
        lines, height = _layout(parse_blocks(source))
        self.assertLessEqual(height, MAX_HEIGHT)
        self.assertIn("已截断", "".join(s.text for s in lines[-1].spans))
        save = Image.Image.save

        def memory_only(image, target, *args, **kwargs):
            self.assertIsInstance(target, io.BytesIO)
            return save(image, target, *args, **kwargs)

        with patch("socket.socket", side_effect=AssertionError("network forbidden")), patch.object(Image.Image, "save", memory_only):
            data = render_card(source)
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            self.assertEqual(image.width, 1000)
            self.assertLessEqual(image.height, MAX_HEIGHT)

    def test_empty_and_long_unbroken_text_still_render(self):
        from message_card import render_card

        for text in ("", "x" * 100000, "正文\x00\ud800中文"):
            with self.subTest(length=len(text)):
                with Image.open(io.BytesIO(render_card(text))) as image:
                    image.load()
                    self.assertEqual(image.width, 1000)
                    self.assertLessEqual(image.height, 6000)

    def test_markdown_becomes_styled_readable_blocks_without_remote_resources(self):
        from message_card import parse_blocks

        blocks = parse_blocks(
            "# 任务完成\n\n正文 **重要** 和 `变量`，[说明](https://invalid.example)。\n\n"
            "- 第一项\n- 第二项\n\n1. 步骤一\n2. 步骤二\n\n> 引用中文\n\n"
            "| 名称 | 状态 |\n| --- | --- |\n| 测试 | 通过 |\n\n"
            "![私有图](https://invalid.example/image.png)"
        )
        visible = "\n".join("".join(s.text for s in b.spans) for b in blocks)
        for raw in ("# ", "**", "`", "https://", "![", "[说明]", "---"):
            self.assertNotIn(raw, visible)
        for expected in ("任务完成", "重要", "变量", "说明", "引用中文", "名称", "状态", "测试", "通过", "图片已省略"):
            self.assertIn(expected, visible)
        self.assertEqual(blocks[0].kind, "heading")
        self.assertTrue(any(s.bold and s.text == "重要" for b in blocks for s in b.spans))
        self.assertTrue(any(b.kind == "quote" for b in blocks))
        self.assertEqual(sum(b.kind == "list" for b in blocks), 4)
        self.assertEqual(sum(b.kind == "table" for b in blocks), 2)

    def test_fenced_and_indented_code_are_explicitly_omitted(self):
        from message_card import parse_blocks

        for source in ("```python\nSECRET_CODE = 42\n```", "~~~\nSECRET_CODE\n~~~", "    SECRET_CODE\n", "```\nSECRET_CODE"):
            with self.subTest(source=source):
                visible = "".join(s.text for b in parse_blocks(source) for s in b.spans)
                self.assertIn("代码块已省略", visible)
                self.assertNotIn("SECRET_CODE", visible)

    def test_render_returns_one_readable_chinese_png_in_memory(self):
        from message_card import render_card

        data = render_card("任务完成\n\n时间：2026-11-11\n中文通知正文。")
        self.assertIsInstance(data, bytes)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.width, 1000)
            self.assertGreater(image.height, 100)
            self.assertLessEqual(image.height, 6000)
            self.assertGreater(len(image.getcolors(image.width * image.height)), 2)


if __name__ == "__main__":
    unittest.main()

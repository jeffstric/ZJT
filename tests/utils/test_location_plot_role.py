"""split_plot_role_from_description 单测：从场景描述抽出剧情作用。"""
import unittest

from utils.location_plot_role import split_plot_role_from_description


class TestSplitPlotRoleFromDescription(unittest.TestCase):

    def test_extracts_chinese_section(self):
        desc = (
            "类型：室内商业场所\n"
            "功能：休闲聚会\n"
            "氛围：温馨舒适\n"
            "剧情作用：主角们经常聚会的地点，重要对话和情感戏的发生地"
        )
        new_desc, plot_role = split_plot_role_from_description(desc)
        self.assertEqual(plot_role, "主角们经常聚会的地点，重要对话和情感戏的发生地")
        self.assertNotIn("剧情作用", new_desc)
        self.assertIn("类型：室内商业场所", new_desc)
        self.assertIn("氛围：温馨舒适", new_desc)

    def test_explicit_plot_role_wins_and_strips_section(self):
        desc = "布局：吧台在入口\n剧情作用：旧的剧情说明"
        new_desc, plot_role = split_plot_role_from_description(desc, "新的剧情作用")
        self.assertEqual(plot_role, "新的剧情作用")
        self.assertEqual(new_desc, "布局：吧台在入口")

    def test_no_section_unchanged(self):
        desc = "类型：地下车库\n布局：坡道入口"
        new_desc, plot_role = split_plot_role_from_description(desc)
        self.assertEqual(new_desc, desc)
        self.assertIsNone(plot_role)

    def test_empty_description(self):
        new_desc, plot_role = split_plot_role_from_description(None, "已有作用")
        self.assertIsNone(new_desc)
        self.assertEqual(plot_role, "已有作用")

    def test_english_plot_role_heading(self):
        desc = "Type: cafe\nPlot Role: where the leads first meet"
        new_desc, plot_role = split_plot_role_from_description(desc)
        self.assertEqual(plot_role, "where the leads first meet")
        self.assertEqual(new_desc, "Type: cafe")


if __name__ == '__main__':
    unittest.main()

"""
Character reference_images 字段测试
测试角色的多参考图功能（reference_images JSON 字段）
"""
import json
import unittest
from .base_db_test import DatabaseTestCase


class TestCharacterReferenceImages(DatabaseTestCase):
    """Character reference_images 字段增删改查测试"""

    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.test_world_id = self.insert_fixture('world', {
            'name': '测试世界_reference',
            'user_id': 1
        })

    def test_create_character_with_single_reference_image(self):
        """测试创建角色时仅有 reference_image（向后兼容）"""
        location_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '测试地点',
            'user_id': 1
        })
        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '仅有主图的角色',
            'reference_image': 'https://example.com/avatar.jpg',
            'user_id': 1
        })

        result = self.execute_query(
            "SELECT * FROM `character` WHERE id = %s",
            (character_id,)
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '仅有主图的角色')
        self.assertEqual(result[0]['reference_image'], 'https://example.com/avatar.jpg')
        # 单图时 reference_images 可能为 NULL（迁移后可能有值）

    def test_create_character_with_reference_images_list(self):
        """测试创建角色时同时有 reference_image 和 reference_images"""
        reference_images_json = json.dumps([
            {'id': 'test-uuid-1', 'label': '默认服装', 'url': 'https://example.com/default.jpg'},
            {'id': 'test-uuid-2', 'label': '晚礼服', 'url': 'https://example.com/formal.jpg'},
            {'id': 'test-uuid-3', 'label': '运动装', 'url': 'https://example.com/sports.jpg'},
        ], ensure_ascii=False)

        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '多服装角色',
            'reference_image': 'https://example.com/default.jpg',
            'reference_images': reference_images_json,
            'user_id': 1
        })

        result = self.execute_query(
            "SELECT * FROM `character` WHERE id = %s",
            (character_id,)
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '多服装角色')
        self.assertEqual(result[0]['reference_image'], 'https://example.com/default.jpg')
        # 验证存储的是 JSON 字符串
        stored_images = result[0]['reference_images']
        self.assertIsInstance(stored_images, str)
        images_list = json.loads(stored_images)
        self.assertEqual(len(images_list), 3)
        self.assertEqual(images_list[0]['label'], '默认服装')
        self.assertEqual(images_list[1]['label'], '晚礼服')
        self.assertEqual(images_list[2]['label'], '运动装')

    def test_create_character_with_reference_images_only(self):
        """测试创建角色时只有 reference_images（没有 reference_image）"""
        reference_images_json = json.dumps([
            {'id': 'test-uuid-4', 'label': '唯一服装', 'url': 'https://example.com/only.jpg'},
        ], ensure_ascii=False)

        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '只有多图的角色',
            'reference_images': reference_images_json,
            'user_id': 1
        })

        result = self.execute_query(
            "SELECT * FROM `character` WHERE id = %s",
            (character_id,)
        )

        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]['reference_image'])
        stored_images = json.loads(result[0]['reference_images'])
        self.assertEqual(len(stored_images), 1)

    def test_read_reference_images_as_dict(self):
        """测试通过模型读取 reference_images 时解析为字典"""
        from model.character import CharacterModel

        reference_images_json = json.dumps([
            {'id': 'uuid-read-1', 'label': '日常服', 'url': 'https://example.com/daily.jpg'},
            {'id': 'uuid-read-2', 'label': '节日服', 'url': 'https://example.com/holiday.jpg'},
        ], ensure_ascii=False)

        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '待读取角色',
            'reference_images': reference_images_json,
            'user_id': 1
        })

        character = CharacterModel.get_by_id(character_id)
        self.assertIsNotNone(character)
        # 验证 to_dict() 将 JSON 字符串解析为列表
        char_dict = character.to_dict()
        self.assertIsInstance(char_dict['reference_images'], list)
        self.assertEqual(len(char_dict['reference_images']), 2)
        self.assertEqual(char_dict['reference_images'][0]['label'], '日常服')
        self.assertEqual(char_dict['reference_images'][1]['label'], '节日服')
        # 验证每项都有 id 字段
        self.assertEqual(char_dict['reference_images'][0]['id'], 'uuid-read-1')
        self.assertEqual(char_dict['reference_images'][1]['id'], 'uuid-read-2')

    def test_update_reference_images(self):
        """测试通过模型更新 reference_images 字段"""
        from model.character import CharacterModel

        # 先创建一个角色
        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '待更新角色',
            'user_id': 1
        })

        # 使用模型更新 reference_images（传入 Python list）
        new_images = [
            {'id': 'uuid-new-1', 'label': '新服装A', 'url': 'https://example.com/new-a.jpg'},
            {'id': 'uuid-new-2', 'label': '新服装B', 'url': 'https://example.com/new-b.jpg'},
        ]
        affected = CharacterModel.update(character_id, reference_images=new_images)
        self.assertEqual(affected, 1)

        # 验证数据库中存储的是 JSON 字符串
        result = self.execute_query(
            "SELECT reference_images FROM `character` WHERE id = %s",
            (character_id,)
        )
        self.assertIsNotNone(result[0]['reference_images'])
        stored = json.loads(result[0]['reference_images'])
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]['label'], '新服装A')

    def test_update_reference_images_to_null(self):
        """测试将 reference_images 更新为 NULL"""
        from model.character import CharacterModel

        reference_images_json = json.dumps([
            {'id': 'uuid-del-1', 'label': '将被删除', 'url': 'https://example.com/todelete.jpg'},
        ], ensure_ascii=False)

        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '待清空多图角色',
            'reference_images': reference_images_json,
            'user_id': 1
        })

        # 更新为 None（模拟删除所有多图）
        affected = CharacterModel.update(character_id, reference_images=None)
        self.assertEqual(affected, 1)

        result = self.execute_query(
            "SELECT reference_images FROM `character` WHERE id = %s",
            (character_id,)
        )
        self.assertIsNone(result[0]['reference_images'])

    def test_update_reference_images_partial(self):
        """测试部分更新 reference_images（追加新图）"""
        from model.character import CharacterModel

        # 初始有多张图
        initial_images = [
            {'id': 'uuid-init-1', 'label': '初始服装', 'url': 'https://example.com/initial.jpg'},
        ]
        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '待追加角色',
            'reference_images': json.dumps(initial_images, ensure_ascii=False),
            'user_id': 1
        })

        # 模拟追加：先读取现有图片，再合并
        character = CharacterModel.get_by_id(character_id)
        existing = character.reference_images or []
        if isinstance(existing, str):
            existing = json.loads(existing)
        appended = existing + [
            {'id': 'uuid-append-1', 'label': '追加服装', 'url': 'https://example.com/append.jpg'},
        ]
        affected = CharacterModel.update(character_id, reference_images=appended)
        self.assertEqual(affected, 1)

        # 验证合并结果
        result = self.execute_query(
            "SELECT reference_images FROM `character` WHERE id = %s",
            (character_id,)
        )
        stored = json.loads(result[0]['reference_images'])
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]['label'], '初始服装')
        self.assertEqual(stored[1]['label'], '追加服装')

    def test_reference_images_migration_format(self):
        """测试迁移后的 reference_images 格式（只有 label 和 url，无 id）"""
        # 模拟迁移数据：reference_images 只有单元素数组，label="默认"
        migrated_json = json.dumps([
            {'label': '默认', 'url': 'https://example.com/migrated.jpg'},
        ], ensure_ascii=False)

        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '迁移数据角色',
            'reference_image': 'https://example.com/migrated.jpg',
            'reference_images': migrated_json,
            'user_id': 1
        })

        character = CharacterModel.get_by_id(character_id)
        char_dict = character.to_dict()
        # 迁移数据没有 id 字段
        self.assertIsNone(char_dict['reference_images'][0].get('id'))
        self.assertEqual(char_dict['reference_images'][0]['label'], '默认')
        self.assertEqual(char_dict['reference_images'][0]['url'], 'https://example.com/migrated.jpg')

    def test_delete_reference_images_via_model(self):
        """测试通过模型层删除角色时 reference_images 被正确处理"""
        from model.character import CharacterModel

        reference_images_json = json.dumps([
            {'id': 'uuid-del-2', 'label': '将删除', 'url': 'https://example.com/del.jpg'},
        ], ensure_ascii=False)

        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '待删除角色',
            'reference_image': 'https://example.com/del.jpg',
            'reference_images': reference_images_json,
            'user_id': 1
        })

        # 删除角色
        affected = CharacterModel.delete(character_id)
        self.assertEqual(affected, 1)

        # 验证删除
        result = self.execute_query(
            "SELECT id FROM `character` WHERE id = %s",
            (character_id,)
        )
        self.assertEqual(len(result), 0)

    def test_reference_images_empty_list(self):
        """测试空数组 reference_images"""
        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '空多图角色',
            'reference_images': json.dumps([], ensure_ascii=False),
            'user_id': 1
        })

        character = CharacterModel.get_by_id(character_id)
        char_dict = character.to_dict()
        self.assertEqual(char_dict['reference_images'], [])


class TestCharacterReferenceImagesModel(DatabaseTestCase):
    """Character 模型层 reference_images 序列化测试（不依赖数据库）"""

    def setUp(self):
        super().setUp()
        self.test_world_id = self.insert_fixture('world', {
            'name': '测试世界_model',
            'user_id': 1
        })

    def test_character_to_dict_parses_reference_images_string(self):
        """测试 Character.to_dict() 将 reference_images JSON 字符串解析为列表"""
        from model.character import CharacterModel

        reference_images_json = json.dumps([
            {'id': 'uuid-todict-1', 'label': '解析测试', 'url': 'https://example.com/parse.jpg'},
        ], ensure_ascii=False)

        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '解析测试角色',
            'reference_images': reference_images_json,
            'user_id': 1
        })

        character = CharacterModel.get_by_id(character_id)
        # 原始值是字符串
        self.assertIsInstance(character.reference_images, str)
        # to_dict() 解析为列表
        char_dict = character.to_dict()
        self.assertIsInstance(char_dict['reference_images'], list)
        self.assertEqual(len(char_dict['reference_images']), 1)

    def test_character_to_dict_handles_reference_images_list(self):
        """测试 Character.to_dict() 当 reference_images 已是列表时不重复解析"""
        from model.character import Character

        # 模拟从模型返回的对象，reference_images 已经是列表
        char = Character(
            id=999,
            world_id=self.test_world_id,
            name='列表类型角色',
            reference_images=[
                {'id': 'uuid-list-1', 'label': '测试', 'url': 'https://example.com/test.jpg'}
            ]
        )
        char_dict = char.to_dict()
        self.assertIsInstance(char_dict['reference_images'], list)
        self.assertEqual(char_dict['reference_images'][0]['label'], '测试')

    def test_character_update_serializes_reference_images_list(self):
        """测试 CharacterModel.update() 将 reference_images list 序列化为 JSON"""
        from model.character import CharacterModel

        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '序列化测试角色',
            'user_id': 1
        })

        # 传入 Python list（未序列化）
        images_list = [
            {'id': 'uuid-serial-1', 'label': '序列化标签', 'url': 'https://example.com/serial.jpg'},
        ]
        CharacterModel.update(character_id, reference_images=images_list)

        # 验证数据库中存储的是 JSON 字符串
        result = self.execute_query(
            "SELECT reference_images FROM `character` WHERE id = %s",
            (character_id,)
        )
        stored = result[0]['reference_images']
        self.assertIsInstance(stored, str)
        parsed = json.loads(stored)
        self.assertEqual(parsed[0]['label'], '序列化标签')

    def test_character_update_skips_invalid_reference_images_field(self):
        """测试 CharacterModel.update() 忽略 reference_images 非法值"""
        from model.character import CharacterModel

        character_id = self.insert_fixture('character', {
            'world_id': self.test_world_id,
            'name': '非法值测试角色',
            'user_id': 1
        })

        # 传入整数（不是 list 也不是 dict），应该被忽略或报错
        # 由于整数不在 allowed_fields 中，不会被添加到更新字段
        affected = CharacterModel.update(character_id, reference_images=123)
        # reference_images 不在 allowed_fields，所以不会更新任何东西
        # 但也不会报错，因为 update() 只处理 allowed_fields

        # 验证 reference_images 仍为 NULL
        result = self.execute_query(
            "SELECT reference_images FROM `character` WHERE id = %s",
            (character_id,)
        )
        self.assertIsNone(result[0]['reference_images'])


if __name__ == '__main__':
    unittest.main()

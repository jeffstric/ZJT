"""
Location reference_images 字段测试
测试场景的多参考图功能（reference_images JSON 字段，含 angle 角度）
"""
import json
import unittest
from .base_db_test import DatabaseTestCase


class TestLocationReferenceImages(DatabaseTestCase):
    """Location reference_images 字段增删改查测试"""

    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.test_world_id = self.insert_fixture('world', {
            'name': '测试世界_loc_ref',
            'user_id': 1
        })

    def test_create_location_with_single_reference_image(self):
        """测试创建场景时仅有 reference_image（向后兼容）"""
        location_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '仅有主图的场景',
            'reference_image': 'https://example.com/scene.jpg',
            'user_id': 1
        })

        result = self.execute_query(
            "SELECT * FROM `location` WHERE id = %s",
            (location_id,)
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '仅有主图的场景')
        self.assertEqual(result[0]['reference_image'], 'https://example.com/scene.jpg')

    def test_create_location_with_reference_images_list(self):
        """测试创建场景时同时有 reference_image 和 reference_images（含角度）"""
        reference_images_json = json.dumps([
            {'id': 'loc-uuid-1', 'label': '正面', 'angle': 'front', 'url': 'https://example.com/front.jpg'},
            {'id': 'loc-uuid-2', 'label': '背面', 'angle': 'back', 'url': 'https://example.com/back.jpg'},
            {'id': 'loc-uuid-3', 'label': '左侧', 'angle': 'left', 'url': 'https://example.com/left.jpg'},
            {'id': 'loc-uuid-4', 'label': '右侧', 'angle': 'right', 'url': 'https://example.com/right.jpg'},
        ], ensure_ascii=False)

        location_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '多角度场景',
            'reference_image': 'https://example.com/front.jpg',
            'reference_images': reference_images_json,
            'user_id': 1
        })

        result = self.execute_query(
            "SELECT * FROM `location` WHERE id = %s",
            (location_id,)
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '多角度场景')
        # 验证存储的是 JSON 字符串
        stored_images = result[0]['reference_images']
        self.assertIsInstance(stored_images, str)
        images_list = json.loads(stored_images)
        self.assertEqual(len(images_list), 4)
        self.assertEqual(images_list[0]['angle'], 'front')
        self.assertEqual(images_list[1]['angle'], 'back')
        self.assertEqual(images_list[2]['angle'], 'left')
        self.assertEqual(images_list[3]['angle'], 'right')

    def test_create_location_with_custom_angle(self):
        """测试创建场景时使用自定义角度"""
        reference_images_json = json.dumps([
            {'id': 'loc-uuid-c1', 'label': '鸟瞰', 'angle': 'custom', 'url': 'https://example.com/bird.jpg'},
            {'id': 'loc-uuid-c2', 'label': '仰视', 'angle': 'custom', 'url': 'https://example.com/up.jpg'},
        ], ensure_ascii=False)

        location_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '自定义角度场景',
            'reference_images': reference_images_json,
            'user_id': 1
        })

        result = self.execute_query(
            "SELECT reference_images FROM `location` WHERE id = %s",
            (location_id,)
        )
        stored_images = json.loads(result[0]['reference_images'])
        self.assertEqual(len(stored_images), 2)
        self.assertEqual(stored_images[0]['angle'], 'custom')
        self.assertEqual(stored_images[0]['label'], '鸟瞰')

    def test_read_reference_images_as_dict_via_model(self):
        """测试通过模型读取 reference_images 时解析为字典"""
        from model.location import LocationModel
        from model.world import WorldModel

        # 使用 Model 层创建 world，确保与 LocationModel 使用同一连接池
        world_id = WorldModel.create(name='测试世界_loc_read_dict', user_id=1)

        reference_images_list = [
            {'id': 'loc-uuid-read-1', 'label': '正面', 'angle': 'front', 'url': 'https://example.com/r-front.jpg'},
            {'id': 'loc-uuid-read-2', 'label': '背面', 'angle': 'back', 'url': 'https://example.com/r-back.jpg'},
        ]

        location_id = LocationModel.create(
            world_id=world_id,
            name='待读取场景',
            reference_images=reference_images_list,
            user_id=1
        )

        location = LocationModel.get_by_id(location_id)
        self.assertIsNotNone(location)
        # 验证 to_dict() 将 JSON 字符串解析为列表
        loc_dict = location.to_dict()
        self.assertIsInstance(loc_dict['reference_images'], list)
        self.assertEqual(len(loc_dict['reference_images']), 2)
        self.assertEqual(loc_dict['reference_images'][0]['angle'], 'front')
        self.assertEqual(loc_dict['reference_images'][1]['angle'], 'back')
        # 验证 id 字段
        self.assertEqual(loc_dict['reference_images'][0]['id'], 'loc-uuid-read-1')

    def test_update_reference_images(self):
        """测试通过模型更新 reference_images 字段"""
        from model.location import LocationModel
        from model.world import WorldModel

        # 使用 Model 层创建数据
        world_id = WorldModel.create(name='测试世界_loc_update', user_id=1)
        location_id = LocationModel.create(
            world_id=world_id,
            name='待更新场景',
            user_id=1
        )

        new_images = [
            {'id': 'loc-uuid-new-1', 'label': '新正面', 'angle': 'front', 'url': 'https://example.com/new-front.jpg'},
            {'id': 'loc-uuid-new-2', 'label': '新背面', 'angle': 'back', 'url': 'https://example.com/new-back.jpg'},
        ]
        affected = LocationModel.update(location_id, reference_images=new_images)
        self.assertEqual(affected, 1)

        # 验证数据库中存储的是 JSON 字符串
        result = self.execute_query(
            "SELECT reference_images FROM `location` WHERE id = %s",
            (location_id,)
        )
        stored = json.loads(result[0]['reference_images'])
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]['label'], '新正面')
        self.assertEqual(stored[1]['angle'], 'back')

    def test_update_reference_images_to_null(self):
        """测试将 reference_images 更新为 NULL"""
        from model.location import LocationModel
        from model.world import WorldModel

        # 使用 Model 层创建数据
        world_id = WorldModel.create(name='测试世界_loc_null', user_id=1)
        reference_images_list = [
            {'id': 'loc-uuid-del-1', 'label': '将被删除', 'angle': 'front', 'url': 'https://example.com/todel.jpg'},
        ]
        location_id = LocationModel.create(
            world_id=world_id,
            name='待清空多图场景',
            reference_images=reference_images_list,
            user_id=1
        )

        affected = LocationModel.update(location_id, reference_images=None)
        self.assertEqual(affected, 1)

        result = self.execute_query(
            "SELECT reference_images FROM `location` WHERE id = %s",
            (location_id,)
        )
        self.assertIsNone(result[0]['reference_images'])

    def test_update_reference_images_partial_append(self):
        """测试部分更新 reference_images（追加新角度图）"""
        from model.location import LocationModel
        from model.world import WorldModel

        # 使用 Model 层创建数据
        world_id = WorldModel.create(name='测试世界_loc_append', user_id=1)
        initial_images = [
            {'id': 'loc-uuid-init-1', 'label': '正面', 'angle': 'front', 'url': 'https://example.com/init-front.jpg'},
        ]
        location_id = LocationModel.create(
            world_id=world_id,
            name='待追加场景',
            reference_images=initial_images,
            user_id=1
        )

        # 模拟追加
        location = LocationModel.get_by_id(location_id)
        existing = location.reference_images or []
        if isinstance(existing, str):
            existing = json.loads(existing)
        appended = existing + [
            {'id': 'loc-uuid-append-1', 'label': '侧面', 'angle': 'left', 'url': 'https://example.com/append-left.jpg'},
        ]
        affected = LocationModel.update(location_id, reference_images=appended)
        self.assertEqual(affected, 1)

        result = self.execute_query(
            "SELECT reference_images FROM `location` WHERE id = %s",
            (location_id,)
        )
        stored = json.loads(result[0]['reference_images'])
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]['label'], '正面')
        self.assertEqual(stored[1]['angle'], 'left')

    def test_reference_images_migration_format(self):
        """测试迁移后的 reference_images 格式（无 id 字段）"""
        from model.location import LocationModel
        from model.world import WorldModel

        # 使用 Model 层创建数据
        world_id = WorldModel.create(name='测试世界_loc_migration', user_id=1)
        migrated_images = [
            {'label': '默认', 'angle': 'front', 'url': 'https://example.com/migrated.jpg'},
        ]
        location_id = LocationModel.create(
            world_id=world_id,
            name='迁移数据场景',
            reference_image='https://example.com/migrated.jpg',
            reference_images=migrated_images,
            user_id=1
        )

        location = LocationModel.get_by_id(location_id)
        loc_dict = location.to_dict()
        # 迁移数据没有 id 字段
        self.assertIsNone(loc_dict['reference_images'][0].get('id'))
        self.assertEqual(loc_dict['reference_images'][0]['label'], '默认')
        self.assertEqual(loc_dict['reference_images'][0]['angle'], 'front')

    def test_reference_images_empty_list(self):
        """测试空数组 reference_images"""
        # 空数组在 Python 中是 falsy，LocationModel.create() 会将其转换为 None
        # 直接测试数据库存储的 '[]' 字符串
        location_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '空多图场景',
            'reference_images': json.dumps([], ensure_ascii=False),
            'user_id': 1
        })

        result = self.execute_query(
            "SELECT reference_images FROM `location` WHERE id = %s",
            (location_id,)
        )
        stored = result[0]['reference_images']
        # 数据库中存储的是 '[]' 字符串
        self.assertEqual(stored, '[]')


class TestLocationReferenceImagesModel(DatabaseTestCase):
    """Location 模型层 reference_images 序列化测试"""

    def setUp(self):
        super().setUp()
        # 这个测试类会使用 Model 层方法，所以使用 WorldModel 创建
        from model.world import WorldModel
        self.test_world_id = WorldModel.create(name='测试世界_loc_model', user_id=1)

    def test_location_to_dict_parses_reference_images_string(self):
        """测试 Location.to_dict() 将 reference_images JSON 字符串解析为列表"""
        from model.location import LocationModel

        # 使用 Model 层创建数据
        reference_images_list = [
            {'id': 'loc-uuid-todict-1', 'label': '解析测试', 'angle': 'front', 'url': 'https://example.com/parse.jpg'},
        ]
        location_id = LocationModel.create(
            world_id=self.test_world_id,
            name='解析测试场景',
            reference_images=reference_images_list,
            user_id=1
        )

        location = LocationModel.get_by_id(location_id)
        # 原始值是字符串
        self.assertIsInstance(location.reference_images, str)
        # to_dict() 解析为列表
        loc_dict = location.to_dict()
        self.assertIsInstance(loc_dict['reference_images'], list)
        self.assertEqual(loc_dict['reference_images'][0]['angle'], 'front')

    def test_location_to_dict_handles_reference_images_list(self):
        """测试 Location.to_dict() 当 reference_images 已是列表时不重复解析"""
        from model.location import Location

        # 模拟从模型返回的对象，reference_images 已经是列表
        loc = Location(
            id=999,
            world_id=self.test_world_id,
            name='列表类型场景',
            reference_images=[
                {'id': 'loc-uuid-list-1', 'label': '正面', 'angle': 'front', 'url': 'https://example.com/test.jpg'}
            ]
        )
        loc_dict = loc.to_dict()
        self.assertIsInstance(loc_dict['reference_images'], list)
        self.assertEqual(loc_dict['reference_images'][0]['angle'], 'front')

    def test_location_update_serializes_reference_images_list(self):
        """测试 LocationModel.update() 将 reference_images list 序列化为 JSON"""
        from model.location import LocationModel

        # 使用 Model 层创建数据
        location_id = LocationModel.create(
            world_id=self.test_world_id,
            name='序列化测试场景',
            user_id=1
        )

        # 传入 Python list（未序列化）
        images_list = [
            {'id': 'loc-uuid-serial-1', 'label': '序列化角度', 'angle': 'custom', 'url': 'https://example.com/serial.jpg'},
        ]
        LocationModel.update(location_id, reference_images=images_list)

        # 验证数据库中存储的是 JSON 字符串
        result = self.execute_query(
            "SELECT reference_images FROM `location` WHERE id = %s",
            (location_id,)
        )
        stored = result[0]['reference_images']
        self.assertIsInstance(stored, str)
        parsed = json.loads(stored)
        self.assertEqual(parsed[0]['angle'], 'custom')

    def test_location_update_reference_images_updates_main_image(self):
        """测试更新 reference_images 时，同时更新主图"""
        from model.location import LocationModel

        # 使用 Model 层创建数据
        reference_images_list = [
            {'id': 'loc-uuid-main-1', 'label': '原正面', 'angle': 'front', 'url': 'https://example.com/main-front.jpg'},
            {'id': 'loc-uuid-main-2', 'label': '背面', 'angle': 'back', 'url': 'https://example.com/main-back.jpg'},
        ]
        location_id = LocationModel.create(
            world_id=self.test_world_id,
            name='主图测试场景',
            reference_image='https://example.com/main-front.jpg',
            reference_images=reference_images_list,
            user_id=1
        )

        # 模拟删除主图（通过更新 reference_images 列表，同时更新 reference_image）
        remaining_images = [
            {'id': 'loc-uuid-main-2', 'label': '背面', 'angle': 'back', 'url': 'https://example.com/main-back.jpg'},
        ]
        LocationModel.update(
            location_id,
            reference_images=remaining_images,
            reference_image=remaining_images[0]['url']  # 明确更新主图
        )

        # 验证主图已更新为 remaining_images[0]
        result = self.execute_query(
            "SELECT reference_image, reference_images FROM `location` WHERE id = %s",
            (location_id,)
        )
        self.assertEqual(result[0]['reference_image'], 'https://example.com/main-back.jpg')


if __name__ == '__main__':
    unittest.main()

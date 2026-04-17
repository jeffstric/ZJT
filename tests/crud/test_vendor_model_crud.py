"""
VendorModel 表 CRUD 测试
"""
import unittest
from ..base.base_db_test import DatabaseTestCase


class TestVendorModelCRUD(DatabaseTestCase):
    """VendorModel 表增删改查测试"""

    def setUp(self):
        """设置测试数据"""
        super().setUp()
        # 确保有测试用的 vendor 和 model
        self.insert_fixture('vendor', {
            'id': 200,
            'vendor_name': 'test_vendor_for_vm',
            'note': '测试供应商'
        })
        self.insert_fixture('model', {
            'id': 2000,
            'model_name': 'test_model_for_vm',
            'context_window': 100000,
            'supports_tools': 1,
            'note': '测试模型'
        })

    def test_create_vendor_model(self):
        """测试创建供应商模型关联"""
        vm_id = self.insert_fixture('vendor_model', {
            'vendor_id': 200,
            'model_id': 2000,
            'input_token_threshold': 50000,
            'out_token_threshold': 5000,
            'cache_read_threshold': 50000
        })

        self.assertIsNotNone(vm_id)
        self.assertGreater(vm_id, 0)

    def test_read_vendor_model(self):
        """测试查询供应商模型关联"""
        self.insert_fixture('vendor_model', {
            'vendor_id': 200,
            'model_id': 2000,
            'input_token_threshold': 60000,
            'out_token_threshold': 6000,
            'cache_read_threshold': 60000
        })

        result = self.execute_query(
            "SELECT * FROM `vendor_model` WHERE vendor_id = %s AND model_id = %s",
            (200, 2000)
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['vendor_id'], 200)
        self.assertEqual(result[0]['model_id'], 2000)
        self.assertEqual(result[0]['input_token_threshold'], 60000)

    def test_update_vendor_model(self):
        """测试更新供应商模型关联"""
        vm_id = self.insert_fixture('vendor_model', {
            'vendor_id': 200,
            'model_id': 2000,
            'input_token_threshold': 70000,
            'out_token_threshold': 7000,
            'cache_read_threshold': 70000
        })

        affected_rows = self.execute_update(
            "UPDATE `vendor_model` SET input_token_threshold = %s WHERE id = %s",
            (80000, vm_id)
        )

        self.assertEqual(affected_rows, 1)

        result = self.execute_query(
            "SELECT * FROM `vendor_model` WHERE id = %s",
            (vm_id,)
        )

        self.assertEqual(result[0]['input_token_threshold'], 80000)

    def test_delete_vendor_model(self):
        """测试删除供应商模型关联"""
        vm_id = self.insert_fixture('vendor_model', {
            'vendor_id': 200,
            'model_id': 2000,
            'input_token_threshold': 90000,
            'out_token_threshold': 9000,
            'cache_read_threshold': 90000
        })

        count_before = self.count_rows('vendor_model', 'id = %s', (vm_id,))
        self.assertEqual(count_before, 1)

        affected_rows = self.execute_update(
            "DELETE FROM `vendor_model` WHERE id = %s",
            (vm_id,)
        )

        self.assertEqual(affected_rows, 1)

        count_after = self.count_rows('vendor_model', 'id = %s', (vm_id,))
        self.assertEqual(count_after, 0)

    def test_vendor_model_model_get_all(self):
        """测试 VendorModelModel.get_all() 方法"""
        self.insert_fixture('vendor_model', {
            'vendor_id': 200,
            'model_id': 2000,
            'input_token_threshold': 100000,
            'out_token_threshold': 10000,
            'cache_read_threshold': 100000
        })

        from model.vendor_model import VendorModelModel
        vendor_models = VendorModelModel.get_all()

        self.assertIsInstance(vendor_models, list)
        # 至少包含我们插入的一条
        found = any(vm.vendor_id == 200 and vm.model_id == 2000 for vm in vendor_models)
        self.assertTrue(found)

    def test_vendor_model_model_get_by_vendor_id(self):
        """测试 VendorModelModel.get_by_vendor_id() 方法"""
        self.insert_fixture('vendor_model', {
            'vendor_id': 200,
            'model_id': 2000,
            'input_token_threshold': 110000,
            'out_token_threshold': 11000,
            'cache_read_threshold': 110000
        })

        from model.vendor_model import VendorModelModel
        vendor_models = VendorModelModel.get_by_vendor_id(200)

        self.assertIsInstance(vendor_models, list)
        self.assertGreater(len(vendor_models), 0)
        self.assertTrue(all(vm.vendor_id == 200 for vm in vendor_models))


if __name__ == '__main__':
    unittest.main()

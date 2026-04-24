"""
Vendor 表 CRUD 测试
"""
import unittest
from ..base.base_db_test import DatabaseTestCase


class TestVendorCRUD(DatabaseTestCase):
    """Vendor 表增删改查测试"""

    def test_create_vendor(self):
        """测试创建供应商"""
        vendor_id = self.insert_fixture('vendor', {
            'id': 100,
            'vendor_name': 'test_vendor',
            'note': '测试供应商'
        })

        self.assertIsNotNone(vendor_id)
        self.assertEqual(vendor_id, 100)

    def test_read_vendor(self):
        """测试查询供应商"""
        vendor_id = self.insert_fixture('vendor', {
            'id': 101,
            'vendor_name': 'read_test_vendor',
            'note': '读取测试供应商'
        })

        result = self.execute_query(
            "SELECT * FROM `vendor` WHERE id = %s",
            (vendor_id,)
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['vendor_name'], 'read_test_vendor')
        self.assertEqual(result[0]['note'], '读取测试供应商')

    def test_update_vendor(self):
        """测试更新供应商"""
        vendor_id = self.insert_fixture('vendor', {
            'id': 102,
            'vendor_name': 'old_vendor',
            'note': '旧供应商'
        })

        affected_rows = self.execute_update(
            "UPDATE `vendor` SET vendor_name = %s, note = %s WHERE id = %s",
            ('new_vendor', '新供应商', vendor_id)
        )

        self.assertEqual(affected_rows, 1)

        result = self.execute_query(
            "SELECT * FROM `vendor` WHERE id = %s",
            (vendor_id,)
        )

        self.assertEqual(result[0]['vendor_name'], 'new_vendor')
        self.assertEqual(result[0]['note'], '新供应商')

    def test_delete_vendor(self):
        """测试删除供应商"""
        vendor_id = self.insert_fixture('vendor', {
            'id': 103,
            'vendor_name': 'temp_vendor',
            'note': '临时供应商'
        })

        count_before = self.count_rows('vendor', 'id = %s', (vendor_id,))
        self.assertEqual(count_before, 1)

        affected_rows = self.execute_update(
            "DELETE FROM `vendor` WHERE id = %s",
            (vendor_id,)
        )

        self.assertEqual(affected_rows, 1)

        count_after = self.count_rows('vendor', 'id = %s', (vendor_id,))
        self.assertEqual(count_after, 0)

    def test_vendor_dao_get_all(self):
        """测试 VendorDAO.get_all() 方法"""
        from model.vendor import VendorDAO
        # 使用 Model 层方法插入数据，确保在同一连接池可见
        vendor_id_1 = VendorDAO.create('vendor_a', '供应商A')
        vendor_id_2 = VendorDAO.create('vendor_b', '供应商B')

        vendors = VendorDAO.get_all()

        self.assertIsInstance(vendors, list)
        # 至少包含我们插入的两个
        vendor_ids = [v.id for v in vendors]
        self.assertIn(vendor_id_1, vendor_ids)
        self.assertIn(vendor_id_2, vendor_ids)

    def test_vendor_dao_get_by_id(self):
        """测试 VendorDAO.get_by_id() 方法"""
        from model.vendor import VendorDAO
        # 使用 Model 层方法插入数据
        vendor_id = VendorDAO.create('test_get_by_id', '测试获取')

        vendor = VendorDAO.get_by_id(vendor_id)

        self.assertIsNotNone(vendor)
        self.assertEqual(vendor.id, vendor_id)
        self.assertEqual(vendor.vendor_name, 'test_get_by_id')
        self.assertEqual(vendor.note, '测试获取')

    def test_vendor_dao_get_by_id_not_found(self):
        """测试 VendorDAO.get_by_id() 查询不存在的记录"""
        from model.vendor import VendorDAO
        vendor = VendorDAO.get_by_id(99999)

        self.assertIsNone(vendor)


if __name__ == '__main__':
    unittest.main()

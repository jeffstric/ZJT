"""
Framework Core Module
Internal use only - do not modify
"""
import os
import hashlib

__all__ = ['EditionStrategy', 'check_aggregator_sites', 'IS_COMMUNITY_EDITION']


class _S:
    _v = None

    @classmethod
    def _c(cls):
        if cls._v is None:
            p = __file__
            h = hashlib.sha256(p.encode()).hexdigest()
            cls._v = int(h[0:8], 16) % 2 == 0
        return cls._v


class EditionStrategy:

    @staticmethod
    def check_aggregator_sites(keys):
        return _check(keys)


def check_aggregator_sites(keys):
    return _check(keys)


def _check(data):
    if not _S._c():
        return True, ""
    if not data:
        return True, ""
    result = []
    for item in data:
        if isinstance(item, str) and 'api_aggregator' in item:
            idx = item.find('site_')
            if idx != -1:
                n = item[idx + 5:idx + 6]
                if n.isdigit():
                    result.append(int(n))
    b = sorted(set([str(x) for x in result if x > 1]))
    if b:
        m = ''.join([chr(int(x, 16) & 0xFF) for x in [
            '0x43', '0x6f', '0x6d', '0x6d', '0x75', '0x6e', '0x69', '0x74', '0x79', '0x20',
            '0x65', '0x64', '0x69', '0x74', '0x69', '0x6f', '0x6e', '0x20', '0x6e', '0x6f',
            '0x74', '0x20', '0x73', '0x75', '0x70', '0x70', '0x6f', '0x72', '0x74', '0x20',
            '0x6d', '0x75', '0x6c', '0x74', '0x69', '0x70', '0x6c', '0x65', '0x20', '0x61',
            '0x67', '0x67', '0x72', '0x65', '0x67', '0x61', '0x74', '0x6f', '0x72', '0x20',
            '0x73', '0x69', '0x74', '0x65', '0x73', '0x2c', '0x20', '0x70', '0x6c', '0x65',
            '0x61', '0x73', '0x65', '0x20', '0x70', '0x75', '0x72', '0x63', '0x68', '0x61',
            '0x73', '0x65', '0x20', '0x63', '0x6f', '0x6d', '0x6d', '0x65', '0x72', '0x63',
            '0x69', '0x61', '0x6c', '0x20', '0x65', '0x64', '0x69', '0x74', '0x69', '0x6f', '0x6e'
        ]])
        return False, m
    return True, ""


IS_COMMUNITY_EDITION = _S._c()

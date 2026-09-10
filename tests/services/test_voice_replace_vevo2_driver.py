"""Vevo2 驱动：zip 结果解析与 base_url 解析。"""
import io
import os
import unittest
import zipfile

from services.voice_replace.vevo2_driver import (
    Vevo2Driver,
    Vevo2Error,
    extract_converted_wav,
    get_vevo2_base_url,
)


def _zip_bytes(content: bytes, name: str = "converted.wav") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(name, content)
    return buf.getvalue()


class TestExtractConvertedWav(unittest.TestCase):
    def test_extracts_converted_wav(self):
        dest = os.path.join(self._tmp, "out.wav")
        extract_converted_wav(_zip_bytes(b"wavdata"), dest)
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), b"wavdata")

    def test_missing_converted_wav_raises(self):
        with self.assertRaises(Vevo2Error):
            extract_converted_wav(_zip_bytes(b"x", name="other.wav"), os.path.join(self._tmp, "o.wav"))

    def test_bad_zip_raises(self):
        with self.assertRaises(Vevo2Error):
            extract_converted_wav(b"not a zip", os.path.join(self._tmp, "o.wav"))

    def setUp(self):
        import tempfile

        self._tmp = tempfile.mkdtemp(prefix="vevo2_test_")


class TestBaseUrl(unittest.TestCase):
    def test_env_override(self):
        os.environ["VEVO2_URL"] = "http://127.0.0.1:9999/"
        try:
            self.assertEqual(get_vevo2_base_url(), "http://127.0.0.1:9999")
        finally:
            del os.environ["VEVO2_URL"]

    def test_default_constant(self):
        self.assertTrue(get_vevo2_base_url().startswith("http"))

    def test_driver_uses_injected_client_url(self):
        driver = Vevo2Driver(base_url="http://127.0.0.1:7863", flow_matching_steps=16)
        self.assertEqual(driver.flow_matching_steps, 16)


if __name__ == "__main__":
    unittest.main()

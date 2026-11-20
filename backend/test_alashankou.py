import tempfile
import unittest
from pathlib import Path

from backend import alashankou


class AlashankouCatalogTests(unittest.TestCase):
    def test_catalog_ignores_macos_metadata_files(self):
        original = alashankou.BASE
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '阿拉山口市典型负荷曲线.xlsx').write_bytes(b'placeholder')
            (root / '._阿拉山口市典型负荷曲线.xlsx').write_bytes(b'metadata')
            (root / '阿拉山口图纸.pdf').write_bytes(b'pdf')
            alashankou.BASE = root
            try:
                names = [item['name'] for item in alashankou.catalog()['files']]
            finally:
                alashankou.BASE = original
        self.assertIn('阿拉山口市典型负荷曲线.xlsx', names)
        self.assertIn('阿拉山口图纸.pdf', names)
        self.assertNotIn('._阿拉山口市典型负荷曲线.xlsx', names)


if __name__ == '__main__':
    unittest.main()

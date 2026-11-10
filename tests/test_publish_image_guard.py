import unittest
from pathlib import Path
from bureau.adapters import Media
from bureau.config import Config

class PublishingImageGuardTests(unittest.TestCase):
    def test_requires_five_images_before_network(self):
        media=Media(Config(Path('/tmp/unused.db'),{'ENABLE_EXTERNAL_CALLS':'1'}))
        with self.assertRaisesRegex(ValueError,'five'):
            media.verify({'files':[],'urls':[],'sha256':[]})

    def test_rejects_duplicate_images_before_network(self):
        media=Media(Config(Path('/tmp/unused.db'),{'ENABLE_EXTERNAL_CALLS':'1'}))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            media.verify({'files':['a']*5,'urls':['https://example.org/a']*5,'sha256':['same']*5})

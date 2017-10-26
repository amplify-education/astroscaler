"""Module for testing our resource helpers"""
from unittest import TestCase

from astroscaler.resource_helper import spotinst_tags_to_dict


class TestResourceHelpers(TestCase):
    """Class for testing our resource helpers"""

    def test_spotinst_tags(self):
        """Test that we can convert Spotinst tags correctly"""
        spotinst_tags = [
            {
                "tagKey": "foo",
                "tagValue": "bar"
            }
        ]

        actual_dict = spotinst_tags_to_dict(spotinst_tags)

        self.assertEqual(
            {"foo": "bar"},
            actual_dict
        )

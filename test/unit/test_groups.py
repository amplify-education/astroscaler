"""Module for testing our groups"""
from datetime import datetime, timedelta
from unittest import TestCase

from botocore.exceptions import ClientError
from dateutil.tz import tzutc
from mock import MagicMock

from astroscaler.exceptions import GroupScaleException, SpotinstApiException
from astroscaler.groups import AWSGroup, SpotinstGroup


YESTERDAYS_DATE = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


class TestAstroscalerGroups(TestCase):
    """Class for testing groups"""

    def test_aws_group_cannot_resize(self):
        """ Test that AWS Group handles client errors during resize """
        mock_client = MagicMock()
        mock_client.set_desired_capacity.side_effect = ClientError(
            error_response={"Error": {}},
            operation_name=None
        )

        group = AWSGroup(
            client=mock_client,
            provider_group={
                "AutoScalingGroupName": "test",
                "MinSize": 1,
                "MaxSize": 1,
                "DesiredCapacity": 1
            }
        )

        self.assertRaises(GroupScaleException, group.resize, new_size=1)

        mock_client.set_desired_capacity.assert_called_once_with(
            AutoScalingGroupName=group.name,
            DesiredCapacity=1
        )

    def test_aws_group_cannot_get_activities(self):
        """ Test that AWS Group handles client errors while getting activities """
        mock_client = MagicMock()
        mock_client.describe_scaling_activities.side_effect = ClientError(
            error_response={"Error": {}},
            operation_name=None
        )

        group = AWSGroup(
            client=mock_client,
            provider_group={
                "AutoScalingGroupName": "test",
                "MinSize": 1,
                "MaxSize": 1,
                "DesiredCapacity": 1
            }
        )

        self.assertRaises(GroupScaleException, group.is_cooling_down, cooldown=60)

        mock_client.describe_scaling_activities.assert_called_once_with(
            AutoScalingGroupName=group.name
        )

    def test_aws_group_is_already_scaling(self):
        """ Test that AWS Group is cooling down if in the middle of scaling """
        mock_client = MagicMock()
        mock_client.describe_scaling_activities.return_value = {
            "Activities": [
                {
                    "Cause": AWSGroup.AWS_SCALING_CAUSES[0]
                }
            ]
        }

        group = AWSGroup(
            client=mock_client,
            provider_group={
                "AutoScalingGroupName": "test",
                "MinSize": 1,
                "MaxSize": 1,
                "DesiredCapacity": 1
            }
        )

        response = group.is_cooling_down(cooldown=60)

        self.assertTrue(response)

        mock_client.describe_scaling_activities.assert_called_once_with(
            AutoScalingGroupName=group.name
        )

    def test_aws_group_is_inside_cooldown_period(self):
        """ Test that AWS Group is cooling down if the cooldown period hasnt expired """
        mock_client = MagicMock()
        mock_client.describe_scaling_activities.return_value = {
            "Activities": [
                {
                    "Cause": AWSGroup.AWS_SCALING_CAUSES[0],
                    "EndTime": datetime.utcnow()
                }
            ]
        }

        group = AWSGroup(
            client=mock_client,
            provider_group={
                "AutoScalingGroupName": "test",
                "MinSize": 1,
                "MaxSize": 1,
                "DesiredCapacity": 1
            }
        )

        response = group.is_cooling_down(cooldown=60)

        self.assertTrue(response)

        mock_client.describe_scaling_activities.assert_called_once_with(
            AutoScalingGroupName=group.name
        )

    def test_spotinst_group_cannot_resize_up(self):
        """ Test that Spotinst Group handles client errors during resize up """
        mock_client = MagicMock()
        mock_client.scale_up.side_effect = SpotinstApiException

        group = SpotinstGroup(
            client=mock_client,
            provider_group={
                "id": "test",
                "capacity": {
                    "minimum": 1,
                    "target": 1,
                    "maximum": 1
                }
            }
        )

        self.assertRaises(GroupScaleException, group.resize, new_size=2)

        mock_client.scale_up.assert_called_once_with(
            group_id=group.identifier,
            adjustment=1
        )

    def test_spotinst_group_cannot_resize_down(self):
        """ Test that Spotinst Group handles client errors during resize down """
        mock_client = MagicMock()
        mock_client.scale_down.side_effect = SpotinstApiException

        group = SpotinstGroup(
            client=mock_client,
            provider_group={
                "id": "test",
                "capacity": {
                    "minimum": 1,
                    "target": 2,
                    "maximum": 2
                }
            }
        )

        self.assertRaises(GroupScaleException, group.resize, new_size=1)

        mock_client.scale_down.assert_called_once_with(
            group_id=group.identifier,
            adjustment=1
        )

    def test_spotinst_group_cannot_get_events(self):
        """ Test that Spotinst Group handles API errors while getting event history"""
        mock_client = MagicMock()
        mock_client.get_group_events.side_effect = SpotinstApiException

        group = SpotinstGroup(
            client=mock_client,
            provider_group={
                "id": "test",
                "capacity": {
                    "minimum": 1,
                    "target": 2,
                    "maximum": 2
                }
            }
        )

        self.assertRaises(GroupScaleException, group.is_cooling_down, cooldown=60)

        mock_client.get_group_events.assert_called_once_with(
            group_id=group.identifier,
            from_date=YESTERDAYS_DATE
        )

    def test_spotinst_group_in_cooldown_period(self):
        """ Test that Spotinst Group is cooling down if the cooldown period hasnt expired """
        mock_client = MagicMock()
        mock_client.get_group_events.return_value = [
            {
                "eventType": SpotinstGroup.SPOTINST_SCALING_CAUSES[0],
                "createdAt": datetime.now(tzutc()).isoformat()
            }
        ]

        group = SpotinstGroup(
            client=mock_client,
            provider_group={
                "id": "test",
                "capacity": {
                    "minimum": 1,
                    "target": 1,
                    "maximum": 1
                }
            }
        )

        response = group.is_cooling_down(cooldown=60)

        self.assertTrue(response)

        mock_client.get_group_events.assert_called_once_with(
            group_id=group.identifier,
            from_date=YESTERDAYS_DATE
        )

    def test_spotinst_group_not_in_cooldown(self):
        """ Test that Spotinst Group is not cooling down if the cooldown period has expired """
        mock_client = MagicMock()
        mock_client.get_group_events.return_value = [
            {
                "eventType": SpotinstGroup.SPOTINST_SCALING_CAUSES[0],
                "createdAt": (datetime.now(tzutc()) - timedelta(minutes=5)).isoformat()
            }
        ]

        group = SpotinstGroup(
            client=mock_client,
            provider_group={
                "id": "test",
                "capacity": {
                    "minimum": 1,
                    "target": 1,
                    "maximum": 1
                }
            }
        )

        response = group.is_cooling_down(cooldown=60)

        self.assertFalse(response)

        mock_client.get_group_events.assert_called_once_with(
            group_id=group.identifier,
            from_date=YESTERDAYS_DATE
        )

    def test_spotinst_group_cooldown_no_events(self):
        """ Test that Spotinst Group is not cooling down if there are no events """
        mock_client = MagicMock()
        mock_client.get_group_events.return_value = []

        group = SpotinstGroup(
            client=mock_client,
            provider_group={
                "id": "test",
                "capacity": {
                    "minimum": 1,
                    "target": 1,
                    "maximum": 1
                }
            }
        )

        response = group.is_cooling_down(cooldown=60)

        self.assertFalse(response)

        mock_client.get_group_events.assert_called_once_with(
            group_id=group.identifier,
            from_date=YESTERDAYS_DATE
        )

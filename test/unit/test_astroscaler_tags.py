"""Test Astroscaler tags"""

from unittest import TestCase

import boto3

from mock import patch, MagicMock

from moto import mock_autoscaling

from astroscaler.handler import AstroScaler


MOCK_MONITOR_TYPE = "astroscaler"
MOCK_DATADOG_API_KEY = "mock_api_key"
MOCK_DATADOG_APP_KEY = "mock_app_key"
MOCK_MONITOR_SOURCE = "mock_source"
MOCK_GLOBAL_FILTERS = {}


@mock_autoscaling
class TestAstroscalerHandler(TestCase):
    """Test class for handler.AstroScaler"""

    def setUp(self):
        """Pre-test setup"""
        self.autoscaling_client = boto3.client('autoscaling')

        self.autoscaling_client.create_launch_configuration(LaunchConfigurationName='mock_lcn')

        with patch('datadog.initialize'):
            self.astroscaler = AstroScaler(
                MOCK_DATADOG_API_KEY,
                MOCK_DATADOG_APP_KEY,
                MOCK_GLOBAL_FILTERS,
                spotinst_client=MagicMock()
            )
            self.astroscaler.aws_client.describe_scaling_activities = MagicMock(
                return_value={'Activities': []}
            )

    def _mock_asgs(self, asgs):
        for mock_asg in asgs:
            self.autoscaling_client.create_auto_scaling_group(
                AutoScalingGroupName=mock_asg['asg_name'],
                LaunchConfigurationName='mock_lcn',
                MinSize=mock_asg['min_size'],
                MaxSize=mock_asg['max_size'],
                DesiredCapacity=mock_asg['desired_size'],
                AvailabilityZones=["foo"]
            )
            for key, value in mock_asg['tags'].iteritems():
                self.autoscaling_client.create_or_update_tags(
                    Tags=[{
                        'ResourceId': mock_asg['asg_name'],
                        'Key': key,
                        'Value': value
                    }]
                )

    @patch("datadog.api.Monitor.get_all")
    def test_default_tags(self, mock_get_datadog_monitors):
        """Test default tags (hostclass & environment) select correct group"""

        mock_get_datadog_monitors.return_value = [{
            'overall_state': 'Alert',
            'name': 'alerthostclass',
            'tags': [
                'monitor_type:astroscaler',
                'hostclass:mhcbar',
                'environment:foo_env',
                'policy_adjustment:+10%'
            ]
        }]

        self._mock_asgs([{
            'asg_name': 'alerthostclass',
            'tags': {
                'hostclass': 'mhcbar',
                'environment': 'foo_env'
            },
            'min_size': 1,
            'max_size': 10,
            'desired_size': 5
        }])

        self.astroscaler.run()

        asgs = self.autoscaling_client.describe_auto_scaling_groups()['AutoScalingGroups']
        asg_dict = {asg['AutoScalingGroupName']: asg for asg in asgs}

        self.assertEquals(asg_dict['alerthostclass']['DesiredCapacity'], 6)

    @patch("datadog.api.Monitor.get_all")
    def test_one_generic_tag(self, mock_get_datadog_monitors):
        """Test a generic tag selects correct group"""

        mock_get_datadog_monitors.return_value = [{
            'overall_state': 'Alert',
            'name': 'alertgroup',
            'tags': [
                'monitor_type:astroscaler',
                'astroscaler_group_tags:foo_tag',
                'foo_tag:foo',
                'policy_adjustment:+10%'
            ]
        }]

        self._mock_asgs([{
            'asg_name': 'alertgroup',
            'tags': {
                'foo_tag': 'foo'
            },
            'min_size': 1,
            'max_size': 10,
            'desired_size': 5
        }])

        self.astroscaler.run()

        asgs = self.autoscaling_client.describe_auto_scaling_groups()['AutoScalingGroups']
        asg_dict = {asg['AutoScalingGroupName']: asg for asg in asgs}

        self.assertEquals(asg_dict['alertgroup']['DesiredCapacity'], 6)

    @patch("datadog.api.Monitor.get_all")
    def test_multiple_generic_tags(self, mock_get_datadog_monitors):
        """Test multiple generic tags select correct group"""

        mock_get_datadog_monitors.return_value = [{
            'overall_state': 'Alert',
            'name': 'alertgroup',
            'tags': [
                'monitor_type:astroscaler',
                'astroscaler_group_tags:foo_tag,bar_tag',
                'foo_tag:foo',
                'bar_tag:bar',
                'policy_adjustment:+10%'
            ]
        }]

        self._mock_asgs([{
            'asg_name': 'alertgroup',
            'tags': {
                'foo_tag': 'foo',
                'bar_tag': 'bar'
            },
            'min_size': 1,
            'max_size': 10,
            'desired_size': 5
        }])

        self.astroscaler.run()

        asgs = self.autoscaling_client.describe_auto_scaling_groups()['AutoScalingGroups']
        asg_dict = {asg['AutoScalingGroupName']: asg for asg in asgs}

        self.assertEquals(asg_dict['alertgroup']['DesiredCapacity'], 6)

    @patch("datadog.api.Monitor.get_all")
    def test_nonexistent_generic_tags(self, mock_get_datadog_monitors):
        """Test nonexistent generic tags do not select a group"""

        mock_get_datadog_monitors.return_value = [{
            'overall_state': 'Alert',
            'name': 'alertgroup',
            'tags': [
                'monitor_type:astroscaler',
                'astroscaler_group_tags:foo_tag,bar_tag',
                'foo_tag:foo',
                'bar_tag:bar',
                'policy_adjustment:+10%'
            ]
        }]

        self._mock_asgs([{
            'asg_name': 'alertgroup',
            'tags': {
                'foo_tag': 'foo',
                'baz_tag': 'baz'
            },
            'min_size': 1,
            'max_size': 10,
            'desired_size': 5
        }])

        self.astroscaler.run()

        asgs = self.autoscaling_client.describe_auto_scaling_groups()['AutoScalingGroups']
        asg_dict = {asg['AutoScalingGroupName']: asg for asg in asgs}

        self.assertEquals(asg_dict['alertgroup']['DesiredCapacity'], 5)

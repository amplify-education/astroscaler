"""
Tests of astroscaler.SimpleAstroScaler
"""
from unittest import TestCase

import boto3

from mock import patch, MagicMock, ANY

from moto import mock_autoscaling, mock_s3

from astroscaler.handler import (
    AstroScaler,
    handler,
    S3_KEY_DATADOG_API_KEY,
    S3_KEY_DATADOG_APP_KEY,
    S3_KEY_SPOTINST_TOKEN)

from astroscaler.resource_helper import aws_tags_to_dict


MOCK_ENVIRONMENT = "mock_env"
MOCK_MONITOR_TYPE = "astroscaler"
MOCK_S3_BUCKET_PREFIX = 'credentials.'
MOCK_MONITOR_SOURCE = "mock_source"
MOCK_DATADOG_API_KEY = "mock_api_key"
MOCK_DATADOG_APP_KEY = "mock_app_key"
MOCK_POLICY_TYPE = "SimpleScaling"
OK_HOSTCLASS_DICTS = [{'hostclass': 'mockhostclass1',
                       'policy_name': 'up',
                       'environment': MOCK_ENVIRONMENT,
                       'is_testing': '0',
                       'min_size': 1,
                       'max_size': 10,
                       'desired_size': 5},
                      {'hostclass': 'mockhostclass2',
                       'policy_name': 'down',
                       'environment': MOCK_ENVIRONMENT,
                       'is_testing': '0',
                       'min_size': 1,
                       'max_size': 10,
                       'desired_size': 5}]
MOCK_GLOBAL_FILTERS = {"environment": MOCK_ENVIRONMENT}
MOCK_ASTROSCALER_GLOBAL_FILTERS = "environment:{}".format(MOCK_ENVIRONMENT)


def _create_monitor_from_hostclass_dict(hc_dict, state="Alert"):
    """ Convenience function for creating Datadog monitor from a hostclass dict """
    tags = [
        'monitor_type:{0}'.format(MOCK_MONITOR_TYPE),
        'hostclass:{0}'.format(hc_dict['hostclass']),
        'environment:{0}'.format(hc_dict['environment']),
        'source:{0}'.format(MOCK_MONITOR_SOURCE)
    ]

    policy_name = hc_dict.get('policy_name')
    policy_cooldown = hc_dict.get('policy_cooldown')
    policy_adjustment = hc_dict.get('policy_adjustment')

    if policy_name:
        tags.append(
            'policy_name:{0}_{1}_{2}_{3}'.format(
                hc_dict['environment'],
                hc_dict['hostclass'],
                hc_dict['is_testing'],
                policy_name
            )
        )
        tags.append('policy_type:{0}'.format(MOCK_POLICY_TYPE))

    if policy_cooldown:
        tags.append('policy_cooldown:{0}'.format(policy_cooldown))

    if policy_adjustment:
        tags.append('policy_adjustment:{0}'.format(policy_adjustment))

    return {
        'overall_state': state,
        'name': '{0}_{1}'.format(hc_dict['environment'], hc_dict['hostclass']),
        'tags': tags
    }


OK_MONITORS = [
    _create_monitor_from_hostclass_dict(hc_dict=hostclass_dict, state="Ok")
    for hostclass_dict in OK_HOSTCLASS_DICTS
]

ALERT_HOSTCLASS_DICTS = [{'hostclass': 'alerthostclass1',
                          'policy_name': 'up',
                          'environment': MOCK_ENVIRONMENT,
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass2',
                          'policy_name': 'down',
                          'environment': MOCK_ENVIRONMENT,
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass3',
                          'policy_name': 'down',
                          'environment': MOCK_ENVIRONMENT,
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass4',
                          'policy_name': 'up',
                          'environment': MOCK_ENVIRONMENT,
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass_already_min',
                          'policy_name': 'down',
                          'environment': MOCK_ENVIRONMENT,
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 1},
                         {'hostclass': 'alerthostclass_already_max',
                          'policy_name': 'up',
                          'environment': MOCK_ENVIRONMENT,
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 10},
                         # Mixing in some hostclass ASGs being in testing state
                         {'hostclass': 'alerthostclass5',
                          'policy_name': 'up',
                          'environment': MOCK_ENVIRONMENT,
                          'is_testing': '1',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass6',
                          'policy_name': 'down',
                          'environment': MOCK_ENVIRONMENT,
                          'is_testing': '1',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         # Mixing in some hostclasses in a random environemt
                         {'hostclass': 'alerthostclass7',
                          'policy_name': 'down',
                          'environment': 'random_env',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass8',
                          'policy_name': 'up',
                          'environment': 'random_env',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass9',
                          'environment': MOCK_ENVIRONMENT,
                          'expected_final_size': 7,
                          'policy_adjustment': '7',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass10',
                          'environment': MOCK_ENVIRONMENT,
                          'expected_final_size': 9,
                          'policy_adjustment': '+4',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass11',
                          'environment': MOCK_ENVIRONMENT,
                          'expected_final_size': 2,
                          'policy_adjustment': '-3',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass12',
                          'environment': MOCK_ENVIRONMENT,
                          'expected_final_size': 6,
                          'policy_adjustment': '+10%',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass13',
                          'environment': MOCK_ENVIRONMENT,
                          'expected_final_size': 2,
                          'policy_adjustment': '-50%',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass14_min_bound',
                          'environment': MOCK_ENVIRONMENT,
                          'expected_final_size': 1,
                          'policy_adjustment': '-500%',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass15_max_bound',
                          'environment': MOCK_ENVIRONMENT,
                          'expected_final_size': 10,
                          'policy_adjustment': '+100',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass16_wrong_env',
                          'environment': MOCK_ENVIRONMENT + "_WRONG",
                          'expected_final_size': 10,
                          'policy_adjustment': '+100',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 5},
                         {'hostclass': 'alerthostclass19_at_max',
                          'environment': MOCK_ENVIRONMENT,
                          'expected_final_size': 10,
                          'policy_adjustment': '+100',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 10},
                         {'hostclass': 'alerthostclass20_at_min',
                          'environment': MOCK_ENVIRONMENT,
                          'expected_final_size': 1,
                          'policy_adjustment': '-100',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 1},
                         {'hostclass': 'alerthostclass21_at_desired',
                          'environment': MOCK_ENVIRONMENT,
                          'expected_final_size': 2,
                          'policy_adjustment': '2',
                          'policy_cooldown': '60',
                          'is_testing': '0',
                          'min_size': 1,
                          'max_size': 10,
                          'desired_size': 2},
                         ]


ALERT_MONITORS = [
    _create_monitor_from_hostclass_dict(hc_dict=hostclass_dict)
    for hostclass_dict in ALERT_HOSTCLASS_DICTS
]

# A unrelated monitor, whose monitor type is not astroscaler
UNRELATED_MONITOR = [{'overall_state': 'Alert',
                      'tags': ['monitor_type:random_monitor_type',
                               'hostclass:random_hostclass',
                               'environment:random_environment',
                               'source:{0}'.format(MOCK_MONITOR_SOURCE)]}]

ALL_MONITORS = OK_MONITORS + ALERT_MONITORS + UNRELATED_MONITOR

MOCK_AUTOSCALING_GROUPS = [{'asg_name': '{0}_{1}_{2}'.format(hostclass_dict['environment'],
                                                             hostclass_dict['hostclass'],
                                                             hostclass_dict['is_testing']),
                            'environment': hostclass_dict['environment'],
                            'hostclass': hostclass_dict['hostclass'],
                            'is_testing': hostclass_dict['is_testing'],
                            'min_size': hostclass_dict['min_size'],
                            'max_size': hostclass_dict['max_size'],
                            'desired_size': hostclass_dict['desired_size']}
                           for hostclass_dict in OK_HOSTCLASS_DICTS + ALERT_HOSTCLASS_DICTS]

ALL_HOSTCLASS_DICTS = OK_HOSTCLASS_DICTS + ALERT_HOSTCLASS_DICTS


def _mock_describe_policies(**args):
    """ Inserting mock policy type to the ASG policies returned from moto """
    autoscaling_client = boto3.client('autoscaling')
    results = autoscaling_client.describe_policies(**args)
    for policy in results['ScalingPolicies']:
        policy['PolicyType'] = MOCK_POLICY_TYPE

    return results


@mock_autoscaling
class TestAstroscalerHandler(TestCase):
    """Test class for handler.AstroScaler"""

    def _create_autoscaling_groups(self):
        autoscaling_client = boto3.client('autoscaling')

        autoscaling_client.create_launch_configuration(
            LaunchConfigurationName='mock_lcn')

        for mock_asg in MOCK_AUTOSCALING_GROUPS:
            autoscaling_client.create_auto_scaling_group(
                AutoScalingGroupName=mock_asg['asg_name'],
                LaunchConfigurationName='mock_lcn',
                MinSize=mock_asg['min_size'],
                MaxSize=mock_asg['max_size'],
                DesiredCapacity=mock_asg['desired_size'],
                AvailabilityZones=["foo"]
            )
            autoscaling_client.create_or_update_tags(
                Tags=[{'ResourceId': mock_asg['asg_name'],
                       'Key': 'environment',
                       'Value': mock_asg['environment']},
                      {'ResourceId': mock_asg['asg_name'],
                       'Key': 'hostclass',
                       'Value': mock_asg['hostclass']},
                      {'ResourceId': mock_asg['asg_name'],
                       'Key': 'is_testing',
                       'Value': mock_asg['is_testing']}])
            autoscaling_client.put_scaling_policy(
                AutoScalingGroupName=mock_asg['asg_name'],
                PolicyName='{0}_{1}'.format(mock_asg['asg_name'], 'down'),
                PolicyType='SimpleScaling',
                AdjustmentType='PercentChangeInCapacity',
                ScalingAdjustment=-10,
                Cooldown=60,
                MinAdjustmentMagnitude=1)
            autoscaling_client.put_scaling_policy(
                AutoScalingGroupName=mock_asg['asg_name'],
                PolicyName='{0}_{1}'.format(mock_asg['asg_name'], 'up'),
                PolicyType='SimpleScaling',
                AdjustmentType='PercentChangeInCapacity',
                ScalingAdjustment=10,
                Cooldown=60,
                MinAdjustmentMagnitude=1)

    def setUp(self):
        """Pre-test setup"""
        self._create_autoscaling_groups()

        with patch('datadog.initialize'):
            self.astroscaler = AstroScaler(
                MOCK_DATADOG_API_KEY,
                MOCK_DATADOG_APP_KEY,
                MOCK_GLOBAL_FILTERS,
                spotinst_client=MagicMock()
            )

    @patch("datadog.api.Monitor.get_all")
    def test_successful_run(self, mock_get_datadog_monitors):
        """ Test a successful run """

        def _mock_get_datadog_monitors(monitor_tags):
            return [monitor for monitor in ALL_MONITORS
                    if set(monitor_tags) <= set(monitor['tags'])]

        mock_get_datadog_monitors.side_effect = _mock_get_datadog_monitors

        self.astroscaler.aws_client.describe_scaling_activities = MagicMock(return_value={'Activities': []})

        self.astroscaler.run()

        autoscaling_client = boto3.client('autoscaling')
        asgs = autoscaling_client.describe_auto_scaling_groups()['AutoScalingGroups']
        for asg in asgs:
            tags_dict = aws_tags_to_dict(asg['Tags'])
            if tags_dict.get('environment') == MOCK_ENVIRONMENT and \
                    self._is_alerted_hostclass(tags_dict.get('hostclass')):

                if self._get_monitor_policy(tags_dict.get('hostclass')).endswith('up'):
                    if self._at_max_size_initially(tags_dict.get('hostclass')):
                        self.assertEquals(asg['DesiredCapacity'],
                                          self._get_initial_size(
                                              tags_dict.get('hostclass'), 'desired_size'))
                    else:
                        self.assertEquals(asg['DesiredCapacity'],
                                          self._get_initial_size(
                                              tags_dict.get('hostclass'), 'desired_size') + 1)
                elif self._get_monitor_policy(tags_dict.get('hostclass')).endswith('down'):
                    if self._at_min_size_initially(tags_dict.get('hostclass')):
                        self.assertEquals(asg['DesiredCapacity'],
                                          self._get_initial_size(
                                              tags_dict.get('hostclass'), 'desired_size'))
                    else:
                        self.assertEquals(asg['DesiredCapacity'],
                                          self._get_initial_size(
                                              tags_dict.get('hostclass'), 'desired_size') - 1)
                else:
                    print(tags_dict.get('hostclass'))
                    self.assertEquals(
                        asg['DesiredCapacity'],
                        self._get_final_size(hostclass=tags_dict.get('hostclass'))
                    )
            else:
                self.assertEquals(asg['DesiredCapacity'],
                                  self._get_initial_size(
                                      tags_dict.get('hostclass'), 'desired_size'))

    def _is_alerted_hostclass(self, hostclass):
        return hostclass in [monitor['hostclass'] for monitor in ALERT_HOSTCLASS_DICTS]

    def _get_monitor_policy(self, hostclass):
        for monitor in ALERT_HOSTCLASS_DICTS:
            if hostclass == monitor['hostclass']:
                return monitor.get('policy_name', '')

        return None

    def _get_initial_size(self, hostclass, size_type):
        hc_dict = [_ for _ in ALL_HOSTCLASS_DICTS
                   if _['hostclass'] == hostclass]

        return hc_dict[0][size_type] if len(hc_dict) > 0 else None

    def _at_max_size_initially(self, hostclass):
        return self._get_initial_size(hostclass, 'desired_size') \
            == self._get_initial_size(hostclass, 'max_size')

    def _at_min_size_initially(self, hostclass):
        return self._get_initial_size(hostclass, 'desired_size') \
            == self._get_initial_size(hostclass, 'min_size')

    def _get_final_size(self, hostclass):
        return self._get_initial_size(hostclass=hostclass, size_type='expected_final_size')

    @mock_s3
    @patch("astroscaler.handler.AstroScaler")
    @patch("astroscaler.handler.os")
    def test_handler(self, mock_os, mock_astroscaler):
        """ Test an AstroScaler object is constructed correctly """
        mock_os.environ = {
            'astroscaler_global_filters': MOCK_ASTROSCALER_GLOBAL_FILTERS,
            'astroscaler_config_bucket': MOCK_S3_BUCKET_PREFIX + MOCK_ENVIRONMENT
        }
        mock_event = {}
        mock_api_key = b'mock_api_key'
        mock_app_key = b'mock_app_key'
        mock_spotinst_token = b'mock_spotinst_token'
        mock_global_filters = MOCK_GLOBAL_FILTERS

        s3_client = boto3.client('s3')

        bucket_name = mock_os.environ['astroscaler_config_bucket']
        s3_client.create_bucket(Bucket=bucket_name)
        s3_client.put_object(Bucket=bucket_name,
                             Key=S3_KEY_DATADOG_API_KEY,
                             Body=mock_api_key)
        s3_client.put_object(Bucket=bucket_name,
                             Key=S3_KEY_DATADOG_APP_KEY,
                             Body=mock_app_key)
        s3_client.put_object(Bucket=bucket_name,
                             Key=S3_KEY_SPOTINST_TOKEN,
                             Body=mock_spotinst_token)

        mock_astroscaler_obj = MagicMock()
        mock_astroscaler.return_value = mock_astroscaler_obj

        # Calling method under test
        handler(mock_event, MagicMock())

        # Begin verifications
        mock_astroscaler.assert_called_once_with(
            datadog_api_key=mock_api_key.decode('utf-8'),
            datadog_app_key=mock_app_key.decode('utf-8'),
            global_filters=mock_global_filters,
            spotinst_client=ANY
        )
        self.assertEqual(mock_spotinst_token, mock_astroscaler.call_args[1]['spotinst_client'].token)
        mock_astroscaler_obj.run.assert_called_once_with()

    @patch("astroscaler.handler.os")
    def test_handler_no_environment(self, mock_os):
        """ Test that AstroScaler raises error when environment is not found """
        mock_os.environ = {'astroscaler_config_bucket': MOCK_S3_BUCKET_PREFIX + MOCK_ENVIRONMENT}

        with self.assertRaises(RuntimeError):
            handler({}, MagicMock())

    @patch("astroscaler.handler.os")
    def test_handler_no_s3_bucket_prefix(self, mock_os):
        """ Test that AstroScaler raises error when S3 Bucket is not found """
        mock_os.environ = {'environment': MOCK_ENVIRONMENT}

        with self.assertRaises(RuntimeError):
            handler({}, MagicMock())

    @patch("datadog.api.Monitor.get_all")
    def test_badly_tagged_monitor(self, mock_datadog_get_monitors):
        """ Test that AstroScaler handles badly tagged monitor """
        bad_monitor = [
            {
                "overall_state": "Alert",
                "tags": [
                    "monitor_type:astroscaler",
                    "hostclass:bad",
                    "environment:%s" % MOCK_ENVIRONMENT
                ]
            }
        ]

        mock_datadog_get_monitors.return_value = bad_monitor

        policies = self.astroscaler._find_policies_for_scaling()

        self.assertEqual([], policies)

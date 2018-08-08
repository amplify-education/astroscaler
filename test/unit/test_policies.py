"""Module for testing our policies"""

from unittest import TestCase

from botocore.exceptions import ClientError
from mock import MagicMock

from astroscaler.policies import SelfPolicy, AWSPolicy


MOCK_ENVIRONMENT = "mock_env"


class TestAstroscalerPolicies(TestCase):
    """Class for testing Astroscaler policies"""

    def test_aws_policy_not_found(self):
        """ Test that AWS Policy fails safely if its underlying policy cannot be found """
        mock_client = MagicMock()
        mock_client.describe_policies.side_effect = IndexError

        mock_group = MagicMock()
        mock_group.name = 'test group'

        policy = AWSPolicy(
            name='test',
            client=mock_client,
            monitor_name='test monitor'
        )

        response = policy.should_execute(group=mock_group)

        self.assertFalse(response)

        mock_client.describe_policies.assert_called_once_with(
            AutoScalingGroupName=mock_group.name,
            PolicyNames=[policy.name]
        )

    def test_aws_policy_not_simple(self):
        """ Test that AWS Policy fails safely if its underlying policy is not simple """
        mock_client = MagicMock()
        mock_client.describe_policies.return_value = {
            "ScalingPolicies": [
                {
                    "PolicyType": "NotSimple",
                    "PolicyName": "A not so simple policy"
                }
            ]
        }

        mock_group = MagicMock()
        mock_group.name = 'test group'

        policy = AWSPolicy(
            name='test',
            client=mock_client,
            monitor_name='test monitor'
        )

        response = policy.should_execute(group=mock_group)

        self.assertFalse(response)

        mock_client.describe_policies.assert_called_once_with(
            AutoScalingGroupName=mock_group.name,
            PolicyNames=[policy.name]
        )

    def test_aws_policy_exact_adjustment(self):
        """ Test that AWS Policy fails safely if its tries to exactly adjust to the current size """
        mock_client = MagicMock()
        mock_client.describe_policies.return_value = {
            "ScalingPolicies": [
                {
                    "PolicyType": "SimpleScaling",
                    "PolicyName": "Change nothing",
                    "AdjustmentType": "ExactCapacity",
                    "ScalingAdjustment": 1
                }
            ]
        }

        mock_group = MagicMock()
        mock_group.name = 'test group'
        mock_group.desired_size = 1

        policy = AWSPolicy(
            name='test',
            client=mock_client,
            monitor_name='test monitor'
        )

        response = policy.should_execute(group=mock_group)

        self.assertFalse(response)

        mock_client.describe_policies.assert_called_once_with(
            AutoScalingGroupName=mock_group.name,
            PolicyNames=[policy.name]
        )

    def test_aws_policy_cannot_execute(self):
        """ Test that AWS Policy handles client errors """
        mock_client = MagicMock()
        mock_client.execute_policy.side_effect = ClientError(
            error_response={"Error": {}},
            operation_name=None
        )

        mock_group = MagicMock()
        mock_group.name = 'test group'

        policy = AWSPolicy(
            name='test',
            client=mock_client,
            monitor_name='test monitor'
        )

        policy.should_execute = MagicMock(return_value=True)

        response = policy.execute(groups=[mock_group])

        self.assertEqual(response, [])

        mock_client.execute_policy.assert_called_once_with(
            AutoScalingGroupName=mock_group.name,
            PolicyName=policy.name,
            HonorCooldown=True
        )

    def test_self_policy_fail_group_cooling_down(self):
        """ Test that Self Policy does not execute if group is cooling """
        policy = SelfPolicy(
            monitor_name='test monitor',
            adjustment="+5",
            cooldown=60
        )

        mock_group = MagicMock(max_size=10, min_size=1, desired_size=5)
        mock_group.is_cooling_down.return_value = True

        response = policy.should_execute(group=mock_group)

        self.assertFalse(response)

    def test_self_policy_handles_cannot_scale(self):
        """ Test that Self Policy does not explode if it cannot scale """
        policy = SelfPolicy(
            monitor_name='test monitor',
            adjustment="+5",
            cooldown=60
        )

        mock_group = MagicMock(max_size=10, min_size=1, desired_size=5)

        response = policy.execute(groups=[mock_group])

        self.assertFalse(response)

    def test_self_policy_handles_exact_adjustment(self):
        """ Test that Self Policy can scale to an exact number"""
        policy = SelfPolicy(
            monitor_name='test monitor',
            adjustment="7",
            cooldown=60
        )

        mock_group = MagicMock(max_size=10, min_size=1, desired_size=5)
        mock_group.is_cooling_down.return_value = False

        policy.execute(groups=[mock_group])

        mock_group.resize.assert_called_once_with(7)

    def test_self_policy_handles_add_exact(self):
        """ Test that Self Policy can scale with a positive integer"""
        policy = SelfPolicy(
            monitor_name='test monitor',
            adjustment="+2",
            cooldown=60
        )

        mock_group = MagicMock(max_size=10, min_size=1, desired_size=5)
        mock_group.is_cooling_down.return_value = False

        policy.execute(groups=[mock_group])

        mock_group.resize.assert_called_once_with(7)

    def test_self_policy_handles_sub_exact(self):
        """ Test that Self Policy can scale with a negative integer"""
        policy = SelfPolicy(
            monitor_name='test monitor',
            adjustment="-2",
            cooldown=60
        )

        mock_group = MagicMock(max_size=10, min_size=1, desired_size=5)
        mock_group.is_cooling_down.return_value = False

        policy.execute(groups=[mock_group])

        mock_group.resize.assert_called_once_with(3)

    def test_self_policy_handles_add_percent(self):
        """ Test that Self Policy can scale with a positive percentage"""
        policy = SelfPolicy(
            monitor_name='test monitor',
            adjustment="+20%",
            cooldown=60
        )

        mock_group = MagicMock(max_size=10, min_size=1, desired_size=5)
        mock_group.is_cooling_down.return_value = False

        policy.execute(groups=[mock_group])

        mock_group.resize.assert_called_once_with(6)

    def test_self_policy_handles_sub_percent(self):
        """ Test that Self Policy can scale with a negative percentage"""
        policy = SelfPolicy(
            monitor_name='test monitor',
            adjustment="-20%",
            cooldown=60
        )

        mock_group = MagicMock(max_size=10, min_size=1, desired_size=5)
        mock_group.is_cooling_down.return_value = False

        policy.execute(groups=[mock_group])

        mock_group.resize.assert_called_once_with(4)

    def test_self_policy_handles_exact_percent(self):
        """ Test that Self Policy can scale with an exact percentage"""
        policy = SelfPolicy(
            monitor_name='test monitor',
            adjustment="20%",
            cooldown=60
        )

        mock_group = MagicMock(max_size=10, min_size=1, desired_size=5)
        mock_group.is_cooling_down.return_value = False

        policy.execute(groups=[mock_group])

        mock_group.resize.assert_called_once_with(6)

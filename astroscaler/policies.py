"""Defines the policies understood by AstroScaler"""
import logging
import re
import math

from abc import ABCMeta, abstractmethod

from botocore.exceptions import ClientError

from astroscaler.resource_helper import throttled_call
from astroscaler.exceptions import GroupScaleException

logger = logging.getLogger(__name__)


class AstroScalerPolicy(object):
    """Abstract class defining policy objects for AstroScaler"""
    __metaclass__ = ABCMeta

    def __init__(self, monitor_name, filters=None):
        self.monitor_name = monitor_name
        self.filters = filters or {}

    # pylint: disable=unused-argument
    @abstractmethod
    def should_execute(self, group):
        """
        Determines whether or not this policy should be executed.
        :param group: The AstroScaler group affected by this policy.
        :return: True if the policy should be executed.
        """
        return

    # pylint: disable=unused-argument
    @abstractmethod
    def execute(self, groups):
        """
        Executes the policy against the provided groups
        :param groups: The AstroScaler groups against which the policy should be executed
        :return: The groups that were successfully scaled.
        """
        return

    def match(self, group):
        """
        Convenience function for checking whether a group is matched by the policy filters
        :param group: A group to match against the policy filters
        :return: True if the provided group satisfies all filters, false otherwise
        """
        metadata_items = group.metadata.viewitems()
        return all(filter_item in metadata_items for filter_item in self.filters.viewitems())


class AWSPolicy(AstroScalerPolicy):
    """Implementation of AstroScalerPolicy for AWS policies"""

    def __init__(self, name, client, monitor_name, filters=None):
        super(AWSPolicy, self).__init__(monitor_name, filters)
        self.name = name

        self._client = client

    def __repr__(self):
        """Returns a representation of this policy object"""
        return str(
            {
                "type": self.__class__.__name__,
                "name": self.name,
                "monitor_name": self.monitor_name,
                "filters": self.filters
            }
        )

    def should_execute(self, group):
        try:
            aws_policy = throttled_call(
                self._client.describe_policies,
                AutoScalingGroupName=group.name,
                PolicyNames=[self.name]
            )['ScalingPolicies'][0]
        except IndexError:
            logger.warning("Failed to find policy in %s ASG: %s", group.name, self.name)
            return False

        if aws_policy['PolicyType'] != 'SimpleScaling':
            logger.warning(
                "Non-SimpleScaling policy is being skipped: %s",
                {
                    'AutoScalingGroupName': group.name,
                    'PolicyName': aws_policy['PolicyName'],
                    'PolicyType': aws_policy['PolicyType']
                }
            )
            return False

        if aws_policy['AdjustmentType'] == 'ExactCapacity' and aws_policy['ScalingAdjustment'] == \
                group.desired_size:
            logger.warning(
                "Unable to execute policy (%s), group (%s) already at desired size of scaling policy",
                self, group
            )
            return False
        elif aws_policy['ScalingAdjustment'] > 0 and group.desired_size == group.max_size:
            logger.warning(
                "Unable to execute policy (%s), group (%s) already at maximum size",
                self, group
            )
            return False
        elif aws_policy['ScalingAdjustment'] < 0 and group.desired_size == group.min_size:
            logger.warning(
                "Unable to execute policy (%s), group (%s) already at minimum size",
                self, group
            )
            return False

        return True

    def execute(self, groups):
        scaled_groups = []

        for group in groups:
            if self.should_execute(group=group):

                try:
                    throttled_call(
                        self._client.execute_policy,
                        AutoScalingGroupName=group.name,
                        PolicyName=self.name,
                        HonorCooldown=True
                    )
                    scaled_groups.append(group)
                except ClientError:
                    logger.exception("Unable to scale group: %s", group)

        return scaled_groups


class SelfPolicy(AstroScalerPolicy):
    """Implementation of AstroScalerPolicy for policies managed by AstroScaler"""

    EXACT_NUM_REGEX = r'^([\d]+)$'
    ADD_INSTANCES_REGEX = r'^([\+-][\d]+)$'
    EXACT_PERCENTAGE_REGEX = r'^([\d]+)\%$'
    ADD_PERCENTAGE_REGEX = r'^([\+-][\d]+)\%$'

    def __init__(self, adjustment, cooldown, monitor_name, filters=None):
        super(SelfPolicy, self).__init__(monitor_name, filters)
        self.adjustment = adjustment
        self.cooldown = int(cooldown)

    def __repr__(self):
        """Returns a representation of this policy object"""
        return str(
            {
                "type": self.__class__.__name__,
                "adjustment": self.adjustment,
                "cooldown": self.cooldown,
                "monitor_name": self.monitor_name,
                "filters": self.filters
            }
        )

    def should_execute(self, group):
        new_desired_size = self._get_new_desired_size(group=group)
        new_bounded_desired_size = self._bound_new_size(
            new_size=new_desired_size,
            min_size=group.min_size,
            max_size=group.max_size
        )

        if new_bounded_desired_size == group.max_size == group.desired_size:
            logger.warning(
                "Unable to execute policy (%s), group (%s) already at maximum size",
                self, group
            )
            return False
        elif new_bounded_desired_size == group.min_size == group.desired_size:
            logger.warning(
                "Unable to execute policy (%s), group (%s) already at minimum size",
                self, group
            )
            return False
        elif new_bounded_desired_size == group.desired_size:
            logger.warning(
                "Unable to execute policy (%s), group (%s) already at desired size of scaling policy",
                self, group
            )
            return False
        elif group.is_cooling_down(self.cooldown):
            logger.warning(
                "Unable to execute policy (%s), group (%s) is cooling down",
                self, group
            )
            return False

        return True

    def execute(self, groups):
        scaled_groups = []

        for group in groups:
            try:
                if self.should_execute(group=group):
                    new_size = self._get_new_desired_size(group=group)
                    bounded_new_size = self._bound_new_size(
                        new_size=new_size,
                        min_size=group.min_size,
                        max_size=group.max_size
                    )

                    group.resize(bounded_new_size)
                    scaled_groups.append(group)
            except GroupScaleException:
                logger.exception("Unable to scale group: %s", group)

        return scaled_groups

    def _get_new_desired_size(self, group):
        """
        Convenience function for determining the new desired size of the given group.
        :param group: The AstroScaler group.
        :return: The new desired size of the provided group, according to this policy. The new size will be
        bounded by the group's min and max sizes.
        """
        exact_num_match = re.findall(self.EXACT_NUM_REGEX, self.adjustment)
        if exact_num_match:
            return int(exact_num_match[0])

        add_instances_match = re.findall(self.ADD_INSTANCES_REGEX, self.adjustment)
        if add_instances_match:
            return group.desired_size + int(add_instances_match[0])

        exact_percentage_match = re.findall(self.EXACT_PERCENTAGE_REGEX, self.adjustment)
        if exact_percentage_match:
            num_to_add = float(exact_percentage_match[0]) / 100 * group.desired_size
            return group.desired_size + int(math.ceil(num_to_add))

        add_percentage_match = re.findall(self.ADD_PERCENTAGE_REGEX, self.adjustment)
        if add_percentage_match:
            num_to_add = float(add_percentage_match[0]) / 100 * group.desired_size
            return math.copysign(math.ceil(abs(num_to_add)), num_to_add) + group.desired_size

    def _bound_new_size(self, new_size, min_size, max_size):
        """
        Convenience function for bounding a new size by a min and maximum.
        :param new_size: The new size.
        :param min_size: The lower bound.
        :param max_size: The upper bound.
        :return: New size, as an integer, bounded inclusively by min_size and max_size.
        """
        return int(max(min(math.ceil(new_size), max_size), min_size))

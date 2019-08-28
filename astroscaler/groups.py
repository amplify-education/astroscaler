"""Defines the various ASGs supported by AstroScaler"""
import logging

from abc import ABCMeta, abstractmethod
from datetime import datetime, timedelta

from dateutil.parser import parse
from dateutil.tz import tzutc
from botocore.exceptions import ClientError

from astroscaler.exceptions import GroupScaleException, SpotinstApiException
from astroscaler.resource_helper import (
    aws_tags_to_dict,
    spotinst_tags_to_dict,
    throttled_call,
    make_all_requests
)

logger = logging.getLogger(__name__)


class AstroScalerGroup(object):
    """Abstract class defining an ASG as understood by AstroScaler"""
    __metaclass__ = ABCMeta

    def __init__(self, provider_group, client, metadata):
        """
        Constructor.
        :param provider_group: Object representing provider's group.
        :param client: Client for communicating with provider.
        :param metadata: Metadata describing the group.
        """
        self.provider_group = provider_group
        self.client = client
        self.metadata = metadata

    def __repr__(self):
        """Returns a representation of this group"""
        return str(
            {
                "type": self.__class__.__name__,
                "name": self.name,
                "id": self.identifier,
                "min_size": self.min_size,
                "max_size": self.max_size,
                "desired_size": self.desired_size,
                "metadata": self.metadata
            }
        )

    # pylint: disable=unused-argument
    @abstractmethod
    def resize(self, new_size):
        """
        Convenience function for resizing a group to a new desired size.
        :param new_size: The new desired size of the group.
        :return: True if successful, false otherwise.
        """
        pass

    @abstractmethod
    def is_cooling_down(self, cooldown):
        """
        Determines whether or not the group was scaled too recently to be scaled again
        :param cooldown: The number of seconds that must have passed since the most recent scaling action.
        :return: True if the group has scaled within the cooldown period, false otherwise.
        """
        pass


class AWSGroup(AstroScalerGroup):
    """Implementation of AstroScalerGroup for AWS"""

    AWS_SCALING_CAUSES = [
        'changing the desired capacity',
        'Executing scheduled action'
    ]

    def __init__(self, provider_group, client):
        super(AWSGroup, self).__init__(provider_group, client, aws_tags_to_dict(provider_group.get('Tags')))

        self.name = self.provider_group.get('AutoScalingGroupName')
        self.identifier = self.provider_group.get('AutoScalingGroupARN')
        self.min_size = int(self.provider_group.get('MinSize'))
        self.desired_size = int(self.provider_group.get('DesiredCapacity'))
        self.max_size = int(self.provider_group.get('MaxSize'))

        self._client = client

    def resize(self, new_size):
        try:
            throttled_call(
                self._client.set_desired_capacity,
                AutoScalingGroupName=self.name,
                DesiredCapacity=new_size
            )
        except ClientError:
            logger.exception("Unable to resize group: %s", self)
            raise GroupScaleException("Unable to resize group: {0}".format(self))

    def is_cooling_down(self, cooldown):
        try:
            activities = make_all_requests(
                self._client.describe_scaling_activities,
                "Activities",
                AutoScalingGroupName=self.name
            )
        except ClientError:
            logger.exception("Unable to resize group: %s", self)
            raise GroupScaleException("Unable to resize group: {0}".format(self))

        scaling_activities = [
            activity for activity in activities
            if any(reason in activity['Cause'] for reason in self.AWS_SCALING_CAUSES)
        ]

        most_recent_scaling_event = scaling_activities[0] if scaling_activities else None
        if not most_recent_scaling_event:
            return False

        most_recent_scaling_time = most_recent_scaling_event.get('EndTime')
        if not most_recent_scaling_time:
            logger.warning("Scaling activity still ongoing, cannot scale group: %s", self)
            return True

        most_recent_allowed_scaling_time = most_recent_scaling_time + timedelta(seconds=cooldown)
        current_time = datetime.now(most_recent_scaling_time.tzinfo)
        if current_time <= most_recent_allowed_scaling_time:
            logger.warning(
                "Cooldown has not elapsed (%s seconds remaining), cannot scale group: %s",
                (most_recent_allowed_scaling_time - current_time).seconds,
                self,
            )
            return True

        return False


class SpotinstGroup(AstroScalerGroup):
    """Implementation of AstroScalerGroup for Spotinst"""

    SPOTINST_SCALING_CAUSES = [
        'Scale',
        'Updating',
        'have been launched',
        'have been detacted',
        'successfully created',
    ]

    def __init__(self, provider_group, client):
        metadata = spotinst_tags_to_dict(
            provider_group.get('compute', {}).get('launchSpecification', {}).get('tags', {}))
        super(SpotinstGroup, self).__init__(provider_group, client, metadata)

        self.name = self.provider_group.get('name')
        self.identifier = self.provider_group.get('id')
        self.min_size = int(self.provider_group.get('capacity').get('minimum'))
        self.desired_size = int(self.provider_group.get('capacity').get('target'))
        self.max_size = int(self.provider_group.get('capacity').get('maximum'))

        self._client = client

    def is_cooling_down(self, cooldown):
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        # Spotinst expects the timestamps to come as milliseconds, not seconds, so add some extra zeros
        from_date = int(one_hour_ago.strftime("%s")) * 1000
        to_date = int(now.strftime("%s")) * 1000

        try:
            events = self.client.get_group_events(
                group_id=self.identifier,
                from_date=from_date,
                to_date=to_date,
            )
        except SpotinstApiException:
            logger.exception("Unable to resize group: %s", self)
            raise GroupScaleException("Unable to resize group: {0}".format(self))

        event = next(
            (
                event
                for event in events
                if any(reason in event['message'] for reason in self.SPOTINST_SCALING_CAUSES)
            ),
            None
        )

        if not event:
            return False

        most_recent_scaling_time = parse(event['createdAt'])
        most_recent_allowed_scaling_time = most_recent_scaling_time + timedelta(seconds=cooldown)
        current_time = datetime.now(tzutc())
        if current_time <= most_recent_allowed_scaling_time:
            logger.warning(
                "Cooldown has not elapsed (%s seconds remaining), cannot scale group: %s",
                (most_recent_allowed_scaling_time - current_time).seconds,
                self,
            )
            return True

        return False

    def resize(self, new_size):
        try:
            if new_size > self.desired_size:
                self.client.scale_up(group_id=self.identifier, adjustment=new_size - self.desired_size)

            elif new_size < self.desired_size:
                self.client.scale_down(group_id=self.identifier, adjustment=self.desired_size - new_size)

        except SpotinstApiException:
            logger.exception("Unable to resize group: %s", self)
            raise GroupScaleException("Unable to resize group: {0}".format(self))

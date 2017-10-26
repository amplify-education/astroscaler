"""
Implementation of the astroscaler Lambda function, which executes Asiaq's default
autoscaling policies based on each hostclass's datadog monitors.
"""

from __future__ import print_function

import logging
import os
import sys

from logging.config import fileConfig

here = os.path.dirname(os.path.realpath(__file__))

# Adding the 'dependencies' directory to the Python import path
sys.path.append(os.path.join(here, "../"))
sys.path.append(os.path.join(here, "../dependencies"))

# Setup logging
fileConfig(os.path.join(here, "../logging.ini"))
logger = logging.getLogger(__name__)

import json
import boto3

from botocore.exceptions import ClientError
from datadog import initialize, api

from astroscaler.resource_helper import (
    make_all_requests,
    monitor_tags_to_dict
)

from astroscaler.policies import AWSPolicy, SelfPolicy
from astroscaler.groups import AWSGroup, SpotinstGroup
from astroscaler.exceptions import GroupScaleException, SpotinstApiException
from astroscaler.spotinst_client import SpotinstClient

S3_KEY_DATADOG_API_KEY = "app_auth/datadog/api_key"
S3_KEY_DATADOG_APP_KEY = "app_auth/datadog/astroscaler_app_key"
S3_KEY_SPOTINST_TOKEN = "spotinst/temp_access_token"


class AstroScaler(object):
    """
    Implements querying triggered datadog monitors and executing policies on autoscaling
    groups that need to be scaled.
    """

    def __init__(self, datadog_api_key, datadog_app_key,
                 global_filters=None, aws_client=None, spotinst_client=None):
        self.monitor_type = "astroscaler"
        self.global_filters = global_filters

        options = {
            'api_key': datadog_api_key,
            'app_key': datadog_app_key
        }

        # initialize datadog api
        initialize(**options)

        self._aws_client = aws_client
        self._spotinst_client = spotinst_client

    @property
    def aws_client(self):
        """ Lazily creates boto3 Autoscaling Connection """
        if not self._aws_client:
            self._aws_client = boto3.client('autoscaling')
        return self._aws_client

    @property
    def spotinst_client(self):
        """ Lazily creates spotinst client """
        if not self._spotinst_client:
            self._spotinst_client = SpotinstClient()
        return self._spotinst_client

    def run(self):
        """ Starts the astroscaler process """
        policies = self._find_policies_for_scaling()
        logger.info("Policies whose monitors have been triggered: %s", policies)

        groups = self._find_groups()

        policies_to_groups = self._map_policies_to_groups(policies, groups)

        return self._execute_policies(policies_to_groups)

    def _execute_policies(self, policies_to_groups):
        executed_policies = []

        for policy, groups in policies_to_groups.iteritems():

            try:
                scaled_groups = policy.execute(groups=groups)
                if scaled_groups:
                    executed_policies.append(policy)
                else:
                    logger.warning("Policy should have executed, but no groups scaled: %s", policy)
            except GroupScaleException:
                logger.exception("Unable to execute policy: %s", policy)

        return executed_policies

    def _find_groups(self):
        """
        Finds all groups from all providers that AstroScaler is aware of.
        :return: AstroScaler group objects representing provider ASGs.
        """
        groups = []

        try:
            groups += [
                AWSGroup(provider_group=asg, client=self.aws_client)
                for asg in make_all_requests(
                    self.aws_client.describe_auto_scaling_groups,
                    'AutoScalingGroups'
                )
            ]
        except ClientError:
            logger.exception("Unable to find any AWS groups.")

        try:
            groups += [
                SpotinstGroup(provider_group=elastigroup, client=self.spotinst_client)
                for elastigroup in self.spotinst_client.get_groups()
            ]
        except SpotinstApiException:
            logger.exception("Unable to find any Spotinst Elastigroups.")

        return groups

    def _find_policies_for_scaling(self):
        """
        Queries all the datadog autoscale monitors that have been triggered.
        Returns a dictionary, keyed by hostclass names, of dictionaries containing the policy name or
        the cooldown and adjustment that should be used. Also contains a type entry, which indicates
        whether the ASG policy is managed by AWS or astroscaler.
        """
        # Because Datadog API treats multiple tags as ORs, not ANDs, we are using only monitor_type
        # as the filtering tag here and then filter the results additionally later.
        monitor_tags = ['monitor_type:{0}'.format(self.monitor_type)]
        results = api.Monitor.get_all(monitor_tags=monitor_tags)

        policies = []
        for monitor in results:
            # We are only interested in monitors that are alerting...
            if monitor.get('overall_state') != 'Alert':
                continue

            monitor_tags = monitor_tags_to_dict(monitor.get('tags'))

            if not all(filter_item in monitor_tags.viewitems()
                       for filter_item in self.global_filters.viewitems()):
                continue

            astroscaler_group_tags = monitor_tags.get(
                "astroscaler_group_tags",
                "environment,hostclass"
            )

            desired_keys = astroscaler_group_tags.split(",")

            filters = {
                key: value
                for key, value in monitor_tags.iteritems()
                if key in desired_keys
            }

            policy_name = monitor_tags.get("policy_name")
            policy_adjustment = monitor_tags.get("policy_adjustment")
            policy_cooldown = monitor_tags.get("policy_cooldown", 600)

            # Create the policy object depending on the presence of tags
            if all(tag is not None for tag in [policy_adjustment, policy_cooldown]):
                policy = SelfPolicy(
                    monitor_name=monitor.get('name'),
                    adjustment=policy_adjustment,
                    cooldown=policy_cooldown,
                    filters=filters
                )
            elif all(tag is not None for tag in [policy_name]):
                policy = AWSPolicy(
                    monitor_name=monitor.get('name'),
                    name=policy_name,
                    filters=filters,
                    client=self.aws_client
                )
            else:
                logger.warning(
                    "Monitor (id: %s) is missing at least one of the required tags: "
                    "hostclass, policy_name or hostclass, policy_adjustment, and policy_cooldown",
                    monitor.get('id')
                )
                continue

            policies.append(policy)

        return policies

    def _map_policies_to_groups(self, policies, groups):
        """
        Convenience function for mapping policies to groups they affect
        :param policies: List of AstroScaler policies.
        :param groups: List of AstroScaler groups.
        :return: Mapping of policies to groups they affect.
        """
        return {
            policy: [group for group in groups if policy.match(group)]
            for policy in policies
        }


def _get_environment_variables():
    env_variables = ['astroscaler_global_filters', 'astroscaler_config_bucket']

    try:
        return {variable: os.environ[variable]
                for variable in env_variables}
    except KeyError as exc:
        raise RuntimeError("Unable to obtain {0} from environment variables.".format(exc.args[0]))


# pylint: disable=unused-argument
def handler(event, context):
    """ Handler function of the Lambda function """

    environ = _get_environment_variables()
    bucket_name = environ['astroscaler_config_bucket']
    s3_client = boto3.client('s3')

    try:
        datadog_api_key = s3_client.get_object(
            Bucket=bucket_name,
            Key=S3_KEY_DATADOG_API_KEY
        )["Body"].read()

        datadog_app_key = s3_client.get_object(
            Bucket=bucket_name,
            Key=S3_KEY_DATADOG_APP_KEY
        )["Body"].read()

    except ClientError as exc:
        if exc.response['Error'].get('Code') == 'NoSuchBucket':
            logger.error("There is no such S3 bucket: %s ", bucket_name)
            sys.exit(1)
        elif exc.response['Error'].get('Code') == 'NoSuchKey':
            logger.error("There is no such key in the %s S3 bucket: %s",
                         bucket_name, exc.response['Error'].get('Key'))
            sys.exit(1)

        raise

    global_filters = monitor_tags_to_dict(environ['astroscaler_global_filters'].split(","))

    spotinst_token = None
    try:
        spotinst_token = s3_client.get_object(
            Bucket=bucket_name,
            Key=S3_KEY_SPOTINST_TOKEN
        )["Body"].read()
    except ClientError:
        logger.exception("Could not locate Spotinst token")

    astroscaler = AstroScaler(
        datadog_api_key=datadog_api_key,
        datadog_app_key=datadog_app_key,
        spotinst_client=SpotinstClient(token=spotinst_token),
        global_filters=global_filters
    )
    policies_executed = astroscaler.run()

    body = {
        "message": "AstroScaler has executed these policies: {0}".format(policies_executed),
        "input": event
    }

    response = {
        "statusCode": 200,
        "body": json.dumps(body)
    }

    return response

"""
This module has a bunch of functions that helps with using boto functions
"""
import logging
import time

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

MAX_POLL_INTERVAL = 60  # seconds


def throttled_call(fun, *args, **kwargs):
    """
    Execute function fun with args and kwargs until it does
    not throw a throttled exception or 5 minutes have passed.

    After each failed attempt a delay is introduced of an
    increasing number seconds following the fibonacci series
    (up to MAX_POLL_INTERVAL seconds).
    """
    max_time = 5 * 60
    last_delay = 0
    curr_delay = 1
    expire_time = time.time() + max_time
    while True:
        try:
            return fun(*args, **kwargs)
        except ClientError as err:
            if logging.getLogger().level == logging.DEBUG:
                logger.exception("Failed to run %s.", fun)

            error_code = err.response['Error'].get('Code', 'Unknown')

            if (error_code not in ("Throttling", "RequestLimitExceeded")) or (time.time() > expire_time):
                raise

            time.sleep(curr_delay)
            delay_register = last_delay
            last_delay = curr_delay
            curr_delay = min(curr_delay + delay_register, MAX_POLL_INTERVAL)


def aws_tags_to_dict(tags):
    """ Converts a list of AWS tag dicts to a single dict with corresponding keys and values """
    return {tag.get('Key'): tag.get('Value') for tag in tags or {}}


def spotinst_tags_to_dict(tags):
    """ Converts a list of Spotinst tag dicts to a single dict with corresponding keys and values """
    return {tag.get('tagKey'): tag.get('tagValue') for tag in tags or {}}


def make_all_requests(func, top_level_key, *args, **kwargs):
    """Helper method for automatically making multiple boto requests for their listing functions"""
    response = throttled_call(func, *args, **kwargs)
    response_items = response[top_level_key]

    while response.get('NextToken'):
        response = throttled_call(func, NextToken=response['NextToken'], *args, **kwargs)
        response_items += response[top_level_key]

    return response_items


def monitor_tags_to_dict(monitor_tags):
    """Convenience function for converting datadog monitors tags to a dictionary"""
    return dict(entry.split(':', 1) for entry in monitor_tags or [])

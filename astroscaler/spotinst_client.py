"""Handles communicating with spotinst"""

import logging

from requests import Session

from astroscaler.exceptions import SpotinstApiException


logger = logging.getLogger(__name__)

SPOTINST_API_HOST = 'https://api.spotinst.io'


class SpotinstClient(object):
    """Class for handling communication with Spotinst"""

    def __init__(self, token=None, session=None):
        self.token = token
        self._session = session

    @property
    def session(self):
        """ The Requests Session object for interacting with the Spotinst API"""
        if not self._session:

            session = Session()
            session.headers.update(
                {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer {0}".format(self.token)
                }
            )
            self._session = session

        return self._session

    def get_groups(self):
        """ Function for getting all existing Spotinst groups """
        response = self._make_request(
            method='get',
            path='aws/ec2/group'
        )

        return response['response']['items']

    def scale_up(self, group_id, adjustment):
        """
        Scales up the given group by the given adjustment.
        :param group_id: The Spotinst group id to scale.
        :param adjustment: How many instances to add to the group.
        :return: None.
        """
        self._make_request(
            method='put',
            path='aws/ec2/group/{0}/scale/up'.format(group_id),
            params={"adjustment": adjustment}
        )

    def scale_down(self, group_id, adjustment):
        """
        Scales down the given group by the given adjustment.
        :param group_id: The Spotinst group id to scale.
        :param adjustment: How many instances to add to the group.
        :return: None.
        """
        self._make_request(
            method='put',
            path='aws/ec2/group/{0}/scale/down'.format(group_id),
            params={"adjustment": adjustment}
        )

    def get_group_events(self, group_id, from_date, to_date):
        """
        Returns any group events for the given group.
        :param group_id: The Spotinst group id.
        :param from_date: Only events from this timestamp forward will be returned.
        :param to_date: Only events from this timestamp backward will be returned.
        :return: List of events.
        """
        response = self._make_request(
            method='get',
            path='aws/ec2/group/{0}/logs'.format(group_id),
            params={
                "fromDate": from_date,
                "toDate": to_date,
                "limit": 1000,
            }
        )

        return response['response']['items']

    def _make_request(self, method, path, params=None, data=None):
        """
        Convenience function for making requests to the Spotinst API.

        :param method: What HTTP method to use.
        :param path: The API endpoint to call. IE: aws/ec2/group
        :param params: Dictionary of query parameters.
        :param data: Body data.
        :return: The response from the Spotinst API.
        """
        response = self.session.request(
            method=method,
            url='{0}/{1}'.format(SPOTINST_API_HOST, path),
            params=params,
            data=data
        )

        try:
            json = response.json()
        except ValueError:
            raise SpotinstApiException("Spotinst API did not return JSON response: {0}".format(response.text))

        if response.status_code == 401:
            raise SpotinstApiException("Provided Spotinst API token is not valid")

        if response.status_code != 200:
            raise SpotinstApiException("Unknown Spotinst API error encountered: {0}".format(
                json['response']['status'])
            )

        return json

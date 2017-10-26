"""Module for testing our Spotinst client"""

from unittest import TestCase

from mock import MagicMock, patch

from astroscaler.exceptions import SpotinstApiException
from astroscaler.spotinst_client import SpotinstClient, SPOTINST_API_HOST


class TestSpotinstClient(TestCase):
    """Class for testing Spotinst Client"""

    def setUp(self):
        """Pretest setup"""
        self.session = MagicMock()
        self.spotinst_client = SpotinstClient(session=self.session)

    @patch('astroscaler.spotinst_client.Session')
    def test_session_created_if_not_provided(self, mock_session_constructor):
        """Test client creates a session if one is not provided"""
        spotinst_client = SpotinstClient(token="MOCK")

        # Access the property
        session = spotinst_client.session

        mock_session_constructor.assert_called_once_with()

        session.headers.update.assert_called_once_with({
            "Content-Type": "application/json",
            "Authorization": "Bearer {0}".format(spotinst_client.token)
        })

    def test_get_groups_correct_request(self):
        """Test client makes correct request for getting groups"""
        self.spotinst_client._make_request = MagicMock(return_value={"response": {"items": []}})

        groups = self.spotinst_client.get_groups()

        self.assertEqual([], groups)

        self.spotinst_client._make_request.assert_called_once_with(method='get', path='aws/ec2/group')

    def test_scale_up_correct_request(self):
        """Test client makes correct request for scale up"""
        self.spotinst_client._make_request = MagicMock(return_value={"response": {"items": []}})

        self.spotinst_client.scale_up(group_id="foo", adjustment="bar")

        self.spotinst_client._make_request.assert_called_once_with(
            method='put',
            path='aws/ec2/group/foo/scale/up',
            params={'adjustment': 'bar'}
        )

    def test_scale_down_correct_request(self):
        """Test client makes correct request for scale down"""
        self.spotinst_client._make_request = MagicMock(return_value={"response": {"items": []}})

        self.spotinst_client.scale_down(group_id="foo", adjustment="bar")

        self.spotinst_client._make_request.assert_called_once_with(
            method='put',
            path='aws/ec2/group/foo/scale/down',
            params={'adjustment': 'bar'}
        )

    def test_get_group_events_correct_request(self):
        """Test client makes correct request for getting group events"""
        self.spotinst_client._make_request = MagicMock(return_value={"response": {"items": []}})

        self.spotinst_client.get_group_events(group_id="foo", from_date="bar")

        self.spotinst_client._make_request.assert_called_once_with(
            method='get',
            path='aws/ec2/group/foo/events',
            params={'fromDate': 'bar'}
        )

    def test_make_request_helper_happy_path(self):
        """Test make request helper happy path"""
        mock_response = MagicMock(status_code=200, json=MagicMock(return_value={}))
        self.session.request = MagicMock(return_value=mock_response)

        actual_json = self.spotinst_client._make_request(method="get", path="fake_path", data=[], params=[])

        self.assertEqual({}, actual_json)
        self.session.request.assert_called_once_with(
            method="get",
            url='%s/fake_path' % SPOTINST_API_HOST,
            data=[],
            params=[]
        )

    def test_make_request_exception_no_json(self):
        """Test make request helper throws exception if no JSON"""
        mock_response = MagicMock(status_code=200, json=MagicMock(side_effect=ValueError))
        self.session.request = MagicMock(return_value=mock_response)

        self.assertRaises(
            SpotinstApiException,
            self.spotinst_client._make_request,
            method="get",
            path="fake_path"
        )

    def test_make_request_exception_unauthorized(self):
        """Test make request helper throws exception if unauthorized"""
        mock_response = MagicMock(status_code=401, json=MagicMock(return_value={}))
        self.session.request = MagicMock(return_value=mock_response)

        self.assertRaises(
            SpotinstApiException,
            self.spotinst_client._make_request,
            method="get",
            path="fake_path"
        )

    def test_make_request_exception_not_200(self):
        """Test make request helper throws exception if status code isnt 200"""
        response_json = {'response': {'status': 'FAKE'}}
        mock_response = MagicMock(status_code=418, json=MagicMock(return_value=response_json))
        self.session.request = MagicMock(return_value=mock_response)

        self.assertRaises(
            SpotinstApiException,
            self.spotinst_client._make_request,
            method="get",
            path="fake_path"
        )

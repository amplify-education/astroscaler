"""Class for storing exceptions for AstroScaler"""


class GroupScaleException(Exception):
    """Raised when a group could not be scaled"""


class SpotinstApiException(Exception):
    """Raised if Spotinst API problem encountered"""

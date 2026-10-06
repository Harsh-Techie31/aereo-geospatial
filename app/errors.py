class GeoFileError(Exception):
    """Base class for errors caused by the uploaded file."""
    status_code = 400


class UnsupportedFileError(GeoFileError):
    """Wrong extension / type of file."""
    status_code = 415


class InvalidFileError(GeoFileError):
    """Right type of file, but it cannot be read or is unsafe."""
    status_code = 422


class FileTooLargeError(GeoFileError):
    status_code = 413

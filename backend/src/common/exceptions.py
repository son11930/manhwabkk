class DomainException(Exception):
    """Base exception for domain-specific errors."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

class NotFoundError(DomainException):
    def __init__(self, entity_name: str, entity_id: str):
        super().__init__(f"{entity_name} with id/slug '{entity_id}' not found.", status_code=404)

class UnauthorizedError(DomainException):
    def __init__(self, message: str = "Authentication credentials were not provided or are invalid."):
        super().__init__(message, status_code=401)

class ForbiddenError(DomainException):
    def __init__(self, message: str = "You do not have permission to perform this action. Super Admin rights required."):
        super().__init__(message, status_code=403)

class ValidationError(DomainException):
    def __init__(self, message: str):
        super().__init__(message, status_code=422)

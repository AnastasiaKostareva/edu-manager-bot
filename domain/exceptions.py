class DomainException(Exception):
    pass


class UserNotFoundException(DomainException):
    pass


class UserAlreadyExistsException(DomainException):
    pass


class LessonNotFoundException(DomainException):
    pass


class ChatNotFoundException(DomainException):
    pass


class ReminderNotFoundException(DomainException):
    pass


class InvalidRoleException(DomainException):
    pass


class PermissionDeniedException(DomainException):
    pass


class ValidationException(DomainException):
    pass
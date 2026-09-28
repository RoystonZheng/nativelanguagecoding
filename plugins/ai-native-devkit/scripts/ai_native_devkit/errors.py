"""Stable runtime errors exposed by the versioned JSON CLI."""


class AiNativeDevError(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ContractError(AiNativeDevError):
    def __init__(self, message, code="rejected.contract"):
        super().__init__(code, message, retryable=False)


class RequirementDocumentError(AiNativeDevError):
    pass


class RequirementApprovalError(AiNativeDevError):
    pass


class StoreError(AiNativeDevError):
    pass


class RepositoryError(AiNativeDevError):
    def __init__(self, code, message, retryable=False, observation=None, details=None):
        super().__init__(code, message, retryable=retryable)
        self.observation = observation
        self.details = details

from __future__ import annotations


class DocumentServiceError(RuntimeError):
    """Base class for safe document-service failures."""

    code = "document_error"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.safe_message = message
        self.code = code or type(self).code
        self.status_code = status_code or type(self).status_code


class DocumentValidationError(DocumentServiceError):
    code = "invalid_document"
    status_code = 422


class DocumentExtractionError(DocumentServiceError):
    code = "extraction_failed"
    status_code = 422


class DocumentStorageError(DocumentServiceError):
    code = "storage_failed"


class DocumentProcessingError(DocumentServiceError):
    code = "processing_failed"


class EmbeddingProviderError(DocumentServiceError):
    code = "embedding_failed"
    status_code = 502

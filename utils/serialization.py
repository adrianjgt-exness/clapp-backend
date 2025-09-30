from datetime import datetime
from typing import Any, TypeVar, overload

from bson import ObjectId

T = TypeVar("T")


@overload
def serialize_document(doc: dict[str, Any]) -> dict[str, Any]: ...


@overload
def serialize_document(doc: list[Any]) -> list[Any]: ...


@overload
def serialize_document(doc: T) -> T: ...


def serialize_document(doc: T) -> T:
    """
    Recursively converts MongoDB documents to JSON-serializable formats.
    Converts ObjectId and datetime objects to strings.
    Provides precise type hints for static analysis.
    """
    if isinstance(doc, list):
        return [serialize_document(item) for item in doc]  # type: ignore

    if isinstance(doc, dict):
        serialized = {}
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                if key == "_id":
                    serialized["id"] = str(value)
                else:
                    serialized[key] = str(value)
            elif isinstance(value, datetime):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = serialize_document(value)
        return serialized  # type: ignore

    return doc

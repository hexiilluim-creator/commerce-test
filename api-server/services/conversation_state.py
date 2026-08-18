"""Abstraction robuste pour mutations de conversation_state.

Objectifs:
- centraliser les mutations JSON de conversation_state
- marquer automatiquement le champ comme dirty pour SQLAlchemy
- éviter les write-back manuels répétitifs
- supporter aussi les mutations imbriquées (dict/list)
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, MutableMapping
from typing import Any

from sqlalchemy.orm.attributes import flag_modified


class _DirtyList(list):
    def __init__(self, values: Iterable[Any], on_dirty):
        self._on_dirty = on_dirty
        super().__init__(self._wrap(v) for v in values)

    def _wrap(self, value: Any) -> Any:
        return _wrap_nested(value, self._on_dirty)

    def append(self, value: Any) -> None:
        super().append(self._wrap(value))
        self._on_dirty()

    def extend(self, values: Iterable[Any]) -> None:
        super().extend(self._wrap(v) for v in values)
        self._on_dirty()

    def insert(self, index: int, value: Any) -> None:
        super().insert(index, self._wrap(value))
        self._on_dirty()

    def pop(self, index: int = -1) -> Any:
        value = super().pop(index)
        self._on_dirty()
        return value

    def remove(self, value: Any) -> None:
        super().remove(value)
        self._on_dirty()

    def clear(self) -> None:
        if self:
            super().clear()
            self._on_dirty()

    def sort(self, *args, **kwargs) -> None:
        super().sort(*args, **kwargs)
        self._on_dirty()

    def reverse(self) -> None:
        super().reverse()
        self._on_dirty()

    def __setitem__(self, index, value) -> None:
        if isinstance(index, slice):
            super().__setitem__(index, [self._wrap(v) for v in value])
        else:
            super().__setitem__(index, self._wrap(value))
        self._on_dirty()

    def __delitem__(self, index) -> None:
        super().__delitem__(index)
        self._on_dirty()


class _DirtyDict(dict):
    def __init__(self, values: dict[str, Any], on_dirty):
        self._on_dirty = on_dirty
        super().__init__((k, self._wrap(v)) for k, v in values.items())

    def _wrap(self, value: Any) -> Any:
        return _wrap_nested(value, self._on_dirty)

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, self._wrap(value))
        self._on_dirty()

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        self._on_dirty()

    def clear(self) -> None:
        if self:
            super().clear()
            self._on_dirty()

    def pop(self, key: str, default: Any = None) -> Any:
        if key in self:
            value = super().pop(key)
            self._on_dirty()
            return value
        return default

    def popitem(self):
        item = super().popitem()
        self._on_dirty()
        return item

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key in self:
            return super().__getitem__(key)
        value = self._wrap(default)
        super().__setitem__(key, value)
        self._on_dirty()
        return value

    def update(self, other=None, /, **kwargs) -> None:
        items: dict[str, Any] = {}
        if other:
            if isinstance(other, dict):
                items.update(other)
            else:
                items.update(dict(other))
        if kwargs:
            items.update(kwargs)
        if not items:
            return
        for key, value in items.items():
            super().__setitem__(key, self._wrap(value))
        self._on_dirty()


def _wrap_nested(value: Any, on_dirty):
    if isinstance(value, _DirtyDict) or isinstance(value, _DirtyList):
        return value
    if isinstance(value, dict):
        return _DirtyDict(value, on_dirty)
    if isinstance(value, list):
        return _DirtyList(value, on_dirty)
    return value


def _to_plain(value: Any) -> Any:
    if isinstance(value, _DirtyDict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, _DirtyList):
        return [_to_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    return value


class ConversationState(MutableMapping[str, Any]):
    """Wrapper mutable pour customer.conversation_state avec dirty-tracking auto."""

    def __init__(self, customer: Any, raw_state: object | None = None, field_name: str = "conversation_state"):
        self._customer = customer
        self._field_name = field_name
        source = raw_state if raw_state is not None else getattr(customer, field_name, None)
        base = source if isinstance(source, dict) else {}
        self._dirty = False
        self._data = _DirtyDict(base, self._mark_dirty)
        if not isinstance(source, dict):
            self._mark_dirty()

    @classmethod
    def from_customer(cls, customer: Any) -> ConversationState:
        return cls(customer)

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def _mark_dirty(self) -> None:
        self._dirty = True
        plain = self.snapshot()
        setattr(self._customer, self._field_name, plain)
        try:
            flag_modified(self._customer, self._field_name)
        except Exception:
            # Objet non mappé / fake customer de test: l'assignation ci-dessus suffit.
            pass

    def snapshot(self) -> dict[str, Any]:
        return _to_plain(self._data)

    def sync(self) -> dict[str, Any]:
        if self._dirty:
            self._mark_dirty()
        return getattr(self._customer, self._field_name)

    def replace(self, new_state: dict[str, Any] | None) -> None:
        self._data.clear()
        if new_state:
            self._data.update(new_state)
        self._mark_dirty()

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:  # type: ignore[override]
        self._data.clear()

    def pop(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return self._data.pop(key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return self._data.setdefault(key, default)

    def update(self, other=None, /, **kwargs) -> None:  # type: ignore[override]
        self._data.update(other, **kwargs)

    def __repr__(self) -> str:
        return f"ConversationState({self.snapshot()!r}, dirty={self._dirty})"

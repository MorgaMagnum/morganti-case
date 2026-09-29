"""Decoder for the `devalue` format used by Nuxt 3 SSR payloads.

The payload is a flat array; containers hold indices into that array. Some
entries are tagged tuples like ["Reactive", idx] or ["Date", "iso"].
"""

from typing import Any

_WRAPPERS = {"ShallowReactive", "Reactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef", "NuxtError", "Island"}


def unflatten(values: list) -> Any:
    cache: dict[int, Any] = {}

    def hydrate(index: Any) -> Any:
        if not isinstance(index, int) or index < 0:
            return None  # negative indices encode undefined / holes / NaN
        if index in cache:
            return cache[index]
        value = values[index]
        if isinstance(value, list):
            tag = value[0] if value and isinstance(value[0], str) else None
            if tag in _WRAPPERS:
                out = hydrate(value[1]) if len(value) > 1 else None
            elif tag == "Date":
                out = value[1]
            elif tag == "Set":
                out = [hydrate(x) for x in value[1:]]
            elif tag == "Map":
                out = {str(hydrate(value[i])): hydrate(value[i + 1]) for i in range(1, len(value) - 1, 2)}
            else:
                lst: list = []
                cache[index] = lst
                lst.extend(hydrate(x) for x in value)
                return lst
        elif isinstance(value, dict):
            obj: dict = {}
            cache[index] = obj
            for key, sub in value.items():
                obj[key] = hydrate(sub)
            return obj
        else:
            out = value
        cache[index] = out
        return out

    return hydrate(0)

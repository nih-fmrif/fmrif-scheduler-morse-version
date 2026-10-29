from inspect import isclass
from typing import get_origin

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapped, configure_mappers

from scheduler import model


def _mapped_model_classes():
    for value in vars(model).values():
        if not isclass(value):
            continue
        if value is model.Model or not issubclass(value, model.Model):
            continue
        if getattr(value, "__tablename__", None) is None:
            continue
        yield value


def test_models_use_explicit_mapped_annotations():
    assert getattr(model.Model, "__allow_unmapped__", None) is not True

    configure_mappers()

    for mapped_class in _mapped_model_classes():
        hints = getattr(mapped_class, "__annotations__", {})

        for attr_name in sa_inspect(mapped_class).attrs.keys():
            assert attr_name in hints, (
                f"{mapped_class.__name__}.{attr_name} is missing an explicit annotation"
            )
            assert get_origin(hints[attr_name]) is Mapped, (
                f"{mapped_class.__name__}.{attr_name} should use Mapped[...]"
            )

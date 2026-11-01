"""Shared test doubles for the tax test-suite (no database needed)."""
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import count
from typing import List

D = Decimal
_pk = count(1)


class FakeChildren:
    """Stand-in for the `Tax.children` / `line.taxes` related managers."""
    def __init__(self, items=()):
        self._items = list(items)

    def all(self):
        return self

    def filter(self, **kwargs):
        return FakeChildren(i for i in self._items
                            if all(getattr(i, k) == v for k, v in kwargs.items()))

    def order_by(self, *fields):
        fields = [f for f in fields if f != 'id']
        return FakeChildren(sorted(self._items, key=lambda i: tuple(getattr(i, f) for f in fields) + (i.pk,)))

    def exists(self):
        return bool(self._items)

    def __iter__(self):
        return iter(self._items)


@dataclass(eq=False)
class FakeTax:
    """Duck-types the Tax model as far as the engine and cost logic read it."""
    rate: Decimal
    price_include: bool = False
    include_base_amount: bool = False
    computation: str = 'PERCENT'          # 'PERCENT' | 'FIXED' | 'GROUP'
    name: str = ""
    type_tax_use: str = 'SALE'
    sequence: int = 10
    is_active: bool = True
    is_recoverable: bool = True
    children_list: List = field(default_factory=list)
    pk: int = field(default_factory=lambda: next(_pk))

    @property
    def children(self):
        return FakeChildren(self.children_list)


def pct(rate, name='', **kw):
    return FakeTax(rate=D(rate), computation='PERCENT', name=name, **kw)


def fixed(rate, name='', **kw):
    return FakeTax(rate=D(rate), computation='FIXED', name=name, **kw)


def group(name, children, **kw):
    return FakeTax(rate=D('0'), computation='GROUP', name=name, children_list=list(children), **kw)


class FakeLine:
    """A priced line as seen by calculate_document_taxes / compute_taxes."""
    def __init__(self, subtotal, taxes, quantity='1'):
        self._subtotal, self.quantity = D(subtotal), D(quantity)
        self.taxes = FakeChildren(taxes)

    def get_subtotal(self):
        return self._subtotal

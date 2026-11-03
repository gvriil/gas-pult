"""Окна пространств в панели (задача 31): тестировщик видит только своё пространство, владелец — все.

У каждого демо-пространства свой сервер tmux (``tenants.tmux_of``), и номера окон там свои: ``@3`` есть и у
владельца, и в пространстве. Поэтому панель называет окно пространства ``t:<slug>:@3`` и передаёт команды в нужный
сервер tmux сама — сервер и работа с tmux (``tmux.py``) не меняются.

``Routed`` встаёт на место ``Pult.tmux`` в процессе панели (бот работает со своим ``Tmux``, как раньше):

- запрос тестировщика идёт внутри ``with routed.scope(slug)`` — список окон только этого пространства, любое
  действие с окном не его пространства — «окна нет» (``LookupError``), новые окна — только в нём;
- владелец без ``scope`` работает со своим tmux; окна пространств он видит в списке, только когда панель сама
  попросила (``with routed.all_spaces()``), а действие с окном ``t:<slug>:…`` уходит в tmux того пространства.

Изоляцию держит не только панель: окна пространства работают от его пользователя Linux (``docs/TENANTS.md``).
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager

from gas_pult import tenants

ID = re.compile(r"^t:([a-z][a-z0-9-]{0,22}[a-z0-9]):(@\d+)$")
NO_WINDOW = "окна уже нет"


def wid_of(slug: str, raw: str) -> str:
    return f"t:{slug}:{raw}"


def split(wid) -> tuple[str | None, str]:
    """``t:demo:@3`` → (``demo``, ``@3``); окно владельца ``@3`` → (None, ``@3``)."""
    m = ID.match(str(wid or ""))
    return (m.group(1), m.group(2)) if m else (None, str(wid or ""))


class Space:
    """tmux одного пространства с номерами окон ``t:<slug>:@N``."""

    def __init__(self, slug: str, tm):
        self.slug, self.tm = slug, tm

    def own(self, wid) -> str:
        slug, raw = split(wid)
        if slug != self.slug:
            raise LookupError(NO_WINDOW)
        return raw

    def windows(self) -> list[dict]:
        try:
            ws = self.tm.windows()
        except OSError:
            return []
        return [{**w, "id": wid_of(self.slug, w["id"]), "raw": w["id"], "space": self.slug} for w in ws]

    def window(self, wid) -> dict | None:
        try:
            raw = self.own(wid)
        except LookupError:
            return None
        return next((w for w in self.windows() if w["raw"] == raw), None)

    def new_window(self, name: str, path: str, command: str, mark: str = "claude", by: str = "") -> str:
        return wid_of(self.slug, self.tm.new_window(name, path, command, mark=mark, by=by))

    def run(self, *args: str, input: str | None = None) -> str:
        return self.tm.run(*(self.own(a) if ID.match(str(a)) else a for a in args), input=input)

    def __getattr__(self, name):
        """Остальное — как у ``Tmux``: первый аргумент — окно (``screen``, ``paste``, ``keys``, ``rename``…)."""
        fn = getattr(self.tm, name)
        if not callable(fn):
            return fn

        def call(wid, *a, **kw):
            return fn(self.own(wid), *a, **kw)
        return call


class Routed:
    """Вместо ``Pult.tmux`` в панели: окна владельца и пространств, с ограничением на запрос (``scope``)."""

    def __init__(self, owner, space_of=None, slugs=None):
        self.owner = owner
        self._space_of = space_of or (lambda s: Space(s, tenants.tmux_of(s)))
        self._slugs = slugs or self.ready_slugs
        self._spaces: dict[str, Space] = {}
        self.local = threading.local()

    @staticmethod
    def ready_slugs() -> list[str]:
        if not tenants.enabled():
            return []
        return [s for s in tenants.slugs() if tenants.ready(s)]

    def space(self, slug: str) -> Space:
        if slug not in self._spaces:
            self._spaces[slug] = self._space_of(slug)
        return self._spaces[slug]

    # ---------- ограничение запроса ----------
    @property
    def scoped(self) -> str | None:
        """Пространство, которым ограничен текущий запрос (тестировщик), или None."""
        return getattr(self.local, "slug", None)

    @contextmanager
    def scope(self, slug: str | None):
        old = getattr(self.local, "slug", None)
        self.local.slug = slug
        try:
            yield
        finally:
            self.local.slug = old

    @contextmanager
    def all_spaces(self):
        """Список окон владельца — вместе с окнами всех пространств (группа «Пространства» в панели)."""
        old = getattr(self.local, "spaces", False)
        self.local.spaces = True
        try:
            yield
        finally:
            self.local.spaces = old

    def target(self, wid):
        """Чей tmux у окна. В ограниченном запросе окно владельца или чужого пространства — «окна нет»."""
        slug, _ = split(wid)
        if self.scoped is not None:
            if slug != self.scoped:
                raise LookupError(NO_WINDOW)
            return self.space(slug)
        return self.space(slug) if slug else self.owner

    # ---------- то же, что у Tmux ----------
    def windows(self) -> list[dict]:
        if self.scoped is not None:
            return self.space(self.scoped).windows() if self.scoped in self._slugs() else []
        ws = self.owner.windows()
        if getattr(self.local, "spaces", False):
            for s in self._slugs():
                ws += self.space(s).windows()
        return ws

    def window(self, wid) -> dict | None:
        try:
            t = self.target(wid)
        except LookupError:
            return None
        if t is self.owner:
            return self.owner.window(wid)
        return t.window(wid)

    def new_window(self, *a, **kw) -> str:
        if self.scoped is not None:
            raise PermissionError("в пространстве окна открывает только tenants.new_window")
        return self.owner.new_window(*a, **kw)

    def run(self, *args: str, input: str | None = None) -> str:
        ids = [a for a in args if ID.match(str(a))]
        if ids or self.scoped is not None:
            if not ids:
                raise LookupError(NO_WINDOW)
            return self.target(ids[0]).run(*args, input=input)
        return self.owner.run(*args, input=input)

    def __getattr__(self, name):
        attr = getattr(self.owner, name)
        if not callable(attr):
            return attr

        def call(wid=None, *a, **kw):
            if wid is None:                         # без окна (ensure_session, shell) — только у владельца
                if self.scoped is not None:
                    raise LookupError(NO_WINDOW)
                return attr(*a, **kw)
            return getattr(self.target(wid), name)(wid, *a, **kw)
        return call

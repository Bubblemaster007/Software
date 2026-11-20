"""Cooperative cancellation; solvers are checked between bounded MILP calls."""


class StudyCancelled(Exception):
    pass

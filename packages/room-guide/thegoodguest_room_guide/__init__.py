"""The room guide: what a room allows, and the guide that talks about it.

A room (model.py) is read from a diorama scene. What holds in every room is code
(laws.py). What this room needs is data in a fixed vocabulary (needs.py), written
once per room by the rules pass and adjustable by the person; the sizes behind it
come from the rulebook (rulebook.py). An arrangement is judged against both
(assess.py), turned into findings with numbers (analyzer.py), searched for better
versions (engine.py), and moved into place without anything passing through
anything (motion.py).

Read by: the local guide harness and, later, api-public's conversation route.
"""

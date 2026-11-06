"""The Campus Customs agent team. One module per agent; team.py wires them together."""

from . import accounting, boss, customer_service, facilities, inventory

ROLES = {m.ROLE.name: m.ROLE for m in (boss, inventory, accounting, facilities, customer_service)}

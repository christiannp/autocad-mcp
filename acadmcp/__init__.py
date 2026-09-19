"""AutoCAD MCP - drive a live AutoCAD from Claude.

Two engines, deliberately:

* **COM** for objects - create, read and edit entities as typed objects with
  stable drawing handles.
* **AutoLISP** for commands - everything AutoCAD only exposes on the command
  line (TRIM, FILLET, HATCH by point, ARRAY, PURGE, Express Tools, ...).

Between them, anything that can be done by hand in AutoCAD can be done here.
"""

__version__ = "0.1.0"

"""Service layer (#018): use cases shared by the CLI and the API.

See ``services/experiences.py`` for the first slice. Services are
framework-free: no typer, no rich, no fastapi imports allowed here.
"""

from experienceos.services import experiences

__all__ = ["experiences"]

"""Examini AI Operating Layer.

Orchestrates existing services through OpenAI Agents SDK agents/tools.
Public surface (the only sanctioned inbound doors, see AI_LAYER_DESIGN.md):

- ``app.ai.api.routes.router`` — mounted at /api/ai in app/main.py
- ``app.ai.facade``             — called by existing routes that migrate onto the layer

Nothing else in the application may import from this package, and this
package never mutates existing services, models, or routes.
"""

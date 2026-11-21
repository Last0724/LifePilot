"""Reverse-UX mechanisms for LifePilot.

Each submodule here implements one deliberately frustrating interaction and is
kept isolated from the core scheduling logic. Importing this package must not
require Streamlit, so the pure-logic parts stay unit-testable offline.
"""

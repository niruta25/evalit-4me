"""Streamlit reviewer view.

The app is structured as a pure section-builder (`build_view_sections`)
plus a thin Streamlit render (`run_app`). Unit tests exercise the pure
layer; Streamlit is a lazy import so `pip install evalit-4me` without
the `[dashboard]` extra still imports this package cleanly.
"""

from evalit_4me.dashboard.app import ViewSection, build_view_sections, run_app

__all__ = ["ViewSection", "build_view_sections", "run_app"]

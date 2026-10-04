"""Translate database failures into user-facing errors."""

import logging

import gradio as gr


def database_error():
    logging.exception("Oracle operation failed")
    return gr.Error("Could not access Oracle. Check the database connection and server log.")

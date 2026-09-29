"""Translate database failures into user-facing errors."""

import logging

import gradio as gr


def database_error():
    logging.exception("PostgreSQL operation failed")
    return gr.Error("Could not access PostgreSQL. Check the database connection and server log.")

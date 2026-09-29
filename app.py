"""Run the QC workspace with ``python app.py``."""

from qc_app.database import initialize_db
from qc_app.ui import create_app


def main() -> None:
    """Initialize PostgreSQL, build the interface, and launch Gradio."""
    initialize_db()
    create_app().launch(share=True)


if __name__ == "__main__":
    main()

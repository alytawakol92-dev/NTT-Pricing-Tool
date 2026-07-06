"""WSGI entry point for production hosting (gunicorn / any WSGI server).

    gunicorn --bind 0.0.0.0:$PORT wsgi:app
"""
from ntt_pricing.web import create_app

app = create_app()

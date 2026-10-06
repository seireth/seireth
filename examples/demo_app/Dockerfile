FROM python:3.14-alpine
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1
COPY scenarios.py server.py ./examples/demo_app/
COPY static ./examples/demo_app/static/
USER 65532:65532
EXPOSE 8080
CMD ["python", "-m", "examples.demo_app.server", "--host", "0.0.0.0", "--port", "8080"]

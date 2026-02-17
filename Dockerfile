FROM python:3.14-alpine AS build
RUN python -m venv /venv && /venv/bin/python -m pip install --no-cache-dir -U pip
COPY requirements.txt /tmp
RUN /venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.14-alpine
COPY --from=build /venv /venv
COPY kwbot.py /app/kwbot.py
WORKDIR /app
CMD ["/venv/bin/python", "/app/kwbot.py"]

# FIXTURE — deliberately misconfigured. Not built by CI, not deployed.
# Exists only to exercise the AI code review agent.
FROM python:latest

ENV DATABASE_PASSWORD=Nv4kTq8wLm2xPr6d
ARG DEPLOY_TOKEN=Zx8mKq3vLw7nTr2b

RUN curl -sL https://get.example-installer.internal/setup.sh | sh

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

USER root

CMD ["python", "-m", "evidensia"]

# Deployment foundation

This directory will hold reviewed Docker, local Compose, and Azure configuration.

The intended production mapping is React on Azure Static Web Apps and the Flask/Gunicorn container on Azure Container Apps, backed by Azure Database for MySQL and private Blob Storage. No cloud resources or deployment claims exist yet. Deployment must not include model training, and ML readiness must remain false until the frozen artifact passes checksum, dependency, metadata, and reference-inference checks.

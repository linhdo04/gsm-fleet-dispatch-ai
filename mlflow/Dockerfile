FROM ghcr.io/mlflow/mlflow:v3.14.0-full

ARG GOOGLE_CLOUD_STORAGE_VERSION=3.13.0

RUN python -m pip install --no-cache-dir \
    "google-cloud-storage==${GOOGLE_CLOUD_STORAGE_VERSION}"

# For more information, please refer to https://aka.ms/vscode-docker-python
FROM python:alpine

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

RUN apk update

# Install git
RUN apk add --no-cache git

# Install pip requirements
COPY ../requirements.txt .
RUN python -m pip install -r requirements.txt

# Install pip requirements for debug
COPY .devcontainer/requirements.debug.txt .
RUN python -m pip install -r requirements.debug.txt

# WORKDIR /app
# COPY .. /app

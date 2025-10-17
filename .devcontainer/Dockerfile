# For more information, please refer to https://aka.ms/vscode-docker-python
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Устанавливаем рабочую директорию как /workspace
WORKDIR /workspace

COPY requirements.txt .
COPY .devcontainer/requirements.debug.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements.debug.txt

# Устанавливаем debugpy
RUN pip install debugpy

# Копируем код (учтите, что volume-монтирование в dev-контейнере его затрет)
# COPY . /workspace

# Открываем порт для отладки
EXPOSE 5678

# Создаем пользователя с UID 5678 и меняем владельца /workspace
RUN adduser -u 5678 --disabled-password --gecos "" appuser && \
    chown -R appuser /workspace
USER appuser

# Запускаем приложение как модуль
CMD ["python", "-m", "app.bot"]
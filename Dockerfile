FROM python:3.9-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
ENV PYTHONPATH "${PYTHONPATH}:/app"
CMD ["python", "app/main.py"]
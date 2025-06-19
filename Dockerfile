FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY . /app

EXPOSE 8081

CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port 8081"]
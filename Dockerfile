# Python 3.10 슬림 버전 사용
FROM python:3.10-slim

# 작업 디렉토리 설정
WORKDIR /app

# 환경 변수 설정 (파이썬 출력 버퍼링 방지)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 필수 패키지 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 프로젝트 코드 전체 복사
COPY . .

# LRSE 포트 노출
EXPOSE 8081

# Uvicorn 서버 기동
CMD ["uvicorn", "core_engine.api.main:app", "--host", "0.0.0.0", "--port", "8081"]
# ==============================================================================
# 1단계: 빌드 스테이지 (Build Stage)
# ==============================================================================
FROM python:3.11-slim AS builder

# 파이썬 버퍼링 비활성화 및 .pyc 컴파일 파일 생성 방지 (용량 최적화)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# C 확장 모듈이 포함된 패키지 빌드 시에만 컴파일러 설치 (최종 이미지에는 포함 안 됨)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 독립된 가상환경(venv) 생성 및 경로 설정
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# pip 업데이트 및 의존성 패키지 설치
# (실제 환경에 맞게 requirements.txt 또는 pyproject.toml을 복사하여 사용하세요)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ==============================================================================
# 2단계: 실행 스테이지 (Runner Stage)
# ==============================================================================
FROM python:3.11-slim AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/src"

WORKDIR /app

# 보안 가이드라인(CIS 벤치마크)에 따른 Non-root 임의 사용자(Appuser) 생성
RUN useradd -u 10001 --create-home --shell /bin/bash appuser

# 빌드 스테이지에서 깔끔하게 설치된 가상환경(의존성 라이브러리 일체)만 복사
COPY --from=builder /opt/venv /opt/venv

# 소스 코드가 포함된 src 폴더를 복사하며 소유권을 appuser로 지정
# (이전 대화의 src/settlement/main.py 구조 기준)
COPY --chown=appuser:appuser ./src /app/src

# [HEALTHCHECK] curl을 설치하면 이미지 용량이 커지므로, 파이썬 내장 urllib를 활용한 경량 헬스체크
# FastAPI에 선언된 /health 또는 /healthz 엔드포인트를 호출합니다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# Non-root 사용자로 전환하여 컨테이너 실행 (보안성 확보)
USER appuser

# 컨테이너 외부 노출 포트 명시
EXPOSE 8000

# 프로덕션 환경용 Uvicorn 실행 가이드라인 적용
# (--proxy-headers 및 --forwarded-allow-ips는 Nginx/ALB 뒤에서 Client IP를 정확히 받기 위함)
CMD ["uvicorn", "settlement.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips=*"]

# Node.js LTS 이미지를 기반으로 합니다.
FROM node:lts-alpine

# Python 3 및 pip 설치
RUN apk add --no-cache python3 py3-pip

# VS Code Extension 개발에 필요한 도구를 설치합니다.
RUN npm install -g yo generator-code

# 작업 디렉토리를 설정합니다.
WORKDIR /app

# Python 가상 환경 생성 (.venv)
RUN python3 -m venv /app/.venv

# 환경 변수 설정: PATH에 가상 환경의 bin 디렉터리 추가
ENV PATH="/app/.venv/bin:$PATH"

# (선택) 호스트의 사용자 ID와 그룹 ID를 가져옵니다.
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# (선택) 컨테이너 내에 사용자를 생성하고 권한을 설정합니다. (macOS에서 권한 문제 방지)
RUN if [ "$USER_UID" != "1000" ] || [ "$USER_GID" != "1000" ]; then \
    groupadd -g $USER_GID node && \
    useradd -u $USER_UID -g node -s /bin/bash -m node; \
    fi

# (선택) 권한 관련 추가 설정 (macOS에서 권한 문제 방지)
# COPY --chown=node:node . .  # 이 부분은 아래에서 처리
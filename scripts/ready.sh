#!/usr/bin/env bash

# 이미 포트 포워딩이 실행 중인지 확인 후, 없으면 실행

if ! lsof -i :5432 -sTCP:LISTEN &>/dev/null; then
  echo "Starting port-forward for PostgreSQL (5432)..."
  kubectl port-forward services/postgres 5432:5432 -n runtime &
else
  echo "Port 5432 already in use, skipping PostgreSQL port-forward."
fi

if ! lsof -i :8080 -sTCP:LISTEN &>/dev/null; then
  echo "Starting port-forward for auth service (8080)..."
  kubectl port-forward services/auth 8080:8080 -n runtime &
else
  echo "Port 8080 already in use, skipping auth service port-forward."
fi

if ! lsof -i :8090 -sTCP:LISTEN &>/dev/null; then
  echo "Starting port-forward for Opik backend (8090->8080, 3003)..."
  kubectl port-forward services/opik-backend 8090:8080 3003:3003 -n opik-ax1 &
else
  echo "Port 8090 already in use, skipping Opik backend port-forward."
fi

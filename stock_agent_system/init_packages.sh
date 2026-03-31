#!/bin/bash
# 모든 패키지 디렉토리에 __init__.py 생성
dirs=(
  "agents/macro_regime"
  "agents/ficc"
  "agents/ficc/fixed_income"
  "agents/ficc/currency"
  "agents/ficc/commodity"
  "agents/equity"
  "agents/equity/screener"
  "agents/equity/technical"
  "agents/equity/fundamental"
  "agents/equity/news_sentiment"
  "agents/risk"
  "agents/alert"
  "orchestrator"
  "shared"
)
for d in "${dirs[@]}"; do
  touch "$d/__init__.py"
  echo "✅ $d/__init__.py"
done

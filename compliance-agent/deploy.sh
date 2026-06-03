#!/usr/bin/env bash
# ============================================================
# 内控评价合规审查智能体 — 一键部署脚本（中国大陆服务器优化）
#
# 使用：
#   bash deploy.sh           # 默认走国内镜像（pip 阿里源 + docker daocloud 源）
#   bash deploy.sh --intl    # 走 pypi.org / Docker Hub 原生源（海外/合规服务器）
#
# 前置：
# 1. 已装 docker + docker compose（如果没装，脚本会引导你）
# 2. 把 .env.example 复制为 .env 并填好 LLM_API_KEY 等
# ============================================================

set -euo pipefail

MODE="cn"
for arg in "$@"; do
  case "$arg" in
    --intl) MODE="intl" ;;
    --help|-h)
      grep '^#' "$0" | sed 's/^# \{0,1\}//' ; exit 0 ;;
  esac
done

echo "═════════════════════════════════════════════"
echo "  内控评价智能审核系统 — 部署脚本（模式：$MODE）"
echo "═════════════════════════════════════════════"
echo ""

# ----- Step 1: 检查 docker -----
if ! command -v docker &>/dev/null; then
  echo "❌ 未检测到 docker。请先安装："
  echo "   curl -fsSL https://get.docker.com | sudo sh"
  echo "   sudo usermod -aG docker \$USER"
  echo "   ↳ 然后退出重新 ssh 一次让组生效"
  exit 1
fi
if ! docker compose version &>/dev/null; then
  echo "❌ 未检测到 docker compose v2。请升级 docker 到最新版。"
  exit 1
fi
echo "✓ docker $(docker --version | awk '{print $3}' | tr -d ',') 就绪"

# ----- Step 2: Docker 镜像源（仅 cn 模式）-----
if [ "$MODE" = "cn" ] && [ ! -f /etc/docker/daemon.json ]; then
  echo ""
  echo "→ 配置 Docker 国内镜像源（避免拉 postgres/qdrant 慢）"
  sudo mkdir -p /etc/docker
  sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com",
    "https://hub-mirror.c.163.com"
  ],
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" }
}
EOF
  sudo systemctl restart docker
  echo "✓ 已配置 4 个国内镜像源"
fi

# ----- Step 3: 检查 .env -----
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    echo ""
    echo "❌ 未找到 .env 文件。已为你创建模板："
    cp .env.example .env
    echo "   请编辑 .env 填入 LLM_API_KEY / POSTGRES_PASSWORD 等敏感配置"
    echo "   编辑完成后重新运行：bash deploy.sh"
    exit 1
  else
    echo "❌ 既找不到 .env 也找不到 .env.example，仓库不完整。"
    exit 1
  fi
fi
echo "✓ .env 已就绪"

# ----- Step 4: 构建 + 启动 -----
echo ""
echo "→ 构建 backend / worker 镜像（首次约 3-5 分钟）"
if [ "$MODE" = "cn" ]; then
  docker compose build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ backend worker
else
  docker compose build backend worker
fi

echo ""
echo "→ 启动 7 个服务"
docker compose up -d

echo ""
echo "→ 等待 backend 健康（最多 60s）"
for i in $(seq 1 30); do
  if curl -s -f http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "✓ backend ready"
    break
  fi
  sleep 2
done

# ----- Step 5: 初始化指标库 -----
echo ""
echo "→ 灌入 54 项评价指标"
docker compose exec -T backend python -m app.seeds.load_indicators_55 || true

# ----- Step 6: 总结 -----
echo ""
echo "═════════════════════════════════════════════"
echo "  ✓ 部署完成"
echo "═════════════════════════════════════════════"
echo ""
docker compose ps
echo ""
echo "→ 访问地址：http://$(hostname -I 2>/dev/null | awk '{print $1}'):8000/"
echo "→ 默认账号：admin / admin123  （登录后立刻改密码！）"
echo ""
echo "→ 看日志：docker compose logs -f backend worker"
echo "→ 停止：  docker compose down"
echo ""

# 裸机 + systemd 部署指南

本文介绍如何在一台 Linux 服务器上，借助 `systemd` 与 `scripts/deploy_baremetal.sh` 脚本部署并运行 StockAI Trader。

## 环境准备

以 Ubuntu 22.04 为例，先安装基础依赖：

```bash
sudo apt update
sudo apt install -y git python3.10 python3.10-venv build-essential \
  libxml2-dev libxslt1-dev libffi-dev pkg-config nginx nodejs npm
```

> 如果希望使用 Python 3.11 或 Node 20，可以通过 `apt`/`nvm` 调整包名。Redis/MongoDB 仍为可选组件，可在需要时再根据 `.env` 打开。

## 一次性初始化

1. （可选）创建独立用户与目录：
   ```bash
   sudo useradd -m -s /bin/bash stockai || true
   sudo mkdir -p /opt/stockai
   sudo chown stockai:stockai /opt/stockai
   ```
2. 克隆仓库并准备环境变量：
   ```bash
   cd /opt/stockai
   git clone https://<your-git-remote>/StockAI-Trader.git
   cd StockAI-Trader
   cp .env.example .env  # 然后填写真实的 API/数据库配置
   ```
3. 创建运行时目录，保证具备写权限：
   ```bash
   mkdir -p cache data reports frontend/dist
   ```
4. 安装 systemd 服务：
   ```bash
   sudo cp infra/systemd/stockai-trader.service /etc/systemd/system/
   sudo nano /etc/systemd/system/stockai-trader.service  # 修改 User/WorkingDirectory 等字段
   sudo systemctl daemon-reload
   sudo systemctl enable stockai-trader.service
   ```
5. （可选）配置 Nginx：静态托管 `frontend/dist`，并将 `/api` 代理到 `http://127.0.0.1:8000`。

## 使用脚本发布

在服务器仓库根目录运行：

```bash
bash scripts/deploy_baremetal.sh \
  --branch main \
  --service stockai-trader \
  --python python3.10 \
  --venv /opt/stockai/.venv
```

脚本会执行：
- 切换并拉取指定 Git 分支；
- 创建/更新虚拟环境，并安装 `pip install -e .[storage,china]`（可用 `--pip-extras` 覆盖）；
- 在 `frontend/` 内执行 `npm ci && npm run build`；
- 重启配置好的 systemd 服务（可用 `--skip-systemd` 跳过）。

常用参数/环境变量：

| 参数或环境变量                | 作用说明                                    |
|-----------------------------|---------------------------------------------|
| `--branch` / `DEPLOY_BRANCH` | 切换到其他分支，例如测试环境。             |
| `--remote` / `DEPLOY_REMOTE` | 指定 Git 远端。                              |
| `--pip-extras`              | 传入 `storage,china` 之类的 extras 名称。   |
| `--skip-git`                | 已手动切换分支时跳过 git 操作。             |
| `--skip-frontend`           | 仅部署后端，适合热修复。                    |
| `--skip-systemd`            | 构建完成但暂不重启，可先手动验证。          |

脚本执行时需要系统已安装 `git`、指定版本的 Python 以及 `npm`。若系统存在 `sudo`，脚本会自动通过 `sudo systemctl ...` 管理服务；否则需要以具备权限的用户运行。

## 回滚步骤

想回到旧版本，可按以下操作：

```bash
cd /opt/stockai/StockAI-Trader
git checkout <previous-commit>
bash scripts/deploy_baremetal.sh --skip-git --service stockai-trader
```

确认无误后，再 `git checkout main && git pull` 回到最新版。

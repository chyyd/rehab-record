#!/bin/sh
# 后端容器的启动脚本：先建库/迁移（+ 首次建管理员），再启动服务。
#
# 为什么不在 Dockerfile 里做：镜像构建期**没有数据库**（`/data` 是运行时
# 才挂上来的卷），迁移与建管理员都必须发生在启动时。
set -eu

echo "[entrypoint] 数据库：${KB_DB_PATH:-（默认）}"

# ---------------------------------------------------------------------------
# 1) 建库 + 应用迁移（幂等：已应用的迁移会被跳过）
# ---------------------------------------------------------------------------
if ! python -m app.cli init; then
    echo "[entrypoint] ✗ 建库/迁移失败，容器退出。" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 2) 管理员账号
#
# ⚠ **只在设置了 KB_ADMIN_PASSWORD 时才动**，且只在账号**不存在**时创建。
#
# 为什么这么小心：`app.cli create-admin` 在账号已存在时语义是**重置密码**
# （见 app/cli.py::cmd_create_admin）。如果容器每次重启都无条件调它，
# 用户改过的密码会在每次重启后被悄悄改回环境变量里的值 ——
# 那种"密码自己变回去了"的问题极难排查。
#
# 想主动重置密码时：改掉 KB_ADMIN_PASSWORD 的值再重启容器即可
# （值变了，这里会重新执行）。但注意"值没变就不执行"意味着
# **同值重启不会重置** —— 这正是我们要的。
# ---------------------------------------------------------------------------
if [ -n "${KB_ADMIN_PASSWORD:-}" ]; then
    ADMIN_NO="${KB_ADMIN_EMPLOYEE_NO:-A001}"
    ADMIN_NAME="${KB_ADMIN_NAME:-科室管理员}"
    if python -c "
import sys
sys.path.insert(0, '/app/backend')
from app.core.config import get_settings
from app.db import storage
from app.models import user as user_model
cfg = get_settings()
conn = storage.connect(cfg, read_only=True)
try:
    sys.exit(0 if user_model.get_by_employee_no(conn, '${ADMIN_NO}') else 3)
finally:
    conn.close()
"; then
        echo "[entrypoint] 管理员 ${ADMIN_NO} 已存在，不改密码（要重置请改 KB_ADMIN_PASSWORD 后重启）"
    else
        echo "[entrypoint] 创建管理员 ${ADMIN_NO} …"
        python -m app.cli create-admin "$ADMIN_NO" --name "$ADMIN_NAME" \
            || echo "[entrypoint] ⚠ 创建管理员失败，可稍后手动执行：python -m app.cli create-admin" >&2
    fi
else
    echo "[entrypoint] 未设置 KB_ADMIN_PASSWORD，跳过管理员创建。" >&2
    echo "[entrypoint]   首次部署请设置它（至少 8 位），例如 compose 的 environment 里。" >&2
fi

# ---------------------------------------------------------------------------
# 3) 安全提醒（只提醒，不阻断 —— 开发/内网试跑不该被挡住）
#
# 注意末尾**不要**写 `|| true`：脚本开着 `set -e`，把失败吞掉会让
# "数据库连不上"这类真问题在启动日志里彻底消失（那比少一句提醒糟得多）。
# ---------------------------------------------------------------------------
python -c "
import sys
sys.path.insert(0, '/app/backend')
from app.core.config import get_settings
if get_settings().is_dev_secret:
    print('[entrypoint] ⚠ 仍在使用开发用 JWT 默认密钥 —— 部署前请设置 KB_JWT_SECRET', file=sys.stderr)
    print('[entrypoint]   否则重启容器会让已登录用户全部掉线，多实例还会互相踢。', file=sys.stderr)
"

echo "[entrypoint] 启动：$*"
exec "$@"

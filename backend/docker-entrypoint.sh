#!/bin/sh
# 后端容器的启动脚本：先把密钥落成文件，再建库/迁移（+ 建管理员），最后启动服务。
#
# 为什么不在 Dockerfile 里做：镜像构建期**没有数据库**（数据目录是运行时
# 才挂上来的），迁移与建管理员都必须发生在启动时。
set -eu

# 数据目录：宿主机绑挂进来的（默认 /data）。
# 刻意分成 db/ 与 secrets/ 两个子目录 —— 备份时整个目录一起拷走即可。
DATA_DIR="${KB_DATA_DIR:-/data}"
SECRETS_DIR="$DATA_DIR/secrets"

# ---------------------------------------------------------------------------
# 把"密钥类"配置**落成文件**
#
# 用户 2026-10-06 的要求：「在 D 盘建立一个目录用来映射镜像里的数据库、密码等内容
# 以便我以后备份，注意把管理员密码映射出来」。
#
# 约定 `<环境变量名>` → 文件 `<SECRETS_DIR>/<名字>.txt`，取值顺序：
#   1. 环境变量已设非空 → 用它的值，并**同步写回文件**；
#   2. 文件已存在且非空 → 用它；
#   3. 都没有 → 生成一个随机值，写文件并打印出来。
#
# ⚠ 顺序必须是"先环境变量、后文件"。反过来会让"我改了 .env 却没生效" ——
#   文件里那个旧值会永远赢。
#
# ⚠ 生成随机值用 Python 的 secrets，**不能用 shell 的 $RANDOM**：
#   很多 sh（dash/busybox）里它只有 0-32767，当密码太弱。
# ---------------------------------------------------------------------------
load_or_create_secret() {
    _name="$1"   # 环境变量名，如 KB_JWT_SECRET
    _file="$2"   # 落盘路径
    _len="${3:-32}"

    eval "_cur=\${$_name:-}"
    if [ -n "$_cur" ]; then
        # 值有变化才写盘：避免每次启动都动文件时间戳（也好让"文件被人改过"看得出来）
        if [ ! -f "$_file" ] || [ "$(cat "$_file" 2>/dev/null || true)" != "$_cur" ]; then
            mkdir -p "$(dirname "$_file")"
            printf '%s' "$_cur" > "$_file"
            chmod 600 "$_file" 2>/dev/null || true
        fi
        return 0
    fi

    if [ -f "$_file" ]; then
        _cur="$(cat "$_file")"
        if [ -n "$_cur" ]; then
            export "$_name=$_cur"
            return 0
        fi
    fi

    _cur="$(python -c "import secrets;print(secrets.token_urlsafe($_len))")"
    mkdir -p "$(dirname "$_file")"
    printf '%s' "$_cur" > "$_file"
    chmod 600 "$_file" 2>/dev/null || true
    export "$_name=$_cur"
    echo "[entrypoint] 已生成 $_name 并写入 $_file"
}

mkdir -p "$DATA_DIR/db" "$SECRETS_DIR"
echo "[entrypoint] 数据目录：$DATA_DIR"
echo "[entrypoint] 数据库：${KB_DB_PATH:-$DATA_DIR/db/kf.db}"

load_or_create_secret KB_JWT_SECRET     "$SECRETS_DIR/jwt_secret.txt"     48
load_or_create_secret KB_ADMIN_PASSWORD "$SECRETS_DIR/admin_password.txt" 12

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
# ⚠ **只在账号不存在时创建**。
#
# 为什么这么小心：`app.cli create-admin` 在账号已存在时语义是**重置密码**
# （见 app/cli.py::cmd_create_admin）。如果容器每次重启都无条件调它，
# 用户在后台改过的密码会在每次重启后被悄悄改回文件里的值 ——
# 那种"密码自己变回去了"的问题极难排查。
#
# 要主动重置：把 secrets/admin_password.txt 改掉（或设 KB_ADMIN_PASSWORD
# 环境变量覆盖它）再重启。**同值重启不会重置** —— 这正是我们要的。
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
        echo "[entrypoint] 管理员 ${ADMIN_NO} 已存在（密码未改动）"
    else
        echo "[entrypoint] 创建管理员 ${ADMIN_NO} …"
        python -m app.cli create-admin "$ADMIN_NO" --name "$ADMIN_NAME" \
            || echo "[entrypoint] ⚠ 创建管理员失败，可稍后手动执行：python -m app.cli create-admin" >&2
    fi
    # 用户明确要求"把管理员密码映射出来" —— 直接打印，省得他去翻文件
    echo "[entrypoint] ┌─────────────────────────────────────────────────"
    echo "[entrypoint] │ 管理员工号：${ADMIN_NO}"
    echo "[entrypoint] │ 管理员密码：${KB_ADMIN_PASSWORD}"
    echo "[entrypoint] │ 密码文件　：$SECRETS_DIR/admin_password.txt"
    echo "[entrypoint] └─────────────────────────────────────────────────"
else
    echo "[entrypoint] ⚠ 未能取得管理员密码。" >&2
fi

# ---------------------------------------------------------------------------
# 3) 安全提醒（只提醒，不阻断 —— 内网试跑不该被挡住）
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

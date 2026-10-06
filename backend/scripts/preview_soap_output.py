"""交付验证：真实跑一遍，把三样东西打出来。

1. `GET /api/v1/records/form` 的真实响应（首评 / 日常 / 复评 / 出院小结四种情形）；
2. 三种 SOAP 文本：当日汇总（JSON）、患者每日汇总（JSON）、单患者 PDF（反向提取文本）；
3. 顺带打印 `POST /records` 建出来的记录里冻结的 `rendered_text`。

用 FastAPI 的 `TestClient` 起真实应用实例（同一套路由、依赖注入与 SQLite 库），
不手写任何输出。运行：

    C:\\Users\\...\\Python313\\python.exe scripts\\preview_soap_output.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TMP_DIR = BACKEND / "data"
TMP_DIR.mkdir(parents=True, exist_ok=True)
fd, path = tempfile.mkstemp(prefix="kf-soap-", suffix=".db", dir=TMP_DIR)
os.close(fd)
db_file = Path(path)
os.environ["KB_DB_PATH"] = str(db_file)

from app.core.config import Settings, get_settings  # noqa: E402

get_settings.cache_clear()
settings = Settings(db_path=db_file)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import storage  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import user as user_model  # noqa: E402

PASSWORD = "Therapist#2026"


def hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    conn = storage.connect(settings)
    storage.migrate(conn, storage.discover_migrations(settings=settings))

    t1 = user_model.create_user(
        conn, employee_no="T001", name="张三", role=user_model.ROLE_THERAPIST, password=PASSWORD
    )
    user_model.create_user(conn, employee_no="A001", name="管理员", role="admin", password=PASSWORD)
    conn.execute(
        "INSERT INTO patient (inpatient_no, name, diagnosis, admin_note, assigned_therapist_id)"
        " VALUES ('ZY001', '患者甲', '脑卒中恢复期', '左侧偏瘫，注意防跌倒', ?)",
        (int(t1["id"]),),
    )

    client = TestClient(create_app(), raise_server_exceptions=False)

    def login(employee_no: str) -> dict[str, str]:
        resp = client.post(
            "/api/v1/auth/login", json={"employee_no": employee_no, "password": PASSWORD}
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    h1 = login("T001")
    ha = login("A001")

    def post_record(kind: str, day: str, body: dict, status: str = "submitted") -> dict:
        resp = client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001",
                "record_date": day,
                "discipline": "PT",
                "kind": kind,
                "body": body,
                "status": status,
            },
            headers=h1,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def form(**params) -> dict:
        params.setdefault("patient_no", "ZY001")
        params.setdefault("discipline", "PT")
        resp = client.get("/api/v1/records/form", params=params, headers=h1)
        assert resp.status_code == 200, resp.text
        return resp.json()

    # ------------------------------------------------------------------ #
    # 1) GET /records/form
    # ------------------------------------------------------------------ #
    hr("① GET /api/v1/records/form —— 该患者还没有任何 PT 记录")
    first = form(date="2026-10-05")
    print(json.dumps(_trim_form(first), ensure_ascii=False, indent=2))

    post_record(
        "initial",
        "2026-10-05",
        {
            "complaint": ["肢体无力"],
            "vas": 2,
            "compliance": "配合良好",
            "consciousness": "清楚",
            "affected_side": "左侧",
            "mmt_upper": 2,
            "mmt_lower": 2,
            "sit_balance": "Ⅱ级",
            "stand_balance": "无法站立",
            "fall_risk": "高风险",
            "diagnosis": ["偏瘫运动功能障碍", "平衡功能障碍"],
            "impairment": "中度受损",
            "goal_short": "坐位平衡达Ⅲ级，辅助站立维持≥60s",
            "therapy_items": ["偏瘫肢体综合训练", "平衡生物反馈训练"],
            "frequency": "每日1次，每次30min，每周5次",
            "safety": ["训练全程监护", "防跌倒"],
        },
    )
    hr("① 首评建好之后的 GET /records/form —— 这次填「日常治疗记录」")
    second = form(date="2026-10-05")
    print(json.dumps(_trim_form(second), ensure_ascii=False, indent=2))

    daily1 = post_record(
        "daily",
        "2026-10-05",
        {
            "mental": "良好",
            "complaint": ["乏力"],
            "vas": 2,
            "therapy_items": ["偏瘫肢体综合训练"],
            "vital_signs": "平稳",
            "completed": ["坐位重心转移"],
            "stand_sec": 45,
            "performance": "较前改善",
            "plan_effect": "有效",
            "next_step": "继续维持原方案",
            "safety": ["继续落实防跌倒宣教"],
        },
    )
    daily2 = post_record(
        "daily",
        "2026-10-06",
        {
            "mental": "良好",
            "complaint": ["无不适"],
            "vas": 1,
            "therapy_items": ["偏瘫肢体综合训练", "肢体平衡功能训练"],
            "completed": ["坐位重心转移", "辅助站立负重训练"],
            "stand_sec": 60,
            "performance": "较前改善",
            "next_step": "微调训练强度",
        },
    )

    hr("① 两条日常记录冻结的 rendered_text（POST /records 的返回）")
    print("[2026-10-05 第 1 次]")
    print(daily1["rendered_text"])
    print("\n[2026-10-06 第 2 次]")
    print(daily2["rendered_text"])

    hr("① 同一天再打开表单（已有 1 条日常）：existing 给出那一条 + same_day_first 预填")
    fifth = form(date="2026-10-05")
    print(json.dumps(_trim_form(fifth), ensure_ascii=False, indent=2)[-2200:])

    # 再落库 18 条日常（第 3–20 次），让记录多一些、表单里的 next_seq 走到 21。
    #
    # ★ 复评的触发点与"第几次"无关（2026-10-06 起按**日期**算）：
    #   首评在 2026-10-05 → 应做日 = 首评 + 30 天 = 2026-11-04，
    #   所以下面取表单用的是 11-04（原来按"满 20 次"用的是 11-01）。
    for index in range(3, 21):
        conn.execute(
            "INSERT INTO treatment_record"
            " (patient_no, therapist_id, record_date, discipline, kind, seq_no, body_json,"
            "  rendered_text, status, submitted_at)"
            " VALUES ('ZY001', ?, ?, 'PT', 'daily', ?, '{}', ?, 'submitted',"
            "         '2026-10-06T00:00:00.000Z')",
            (
                int(t1["id"]),
                f"2026-10-{min(index, 28):02d}",
                index,
                f"康复治疗记录（PT运动）\n治疗日期：2026-10-07   第 {index} 次\n\n"
                "主观资料：精神状态：良好\n\n客观资料：本次训练项目：偏瘫肢体综合训练",
            ),
        )
    hr("① 距首评满 30 个自然日 —— GET /records/form 先弹「阶段性复评」")
    third = form(date="2026-11-04")
    print(json.dumps(_trim_form(third), ensure_ascii=False, indent=2))

    post_record(
        "reassessment",
        "2026-11-04",
        {
            "complaint": ["肢体无力"],
            "mmt_upper": 3,
            "mmt_lower": 3,
            "sit_balance": "Ⅲ级",
            "stand_balance": "Ⅱ级",
            "fall_risk": "中风险",
            "diagnosis": ["偏瘫运动功能障碍"],
            "improvement": ["运动能力显著改善"],
            "therapy_items": ["偏瘫肢体综合训练"],
        },
    )
    hr("① 显式要「出院小结」表单（kind=discharge）：含服务端自动生成的汇总")
    fourth = form(kind="discharge", date="2026-11-05")
    print(json.dumps(_trim_form(fourth), ensure_ascii=False, indent=2))

    discharge = post_record(
        "discharge",
        "2026-11-05",
        {
            **{k: v for k, v in fourth["prefill"].items()},
            "subjective_change": ["肢体力量明显恢复", "站立行走稳定性改善"],
            "vas": 0,
            "home_activity": "可独立室内活动",
            "goal_achieved": "基本达成",
            "improvement": ["运动能力显著改善", "平衡能力显著改善"],
            "residual": ["步行耐力不足，长时间活动易疲劳"],
            "discharge_goal": "维持现有运动功能，逐步提升步行耐力，安全进行居家活动",
            "home_training": ["肌力训练", "平衡训练"],
            "home_frequency": "每日1次，每次30min",
            "safety_note": ["起身、转身动作缓慢", "家属陪同训练"],
            "home_management": ["坚持良肢位摆放", "防跌倒环境改造"],
            "follow_up": "1个月后康复科门诊复查",
        },
    )
    hr("① 出院小结冻结的 rendered_text（自动汇总 + 治疗师补充）")
    print(discharge["rendered_text"])

    # ------------------------------------------------------------------ #
    # 2) 三种 SOAP 文本
    # ------------------------------------------------------------------ #
    # 注意：此时患者已是 `pending_discharge`（上一步提交了出院小结），
    # 对治疗师而言他从白板上消失了 —— 所以汇总与打印这一节用**管理员**身份看
    #（管理员不受在院状态限制，能打出完整病历）。
    hr("② 当日汇总（GET /api/v1/summary/date?date=2026-10-05）：JSON 里就是 SOAP 文本")
    date_summary = client.get(
        "/api/v1/summary/date", params={"date": "2026-10-05"}, headers=ha
    ).json()
    print(json.dumps(date_summary, ensure_ascii=False, indent=2)[:3000])

    hr("② 患者每日汇总（GET /api/v1/summary/patient/ZY001）：按天带出 SOAP 文本")
    daily_resp = client.get("/api/v1/summary/patient/ZY001", headers=ha)
    print(f"[HTTP {daily_resp.status_code}]")
    daily_summary = daily_resp.json()
    print(json.dumps(_trim_daily(daily_summary), ensure_ascii=False, indent=2))

    hr("② 单患者 PDF（GET /api/v1/print/patient/ZY001）反向提取的文本")
    pdf_resp = client.get("/api/v1/print/patient/ZY001", headers=ha)
    print(_pdf_text(pdf_resp.content))

    hr("② 当日汇总 PDF（GET /api/v1/print/summary/date?date=2026-10-05）反向提取的文本")
    pdf_date = client.get(
        "/api/v1/print/summary/date", params={"date": "2026-10-05"}, headers=ha
    )
    print(_pdf_text(pdf_date.content))

    hr("② 患者每日汇总 PDF（GET /api/v1/print/summary/patient/ZY001）反向提取的文本")
    pdf_daily = client.get("/api/v1/print/summary/patient/ZY001", headers=ha)
    print(_pdf_text(pdf_daily.content))

    conn.close()
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_file) + suffix).unlink(missing_ok=True)
    print(f"\n（临时库已清理：{db_file.name}）")
    return 0


def _trim_form(data: dict) -> dict:
    """表单响应很长（16 份模板的字段定义都在里面），这里只留字段骨架便于阅读。"""
    out = dict(data)
    out["soap"] = [
        {
            "key": section["key"],
            "heading": section["heading"],
            "fields": [
                {k: v for k, v in field.items() if k in ("key", "type", "label", "required", "prefill")}
                for field in section["fields"]
            ],
        }
        for section in data["soap"]
    ]
    if data.get("existing"):
        out["existing"] = {
            k: data["existing"][k]
            for k in ("id", "kind", "seq_no", "status", "record_date", "body")
        }
    return out


def _trim_daily(data: dict) -> dict:
    out = dict(data)
    out["days"] = [
        {
            "record_date": day["record_date"],
            "record_count": day["record_count"],
            "therapists": day["therapists"],
            "disciplines": day["disciplines"],
            "texts": day["texts"],
        }
        for day in data["days"]
    ]
    return out


def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


if __name__ == "__main__":
    raise SystemExit(main())

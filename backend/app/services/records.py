"""治疗记录业务逻辑（阶段 3 / `设计.md` 3.7、`开发计划.md` T3.6/T3.7）。

本模块有两个核心职责：

1. **组装记录表单**（`build_form`）：把字典、选项集、上次值合成一份"前端可直接渲染"的结构。
   这样治疗师端不需要知道字典层级与选项解析规则，也避免 N 次请求。
2. **参数带入与快照**（`resolve_params` / `snapshot_params`）：决定每个参数用什么默认值，
   并在保存时把"当时的参数名与选项文本"固化进 `params_snapshot_json`，
   使字典后续改名不影响历史记录（`设计.md` 4.3）。

参数带入优先级（Q7 定稿）：

    上次值（该患者在该子项目的最近一次记录）
      → 个人默认（该 code 的个人选项集里的 is_default）
      → 科室默认（dept 选项集的 is_default）
      → 全局默认（global 选项集的 is_default）
      → 字典默认（sub_item_param_def.default_value）
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import jsonutil
from app.core.worktime import classify_period
from app.models import dictionary as dictionary_model
from app.models import response_def as response_def_model
from app.models import treatment as treatment_model
from app.models.base import Invalid
from app.services import options as options_service


# --------------------------------------------------------------------------- #
# 表单组装
# --------------------------------------------------------------------------- #
def build_form(
    conn: sqlite3.Connection,
    *,
    patient_no: str,
    owner_user_id: int,
    dept_tag: str | None = None,
    main_item_id: int | None = None,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """组装记录页所需的一切：患者信息、字典树、每个参数的选项与带入值、可用的患者反应。"""
    from app.models import patient as patient_model

    patient = patient_model.get_patient_or_raise(conn, patient_no)

    main_items = dictionary_model.dictionary_tree(conn, main_item_id=main_item_id)
    for main in main_items:
        for sub in main["sub_items"]:
            enriched: list[dict[str, Any]] = []
            last = treatment_model.last_params_for_sub_item(conn, patient_no, int(sub["id"]))
            for param in sub["params"]:
                enriched.append(
                    _enrich_param(
                        conn,
                        param,
                        owner_user_id=owner_user_id,
                        dept_tag=dept_tag,
                        last_params=last,
                    )
                )
            sub["params"] = enriched

    responses = response_def_model.list_response_defs(conn, main_item_id=main_item_id)
    return {
        "patient": {
            "inpatient_no": patient["inpatient_no"],
            "name": patient["name"],
            "diagnosis": patient["diagnosis"],
            "admin_note": patient["admin_note"],
            "status": patient["status"],
            "visible_therapist_id": patient["visible_therapist_id"],
        },
        "main_items": main_items,
        "response_defs": responses,
        "last_completed_seq_no": _last_seq_no(conn, patient_no),
        "reference_date": reference_date,
    }


def _last_seq_no(conn: sqlite3.Connection, patient_no: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq_no), 0) FROM treatment_record"
        " WHERE patient_no = ? AND status IN (?, ?)",
        (patient_no, treatment_model.STATUS_SUBMITTED, treatment_model.STATUS_LOCKED),
    ).fetchone()
    return int(row[0])


def _enrich_param(
    conn: sqlite3.Connection,
    param: dict[str, Any],
    *,
    owner_user_id: int,
    dept_tag: str | None,
    last_params: dict[str, Any] | None,
) -> dict[str, Any]:
    """给一个参数定义补上：解析后的选项、带入值、以及值的来源。"""
    code = param["param_key"]
    resolved = options_service.resolve_options(
        conn,
        code=code,
        builtin=param.get("options") or [],
        owner_user_id=owner_user_id,
        dept_tag=dept_tag,
    )

    last_value = None
    if last_params is not None and code in last_params:
        last_value = last_params[code]

    default_from_options = list(resolved["defaults"])
    current, value_source = _pick_default(
        input_type=param["input_type"],
        last_value=last_value,
        option_defaults=default_from_options,
        dict_default=param.get("default_value"),
    )
    param = dict(param)
    param["options_resolved"] = resolved
    param["value_source"] = value_source
    param["current_value"] = current
    param["last_value"] = last_value
    return param


def _pick_default(
    *,
    input_type: str,
    last_value: Any,
    option_defaults: list[str],
    dict_default: str | None,
) -> tuple[Any, str]:
    """返回 ``(带入值, 来源)``。来源用于前端提示"这是上次的值"，也让测试能断言优先级。"""
    if last_value not in (None, "", [], {}):
        return last_value, "last_value"

    if option_defaults:
        if input_type == "multi_select":
            return list(option_defaults), "option_set_default"
        return option_defaults[0], "option_set_default"

    if dict_default is None:
        return ([] if input_type == "multi_select" else None), "none"

    parsed = jsonutil.loads(dict_default, None)
    if isinstance(parsed, list):
        return parsed, "dict_default"
    return dict_default, "dict_default"


# --------------------------------------------------------------------------- #
# 参数校验与快照
# --------------------------------------------------------------------------- #
def resolve_params(
    conn: sqlite3.Connection,
    *,
    sub_item_id: int,
    params: dict[str, Any] | None,
    owner_user_id: int,
    dept_tag: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """校验并归一化一组参数。

    返回 ``(归一化后的 params, 快照列表)``。快照记录每个参数的**当时的**显示名与选项文本，
    存进 `params_snapshot_json`，因此历史记录不因字典改名而改变。

    校验规则：
    - 未知 `param_key` 直接拒绝（防止前端拼错键导致数据静默丢失）；
    - `select` / `multi_select` 的取值必须来自解析后的选项（允许"其他"自由文本时除外，见下）；
    - `number` 的取值必须是数字，且在 `value_min`/`value_max` 范围内（若有定义）。
    """
    supplied = dict(params or {})
    defs = dictionary_model.list_params(conn, sub_item_id)
    known = {d["param_key"]: d for d in defs}

    unknown = set(supplied) - set(known)
    if unknown:
        raise Invalid(
            "存在未知参数键（可能是前端拼写错误）",
            details={"sub_item_id": sub_item_id, "unknown_keys": sorted(unknown)},
        )

    normalized: dict[str, Any] = {}
    snapshot: list[dict[str, Any]] = []
    for key, definition in known.items():
        if key not in supplied:
            # 未提交的参数留空，不写进 JSON（保持记录精简）
            snapshot_entry = {
                "param_key": key,
                "param_name": definition["param_name"],
                "input_type": definition["input_type"],
                "unit": definition.get("unit"),
            }
            # 必填但没给值 —— 只在"给了 params 但漏了这个必填项"时报错：
            # 完全空表单（params 为空）不应报错，否则新建草稿就会失败
            if definition["required"] and supplied:
                raise Invalid(
                    "必填参数缺失",
                    details={"sub_item_id": sub_item_id, "param_key": key,
                             "param_name": definition["param_name"]},
                )
            snapshot_entry["value"] = None
            snapshot_entry["options"] = definition.get("options") or []
            snapshot.append(snapshot_entry)
            continue

        value = supplied[key]
        value = _validate_value(conn, definition, value, owner_user_id=owner_user_id, dept_tag=dept_tag)
        normalized[key] = value
        snapshot.append(
            {
                "param_key": key,
                "param_name": definition["param_name"],
                "input_type": definition["input_type"],
                "unit": definition.get("unit"),
                "value": value,
                "options": definition.get("options") or [],
            }
        )
    return normalized, snapshot


def _validate_value(
    conn: sqlite3.Connection,
    definition: dict[str, Any],
    value: Any,
    *,
    owner_user_id: int,
    dept_tag: str | None,
) -> Any:
    from app.models.dictionary import get_sub_item  # noqa: F401  (保持导入语义清晰)

    key, input_type = definition["param_key"], definition["input_type"]

    if input_type == "number":
        if value in (None, ""):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise Invalid("数值参数取值非法", details={"param_key": key, "value": value})
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise Invalid("数值参数取值非法", details={"param_key": key, "value": value}) from exc
        if number.is_integer():
            number = int(number)
        vmin, vmax = definition.get("value_min"), definition.get("value_max")
        if vmin is not None and number < vmin:
            raise Invalid("取值低于下限", details={"param_key": key, "min": vmin})
        if vmax is not None and number > vmax:
            raise Invalid("取值高于上限", details={"param_key": key, "max": vmax})
        return number

    if input_type == "text":
        return None if value is None else str(value)

    # select / multi_select：取值必须来自"解析后的有效选项"
    resolved = options_service.resolve_options(
        conn,
        code=key,
        builtin=definition.get("options") or [],
        owner_user_id=owner_user_id,
        dept_tag=dept_tag,
    )
    allowed = [o["value"] for o in resolved["options"]]
    if input_type == "multi_select":
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise Invalid("多选参数取值必须是数组", details={"param_key": key, "value": value})
        invalid = [v for v in value if v not in allowed]
        if invalid:
            raise Invalid(
                "存在不在选项内的取值",
                details={"param_key": key, "invalid": invalid, "allowed": allowed},
            )
        return value
    if value in (None, ""):
        return None
    if value not in allowed:
        raise Invalid(
            "取值不在选项内", details={"param_key": key, "value": value, "allowed": allowed}
        )
    return value


def normalize_responses(
    conn: sqlite3.Connection,
    *,
    patient_response: Any,
    main_item_ids: list[int] | None = None,
) -> dict[str, Any] | None:
    """校验并归一化 `patient_response_json`（结构见 `设计.md` 4.2.2）。

    输入形如::

        {"tags": ["no_discomfort"], "items": [{"code": "pain", "value": 3}]}

    校验：`tags` 里的 code 必须是 `tag` 类型；`items` 里的 value 必须符合定义的
    `value_type` 与范围；并**补写 label / value_key / unit 快照**，
    使字典改名后历史仍可正确展示。
    """
    if patient_response is None:
        return None
    if not isinstance(patient_response, dict):
        raise Invalid("patient_response 必须是对象", details={"type": type(patient_response).__name__})

    primary_main = (main_item_ids or [None])[0]
    result: dict[str, Any] = {"tags": [], "items": []}

    tags = patient_response.get("tags") or []
    if not isinstance(tags, list):
        raise Invalid("tags 必须是数组")
    for code in tags:
        definition = response_def_model.get_by_code(conn, str(code), main_item_id=primary_main)
        if definition is None:
            raise Invalid("未知的患者反应", details={"response_code": code})
        if definition["value_type"] != "tag":
            raise Invalid(
                "该反应需要取值，不能放在 tags 里",
                details={"response_code": code, "value_type": definition["value_type"]},
            )
        result["tags"].append({"code": definition["code"], "label": definition["label"]})

    items = patient_response.get("items") or []
    if not isinstance(items, list):
        raise Invalid("items 必须是数组")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not item.get("code"):
            raise Invalid("items 的每一项都必须包含 code")
        code = str(item["code"])
        definition = response_def_model.get_by_code(conn, code, main_item_id=primary_main)
        if definition is None:
            raise Invalid("未知的患者反应", details={"response_code": code})
        if code in seen:
            raise Invalid("同一反应不能重复出现", details={"response_code": code})
        seen.add(code)

        value = item.get("value")
        value_type = definition["value_type"]
        if value_type == "number":
            if value in (None, ""):
                raise Invalid("该反应需要取值", details={"response_code": code})
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise Invalid("反应取值必须是数字", details={"response_code": code, "value": value}) from exc
            if number.is_integer():
                number = int(number)
            vmin, vmax = definition.get("value_min"), definition.get("value_max")
            if vmin is not None and number < vmin:
                raise Invalid("反应取值低于下限", details={"response_code": code, "min": vmin})
            if vmax is not None and number > vmax:
                raise Invalid("反应取值高于上限", details={"response_code": code, "max": vmax})
            value = number
        elif value_type == "select":
            allowed = definition.get("options") or []
            if value not in allowed:
                raise Invalid("反应取值不在选项内", details={"response_code": code, "allowed": allowed})
        elif value_type == "tag":
            raise Invalid("标签类反应应放在 tags 里", details={"response_code": code})
        else:
            value = None if value is None else str(value)

        result["items"].append(
            {
                "code": definition["code"],
                "label": definition["label"],
                "value_type": value_type,
                "value_key": definition.get("value_key"),
                "value": value,
                "unit": definition.get("value_unit"),
            }
        )
    return result


# --------------------------------------------------------------------------- #
# 半日推断
# --------------------------------------------------------------------------- #
def infer_session_period(clock: str) -> str | None:
    """按当前时间推断所属半日（Q11 作息）。落在午休/作息外时返回 None，由调用方要求显式指定。"""
    from app.core.worktime import parse_hm

    return classify_period(parse_hm(clock))


__all__ = [
    "build_form",
    "infer_session_period",
    "normalize_responses",
    "resolve_params",
]

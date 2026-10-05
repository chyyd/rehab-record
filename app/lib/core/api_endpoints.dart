/// 后端接口路径常量（与 `backend/app/api/v1/` 对齐）。
///
/// 只收录 App 用到的接口。字段名沿用后端的 snake_case，不做驼峰转换——
/// 少一层映射就少一处会漂移的地方（与管理后台 `admin/src/api/endpoints.ts` 同一约定）。
library;

/// 统一前缀。
const String kApiPrefix = '/api/v1';

/// 默认后端地址。真机/内网部署时由 `AppConfig` 覆盖。
const String kDefaultBaseUrl = 'http://127.0.0.1:8000';

// --------------------------------------------------------------------------- //
// 认证
// --------------------------------------------------------------------------- //
const String kAuthLogin = '$kApiPrefix/auth/login';
const String kAuthRefresh = '$kApiPrefix/auth/refresh';
const String kAuthLogout = '$kApiPrefix/auth/logout';
const String kAuthMe = '$kApiPrefix/auth/me';
const String kAuthPassword = '$kApiPrefix/auth/password';

// --------------------------------------------------------------------------- //
// 患者（★ 不走同步接口，见 docs/sync-protocol.md §1）
// --------------------------------------------------------------------------- //
const String kPatients = '$kApiPrefix/patients';
String kPatient(String inpatientNo) => '$kPatients/$inpatientNo';
String kPatientAssignments(String inpatientNo) => '$kPatients/$inpatientNo/assignments';
const String kPatientClaim = '$kPatients/claim';
String kPatientRelease(String inpatientNo) => '$kPatients/$inpatientNo/release';

/// 出院流程（用户 2026-10-05 要求：「所有治疗师都可以有出院的权限」）。
///
/// - [kPatientDischarge]：**任何治疗师**都能调，body `{"record_id": <已提交的出院小结 id>}`，
///   把患者置为 `pending_discharge`（随即从治疗师白板消失）；
/// - `confirm` / `cancel` 只有管理员能用（App 不提供入口，留常量便于排查）。
String kPatientDischarge(String inpatientNo) => '$kPatients/$inpatientNo/discharge';
String kPatientDischargeConfirm(String inpatientNo) =>
    '${kPatientDischarge(inpatientNo)}/confirm';
String kPatientDischargeCancel(String inpatientNo) =>
    '${kPatientDischarge(inpatientNo)}/cancel';

// --------------------------------------------------------------------------- //
// 同步
// --------------------------------------------------------------------------- //
const String kSyncInfo = '$kApiPrefix/sync/info';
const String kSyncPush = '$kApiPrefix/sync/push';
const String kSyncPull = '$kApiPrefix/sync/pull';

// --------------------------------------------------------------------------- //
// 治疗记录（SOAP 模板驱动，迁移 011 之后）
//
// ★ 曾经的 `/dict/**`、`/templates*`、`/option-sets*`、`/response-defs*` 常量
// **已全部删除**：那些表随迁移 011/012 删除，接口也不存在了。模板改成
// `templates/*.json`（内容不进数据库），由 `/records/form` 一次性返回，
// App 端只需要下面这几个常量。
// --------------------------------------------------------------------------- //
const String kRecords = '$kApiPrefix/records';
String kRecord(int recordId) => '$kRecords/$recordId';
String kRecordSubmit(int recordId) => '$kRecords/$recordId/submit';
String kRecordLock(int recordId) => '$kRecords/$recordId/lock';

/// 记录页表单：该填哪份文书 + 四段字段定义 + 预填 + 已存在的那条。
///
/// 必填参数 `patient_no` + `discipline`；可选 `date`、`kind`
/// （**出院小结必须显式传 `kind=discharge`**，门禁推不出来）。
const String kRecordForm = '$kRecords/form';

/// 状态 / 形态 / 四大类枚举。
const String kRecordEnums = '$kRecords/enums';
const String kTimeline = '$kApiPrefix/timeline';

// --------------------------------------------------------------------------- //
// 汇总与打印
// --------------------------------------------------------------------------- //
const String kSummaryDate = '$kApiPrefix/summary/date';
String kSummaryPatient(String inpatientNo) => '$kApiPrefix/summary/patient/$inpatientNo';
String kSummaryPatientOverview(String inpatientNo) =>
    '$kApiPrefix/summary/patient/$inpatientNo/overview';
String kPrintPatient(String inpatientNo) => '$kApiPrefix/print/patient/$inpatientNo';
const String kPrintSummaryDate = '$kApiPrefix/print/summary/date';
String kPrintSummaryPatient(String inpatientNo) =>
    '$kApiPrefix/print/summary/patient/$inpatientNo';
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

// --------------------------------------------------------------------------- //
// 同步
// --------------------------------------------------------------------------- //
const String kSyncInfo = '$kApiPrefix/sync/info';
const String kSyncPush = '$kApiPrefix/sync/push';
const String kSyncPull = '$kApiPrefix/sync/pull';

// --------------------------------------------------------------------------- //
// 字典 / 选项集 / 反应定义 / 模板（只读缓存）
// --------------------------------------------------------------------------- //
const String kDictTree = '$kApiPrefix/dict/tree';
const String kDictMainItems = '$kApiPrefix/dict/main-items';
const String kDictSubItems = '$kApiPrefix/dict/sub-items';
String kDictSubItemParams(int subItemId) => '$kDictSubItems/$subItemId/params';
const String kOptionSets = '$kApiPrefix/option-sets';
const String kOptionSetsResolve = '$kOptionSets/resolve';
const String kOptionSetsPersonal = '$kOptionSets/personal';
const String kResponseDefs = '$kApiPrefix/response-defs';
const String kResponseDefsGrouped = '$kResponseDefs/grouped';
const String kTemplates = '$kApiPrefix/templates';
String kTemplateApply(int templateId) => '$kTemplates/$templateId/apply';

// --------------------------------------------------------------------------- //
// 治疗记录
// --------------------------------------------------------------------------- //
const String kRecords = '$kApiPrefix/records';
String kRecord(int recordId) => '$kRecords/$recordId';
String kRecordSubmit(int recordId) => '$kRecords/$recordId/submit';
String kRecordLock(int recordId) => '$kRecords/$recordId/lock';
const String kRecordForm = '$kRecords/form';
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
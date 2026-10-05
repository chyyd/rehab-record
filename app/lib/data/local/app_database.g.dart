// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'app_database.dart';

// ignore_for_file: type=lint
class $PatientsTable extends Patients with TableInfo<$PatientsTable, Patient> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $PatientsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _inpatientNoMeta = const VerificationMeta(
    'inpatientNo',
  );
  @override
  late final GeneratedColumn<String> inpatientNo = GeneratedColumn<String>(
    'inpatient_no',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _nameMeta = const VerificationMeta('name');
  @override
  late final GeneratedColumn<String> name = GeneratedColumn<String>(
    'name',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _diagnosisMeta = const VerificationMeta(
    'diagnosis',
  );
  @override
  late final GeneratedColumn<String> diagnosis = GeneratedColumn<String>(
    'diagnosis',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _adminNoteMeta = const VerificationMeta(
    'adminNote',
  );
  @override
  late final GeneratedColumn<String> adminNote = GeneratedColumn<String>(
    'admin_note',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _assignedTherapistIdMeta =
      const VerificationMeta('assignedTherapistId');
  @override
  late final GeneratedColumn<int> assignedTherapistId = GeneratedColumn<int>(
    'assigned_therapist_id',
    aliasedName,
    true,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _assignedTherapistNameMeta =
      const VerificationMeta('assignedTherapistName');
  @override
  late final GeneratedColumn<String> assignedTherapistName =
      GeneratedColumn<String>(
        'assigned_therapist_name',
        aliasedName,
        true,
        type: DriftSqlType.string,
        requiredDuringInsert: false,
      );
  static const VerificationMeta _visibleTherapistIdMeta =
      const VerificationMeta('visibleTherapistId');
  @override
  late final GeneratedColumn<int> visibleTherapistId = GeneratedColumn<int>(
    'visible_therapist_id',
    aliasedName,
    true,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _statusMeta = const VerificationMeta('status');
  @override
  late final GeneratedColumn<String> status = GeneratedColumn<String>(
    'status',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _revisionMeta = const VerificationMeta(
    'revision',
  );
  @override
  late final GeneratedColumn<int> revision = GeneratedColumn<int>(
    'revision',
    aliasedName,
    false,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
    defaultValue: const Constant(0),
  );
  static const VerificationMeta _visibleMeta = const VerificationMeta(
    'visible',
  );
  @override
  late final GeneratedColumn<bool> visible = GeneratedColumn<bool>(
    'visible',
    aliasedName,
    false,
    type: DriftSqlType.bool,
    requiredDuringInsert: false,
    defaultConstraints: GeneratedColumn.constraintIsAlways(
      'CHECK ("visible" IN (0, 1))',
    ),
    defaultValue: const Constant(true),
  );
  static const VerificationMeta _fetchedAtMeta = const VerificationMeta(
    'fetchedAt',
  );
  @override
  late final GeneratedColumn<String> fetchedAt = GeneratedColumn<String>(
    'fetched_at',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [
    inpatientNo,
    name,
    diagnosis,
    adminNote,
    assignedTherapistId,
    assignedTherapistName,
    visibleTherapistId,
    status,
    revision,
    visible,
    fetchedAt,
  ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'patients';
  @override
  VerificationContext validateIntegrity(
    Insertable<Patient> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('inpatient_no')) {
      context.handle(
        _inpatientNoMeta,
        inpatientNo.isAcceptableOrUnknown(
          data['inpatient_no']!,
          _inpatientNoMeta,
        ),
      );
    } else if (isInserting) {
      context.missing(_inpatientNoMeta);
    }
    if (data.containsKey('name')) {
      context.handle(
        _nameMeta,
        name.isAcceptableOrUnknown(data['name']!, _nameMeta),
      );
    } else if (isInserting) {
      context.missing(_nameMeta);
    }
    if (data.containsKey('diagnosis')) {
      context.handle(
        _diagnosisMeta,
        diagnosis.isAcceptableOrUnknown(data['diagnosis']!, _diagnosisMeta),
      );
    }
    if (data.containsKey('admin_note')) {
      context.handle(
        _adminNoteMeta,
        adminNote.isAcceptableOrUnknown(data['admin_note']!, _adminNoteMeta),
      );
    }
    if (data.containsKey('assigned_therapist_id')) {
      context.handle(
        _assignedTherapistIdMeta,
        assignedTherapistId.isAcceptableOrUnknown(
          data['assigned_therapist_id']!,
          _assignedTherapistIdMeta,
        ),
      );
    }
    if (data.containsKey('assigned_therapist_name')) {
      context.handle(
        _assignedTherapistNameMeta,
        assignedTherapistName.isAcceptableOrUnknown(
          data['assigned_therapist_name']!,
          _assignedTherapistNameMeta,
        ),
      );
    }
    if (data.containsKey('visible_therapist_id')) {
      context.handle(
        _visibleTherapistIdMeta,
        visibleTherapistId.isAcceptableOrUnknown(
          data['visible_therapist_id']!,
          _visibleTherapistIdMeta,
        ),
      );
    }
    if (data.containsKey('status')) {
      context.handle(
        _statusMeta,
        status.isAcceptableOrUnknown(data['status']!, _statusMeta),
      );
    } else if (isInserting) {
      context.missing(_statusMeta);
    }
    if (data.containsKey('revision')) {
      context.handle(
        _revisionMeta,
        revision.isAcceptableOrUnknown(data['revision']!, _revisionMeta),
      );
    }
    if (data.containsKey('visible')) {
      context.handle(
        _visibleMeta,
        visible.isAcceptableOrUnknown(data['visible']!, _visibleMeta),
      );
    }
    if (data.containsKey('fetched_at')) {
      context.handle(
        _fetchedAtMeta,
        fetchedAt.isAcceptableOrUnknown(data['fetched_at']!, _fetchedAtMeta),
      );
    } else if (isInserting) {
      context.missing(_fetchedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {inpatientNo};
  @override
  Patient map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return Patient(
      inpatientNo: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}inpatient_no'],
      )!,
      name: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}name'],
      )!,
      diagnosis: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}diagnosis'],
      ),
      adminNote: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}admin_note'],
      ),
      assignedTherapistId: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}assigned_therapist_id'],
      ),
      assignedTherapistName: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}assigned_therapist_name'],
      ),
      visibleTherapistId: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}visible_therapist_id'],
      ),
      status: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}status'],
      )!,
      revision: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}revision'],
      )!,
      visible: attachedDatabase.typeMapping.read(
        DriftSqlType.bool,
        data['${effectivePrefix}visible'],
      )!,
      fetchedAt: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}fetched_at'],
      )!,
    );
  }

  @override
  $PatientsTable createAlias(String alias) {
    return $PatientsTable(attachedDatabase, alias);
  }
}

class Patient extends DataClass implements Insertable<Patient> {
  final String inpatientNo;
  final String name;
  final String? diagnosis;
  final String? adminNote;
  final int? assignedTherapistId;

  /// 归属治疗师的**姓名**（服务端解析后下发）。
  ///
  /// ★ 2026-10-05 新增（本地库 schemaVersion 5 → 6）：患者详情页原来显示
  /// 「治疗师 #2」这种原始 id，对治疗师毫无意义。姓名是**服务端**拼出来的
  /// （本地没有 `user` 表，也**不应该**为了显示姓名去同步一张用户表 ——
  /// 那会把账号体系镜像到每台床旁设备上），所以服务端随患者一起下发。
  final String? assignedTherapistName;
  final int? visibleTherapistId;

  /// 2026-10-05：`visibility_state` 列**已删除**（本地库 schemaVersion 3 → 4）。
  ///
  /// 它缓存的是服务端 `v_patient_visibility.visibility_state`，而那个字段随临时指派
  /// 删除后**恒为 `'assigned'`**（服务端的"可见归属"现在直接等于 `assigned_therapist_id`）。
  /// 一个恒为常量的镜像列没有任何查询价值，继续留着只会让后来的人以为本地有归属状态机。
  /// 服务端仍返回该字段（为兼容既有客户端），但 App **不再读也不再写**它。
  final String status;

  /// 服务端 `revision`，用于推送时做乐观锁基线。
  final int revision;

  /// 本地是否仍在该治疗师的可见范围内。
  ///
  /// ★ 已出院患者会从"全科白板"消失，但本地**不能**直接删——否则历史记录会失去
  /// 患者信息（协议 §2）。用这个标记软隐藏。
  final bool visible;
  final String fetchedAt;
  const Patient({
    required this.inpatientNo,
    required this.name,
    this.diagnosis,
    this.adminNote,
    this.assignedTherapistId,
    this.assignedTherapistName,
    this.visibleTherapistId,
    required this.status,
    required this.revision,
    required this.visible,
    required this.fetchedAt,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['inpatient_no'] = Variable<String>(inpatientNo);
    map['name'] = Variable<String>(name);
    if (!nullToAbsent || diagnosis != null) {
      map['diagnosis'] = Variable<String>(diagnosis);
    }
    if (!nullToAbsent || adminNote != null) {
      map['admin_note'] = Variable<String>(adminNote);
    }
    if (!nullToAbsent || assignedTherapistId != null) {
      map['assigned_therapist_id'] = Variable<int>(assignedTherapistId);
    }
    if (!nullToAbsent || assignedTherapistName != null) {
      map['assigned_therapist_name'] = Variable<String>(assignedTherapistName);
    }
    if (!nullToAbsent || visibleTherapistId != null) {
      map['visible_therapist_id'] = Variable<int>(visibleTherapistId);
    }
    map['status'] = Variable<String>(status);
    map['revision'] = Variable<int>(revision);
    map['visible'] = Variable<bool>(visible);
    map['fetched_at'] = Variable<String>(fetchedAt);
    return map;
  }

  PatientsCompanion toCompanion(bool nullToAbsent) {
    return PatientsCompanion(
      inpatientNo: Value(inpatientNo),
      name: Value(name),
      diagnosis: diagnosis == null && nullToAbsent
          ? const Value.absent()
          : Value(diagnosis),
      adminNote: adminNote == null && nullToAbsent
          ? const Value.absent()
          : Value(adminNote),
      assignedTherapistId: assignedTherapistId == null && nullToAbsent
          ? const Value.absent()
          : Value(assignedTherapistId),
      assignedTherapistName: assignedTherapistName == null && nullToAbsent
          ? const Value.absent()
          : Value(assignedTherapistName),
      visibleTherapistId: visibleTherapistId == null && nullToAbsent
          ? const Value.absent()
          : Value(visibleTherapistId),
      status: Value(status),
      revision: Value(revision),
      visible: Value(visible),
      fetchedAt: Value(fetchedAt),
    );
  }

  factory Patient.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return Patient(
      inpatientNo: serializer.fromJson<String>(json['inpatientNo']),
      name: serializer.fromJson<String>(json['name']),
      diagnosis: serializer.fromJson<String?>(json['diagnosis']),
      adminNote: serializer.fromJson<String?>(json['adminNote']),
      assignedTherapistId: serializer.fromJson<int?>(
        json['assignedTherapistId'],
      ),
      assignedTherapistName: serializer.fromJson<String?>(
        json['assignedTherapistName'],
      ),
      visibleTherapistId: serializer.fromJson<int?>(json['visibleTherapistId']),
      status: serializer.fromJson<String>(json['status']),
      revision: serializer.fromJson<int>(json['revision']),
      visible: serializer.fromJson<bool>(json['visible']),
      fetchedAt: serializer.fromJson<String>(json['fetchedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'inpatientNo': serializer.toJson<String>(inpatientNo),
      'name': serializer.toJson<String>(name),
      'diagnosis': serializer.toJson<String?>(diagnosis),
      'adminNote': serializer.toJson<String?>(adminNote),
      'assignedTherapistId': serializer.toJson<int?>(assignedTherapistId),
      'assignedTherapistName': serializer.toJson<String?>(
        assignedTherapistName,
      ),
      'visibleTherapistId': serializer.toJson<int?>(visibleTherapistId),
      'status': serializer.toJson<String>(status),
      'revision': serializer.toJson<int>(revision),
      'visible': serializer.toJson<bool>(visible),
      'fetchedAt': serializer.toJson<String>(fetchedAt),
    };
  }

  Patient copyWith({
    String? inpatientNo,
    String? name,
    Value<String?> diagnosis = const Value.absent(),
    Value<String?> adminNote = const Value.absent(),
    Value<int?> assignedTherapistId = const Value.absent(),
    Value<String?> assignedTherapistName = const Value.absent(),
    Value<int?> visibleTherapistId = const Value.absent(),
    String? status,
    int? revision,
    bool? visible,
    String? fetchedAt,
  }) => Patient(
    inpatientNo: inpatientNo ?? this.inpatientNo,
    name: name ?? this.name,
    diagnosis: diagnosis.present ? diagnosis.value : this.diagnosis,
    adminNote: adminNote.present ? adminNote.value : this.adminNote,
    assignedTherapistId: assignedTherapistId.present
        ? assignedTherapistId.value
        : this.assignedTherapistId,
    assignedTherapistName: assignedTherapistName.present
        ? assignedTherapistName.value
        : this.assignedTherapistName,
    visibleTherapistId: visibleTherapistId.present
        ? visibleTherapistId.value
        : this.visibleTherapistId,
    status: status ?? this.status,
    revision: revision ?? this.revision,
    visible: visible ?? this.visible,
    fetchedAt: fetchedAt ?? this.fetchedAt,
  );
  Patient copyWithCompanion(PatientsCompanion data) {
    return Patient(
      inpatientNo: data.inpatientNo.present
          ? data.inpatientNo.value
          : this.inpatientNo,
      name: data.name.present ? data.name.value : this.name,
      diagnosis: data.diagnosis.present ? data.diagnosis.value : this.diagnosis,
      adminNote: data.adminNote.present ? data.adminNote.value : this.adminNote,
      assignedTherapistId: data.assignedTherapistId.present
          ? data.assignedTherapistId.value
          : this.assignedTherapistId,
      assignedTherapistName: data.assignedTherapistName.present
          ? data.assignedTherapistName.value
          : this.assignedTherapistName,
      visibleTherapistId: data.visibleTherapistId.present
          ? data.visibleTherapistId.value
          : this.visibleTherapistId,
      status: data.status.present ? data.status.value : this.status,
      revision: data.revision.present ? data.revision.value : this.revision,
      visible: data.visible.present ? data.visible.value : this.visible,
      fetchedAt: data.fetchedAt.present ? data.fetchedAt.value : this.fetchedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('Patient(')
          ..write('inpatientNo: $inpatientNo, ')
          ..write('name: $name, ')
          ..write('diagnosis: $diagnosis, ')
          ..write('adminNote: $adminNote, ')
          ..write('assignedTherapistId: $assignedTherapistId, ')
          ..write('assignedTherapistName: $assignedTherapistName, ')
          ..write('visibleTherapistId: $visibleTherapistId, ')
          ..write('status: $status, ')
          ..write('revision: $revision, ')
          ..write('visible: $visible, ')
          ..write('fetchedAt: $fetchedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
    inpatientNo,
    name,
    diagnosis,
    adminNote,
    assignedTherapistId,
    assignedTherapistName,
    visibleTherapistId,
    status,
    revision,
    visible,
    fetchedAt,
  );
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is Patient &&
          other.inpatientNo == this.inpatientNo &&
          other.name == this.name &&
          other.diagnosis == this.diagnosis &&
          other.adminNote == this.adminNote &&
          other.assignedTherapistId == this.assignedTherapistId &&
          other.assignedTherapistName == this.assignedTherapistName &&
          other.visibleTherapistId == this.visibleTherapistId &&
          other.status == this.status &&
          other.revision == this.revision &&
          other.visible == this.visible &&
          other.fetchedAt == this.fetchedAt);
}

class PatientsCompanion extends UpdateCompanion<Patient> {
  final Value<String> inpatientNo;
  final Value<String> name;
  final Value<String?> diagnosis;
  final Value<String?> adminNote;
  final Value<int?> assignedTherapistId;
  final Value<String?> assignedTherapistName;
  final Value<int?> visibleTherapistId;
  final Value<String> status;
  final Value<int> revision;
  final Value<bool> visible;
  final Value<String> fetchedAt;
  final Value<int> rowid;
  const PatientsCompanion({
    this.inpatientNo = const Value.absent(),
    this.name = const Value.absent(),
    this.diagnosis = const Value.absent(),
    this.adminNote = const Value.absent(),
    this.assignedTherapistId = const Value.absent(),
    this.assignedTherapistName = const Value.absent(),
    this.visibleTherapistId = const Value.absent(),
    this.status = const Value.absent(),
    this.revision = const Value.absent(),
    this.visible = const Value.absent(),
    this.fetchedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  PatientsCompanion.insert({
    required String inpatientNo,
    required String name,
    this.diagnosis = const Value.absent(),
    this.adminNote = const Value.absent(),
    this.assignedTherapistId = const Value.absent(),
    this.assignedTherapistName = const Value.absent(),
    this.visibleTherapistId = const Value.absent(),
    required String status,
    this.revision = const Value.absent(),
    this.visible = const Value.absent(),
    required String fetchedAt,
    this.rowid = const Value.absent(),
  }) : inpatientNo = Value(inpatientNo),
       name = Value(name),
       status = Value(status),
       fetchedAt = Value(fetchedAt);
  static Insertable<Patient> custom({
    Expression<String>? inpatientNo,
    Expression<String>? name,
    Expression<String>? diagnosis,
    Expression<String>? adminNote,
    Expression<int>? assignedTherapistId,
    Expression<String>? assignedTherapistName,
    Expression<int>? visibleTherapistId,
    Expression<String>? status,
    Expression<int>? revision,
    Expression<bool>? visible,
    Expression<String>? fetchedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (inpatientNo != null) 'inpatient_no': inpatientNo,
      if (name != null) 'name': name,
      if (diagnosis != null) 'diagnosis': diagnosis,
      if (adminNote != null) 'admin_note': adminNote,
      if (assignedTherapistId != null)
        'assigned_therapist_id': assignedTherapistId,
      if (assignedTherapistName != null)
        'assigned_therapist_name': assignedTherapistName,
      if (visibleTherapistId != null)
        'visible_therapist_id': visibleTherapistId,
      if (status != null) 'status': status,
      if (revision != null) 'revision': revision,
      if (visible != null) 'visible': visible,
      if (fetchedAt != null) 'fetched_at': fetchedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  PatientsCompanion copyWith({
    Value<String>? inpatientNo,
    Value<String>? name,
    Value<String?>? diagnosis,
    Value<String?>? adminNote,
    Value<int?>? assignedTherapistId,
    Value<String?>? assignedTherapistName,
    Value<int?>? visibleTherapistId,
    Value<String>? status,
    Value<int>? revision,
    Value<bool>? visible,
    Value<String>? fetchedAt,
    Value<int>? rowid,
  }) {
    return PatientsCompanion(
      inpatientNo: inpatientNo ?? this.inpatientNo,
      name: name ?? this.name,
      diagnosis: diagnosis ?? this.diagnosis,
      adminNote: adminNote ?? this.adminNote,
      assignedTherapistId: assignedTherapistId ?? this.assignedTherapistId,
      assignedTherapistName:
          assignedTherapistName ?? this.assignedTherapistName,
      visibleTherapistId: visibleTherapistId ?? this.visibleTherapistId,
      status: status ?? this.status,
      revision: revision ?? this.revision,
      visible: visible ?? this.visible,
      fetchedAt: fetchedAt ?? this.fetchedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (inpatientNo.present) {
      map['inpatient_no'] = Variable<String>(inpatientNo.value);
    }
    if (name.present) {
      map['name'] = Variable<String>(name.value);
    }
    if (diagnosis.present) {
      map['diagnosis'] = Variable<String>(diagnosis.value);
    }
    if (adminNote.present) {
      map['admin_note'] = Variable<String>(adminNote.value);
    }
    if (assignedTherapistId.present) {
      map['assigned_therapist_id'] = Variable<int>(assignedTherapistId.value);
    }
    if (assignedTherapistName.present) {
      map['assigned_therapist_name'] = Variable<String>(
        assignedTherapistName.value,
      );
    }
    if (visibleTherapistId.present) {
      map['visible_therapist_id'] = Variable<int>(visibleTherapistId.value);
    }
    if (status.present) {
      map['status'] = Variable<String>(status.value);
    }
    if (revision.present) {
      map['revision'] = Variable<int>(revision.value);
    }
    if (visible.present) {
      map['visible'] = Variable<bool>(visible.value);
    }
    if (fetchedAt.present) {
      map['fetched_at'] = Variable<String>(fetchedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('PatientsCompanion(')
          ..write('inpatientNo: $inpatientNo, ')
          ..write('name: $name, ')
          ..write('diagnosis: $diagnosis, ')
          ..write('adminNote: $adminNote, ')
          ..write('assignedTherapistId: $assignedTherapistId, ')
          ..write('assignedTherapistName: $assignedTherapistName, ')
          ..write('visibleTherapistId: $visibleTherapistId, ')
          ..write('status: $status, ')
          ..write('revision: $revision, ')
          ..write('visible: $visible, ')
          ..write('fetchedAt: $fetchedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $TreatmentRecordsTable extends TreatmentRecords
    with TableInfo<$TreatmentRecordsTable, TreatmentRecord> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $TreatmentRecordsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<int> id = GeneratedColumn<int>(
    'id',
    aliasedName,
    false,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _patientNoMeta = const VerificationMeta(
    'patientNo',
  );
  @override
  late final GeneratedColumn<String> patientNo = GeneratedColumn<String>(
    'patient_no',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _therapistIdMeta = const VerificationMeta(
    'therapistId',
  );
  @override
  late final GeneratedColumn<int> therapistId = GeneratedColumn<int>(
    'therapist_id',
    aliasedName,
    false,
    type: DriftSqlType.int,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _recordDateMeta = const VerificationMeta(
    'recordDate',
  );
  @override
  late final GeneratedColumn<String> recordDate = GeneratedColumn<String>(
    'record_date',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _disciplineMeta = const VerificationMeta(
    'discipline',
  );
  @override
  late final GeneratedColumn<String> discipline = GeneratedColumn<String>(
    'discipline',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _kindMeta = const VerificationMeta('kind');
  @override
  late final GeneratedColumn<String> kind = GeneratedColumn<String>(
    'kind',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _seqNoMeta = const VerificationMeta('seqNo');
  @override
  late final GeneratedColumn<int> seqNo = GeneratedColumn<int>(
    'seq_no',
    aliasedName,
    true,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _bodyJsonMeta = const VerificationMeta(
    'bodyJson',
  );
  @override
  late final GeneratedColumn<String> bodyJson = GeneratedColumn<String>(
    'body_json',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
    defaultValue: const Constant('{}'),
  );
  static const VerificationMeta _renderedTextMeta = const VerificationMeta(
    'renderedText',
  );
  @override
  late final GeneratedColumn<String> renderedText = GeneratedColumn<String>(
    'rendered_text',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
    defaultValue: const Constant(''),
  );
  static const VerificationMeta _noteMeta = const VerificationMeta('note');
  @override
  late final GeneratedColumn<String> note = GeneratedColumn<String>(
    'note',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _statusMeta = const VerificationMeta('status');
  @override
  late final GeneratedColumn<String> status = GeneratedColumn<String>(
    'status',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
    defaultValue: const Constant('draft'),
  );
  static const VerificationMeta _editCountMeta = const VerificationMeta(
    'editCount',
  );
  @override
  late final GeneratedColumn<int> editCount = GeneratedColumn<int>(
    'edit_count',
    aliasedName,
    false,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
    defaultValue: const Constant(0),
  );
  static const VerificationMeta _revisionMeta = const VerificationMeta(
    'revision',
  );
  @override
  late final GeneratedColumn<int> revision = GeneratedColumn<int>(
    'revision',
    aliasedName,
    false,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
    defaultValue: const Constant(0),
  );
  static const VerificationMeta _isTemporaryMeta = const VerificationMeta(
    'isTemporary',
  );
  @override
  late final GeneratedColumn<bool> isTemporary = GeneratedColumn<bool>(
    'is_temporary',
    aliasedName,
    false,
    type: DriftSqlType.bool,
    requiredDuringInsert: false,
    defaultConstraints: GeneratedColumn.constraintIsAlways(
      'CHECK ("is_temporary" IN (0, 1))',
    ),
    defaultValue: const Constant(false),
  );
  static const VerificationMeta _originalTherapistIdMeta =
      const VerificationMeta('originalTherapistId');
  @override
  late final GeneratedColumn<int> originalTherapistId = GeneratedColumn<int>(
    'original_therapist_id',
    aliasedName,
    true,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _clientUuidMeta = const VerificationMeta(
    'clientUuid',
  );
  @override
  late final GeneratedColumn<String> clientUuid = GeneratedColumn<String>(
    'client_uuid',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _syncStatusMeta = const VerificationMeta(
    'syncStatus',
  );
  @override
  late final GeneratedColumn<String> syncStatus = GeneratedColumn<String>(
    'sync_status',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
    defaultValue: const Constant('synced'),
  );
  @override
  List<GeneratedColumn> get $columns => [
    id,
    patientNo,
    therapistId,
    recordDate,
    discipline,
    kind,
    seqNo,
    bodyJson,
    renderedText,
    note,
    status,
    editCount,
    revision,
    isTemporary,
    originalTherapistId,
    clientUuid,
    syncStatus,
  ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'treatment_records';
  @override
  VerificationContext validateIntegrity(
    Insertable<TreatmentRecord> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    }
    if (data.containsKey('patient_no')) {
      context.handle(
        _patientNoMeta,
        patientNo.isAcceptableOrUnknown(data['patient_no']!, _patientNoMeta),
      );
    } else if (isInserting) {
      context.missing(_patientNoMeta);
    }
    if (data.containsKey('therapist_id')) {
      context.handle(
        _therapistIdMeta,
        therapistId.isAcceptableOrUnknown(
          data['therapist_id']!,
          _therapistIdMeta,
        ),
      );
    } else if (isInserting) {
      context.missing(_therapistIdMeta);
    }
    if (data.containsKey('record_date')) {
      context.handle(
        _recordDateMeta,
        recordDate.isAcceptableOrUnknown(data['record_date']!, _recordDateMeta),
      );
    } else if (isInserting) {
      context.missing(_recordDateMeta);
    }
    if (data.containsKey('discipline')) {
      context.handle(
        _disciplineMeta,
        discipline.isAcceptableOrUnknown(data['discipline']!, _disciplineMeta),
      );
    } else if (isInserting) {
      context.missing(_disciplineMeta);
    }
    if (data.containsKey('kind')) {
      context.handle(
        _kindMeta,
        kind.isAcceptableOrUnknown(data['kind']!, _kindMeta),
      );
    } else if (isInserting) {
      context.missing(_kindMeta);
    }
    if (data.containsKey('seq_no')) {
      context.handle(
        _seqNoMeta,
        seqNo.isAcceptableOrUnknown(data['seq_no']!, _seqNoMeta),
      );
    }
    if (data.containsKey('body_json')) {
      context.handle(
        _bodyJsonMeta,
        bodyJson.isAcceptableOrUnknown(data['body_json']!, _bodyJsonMeta),
      );
    }
    if (data.containsKey('rendered_text')) {
      context.handle(
        _renderedTextMeta,
        renderedText.isAcceptableOrUnknown(
          data['rendered_text']!,
          _renderedTextMeta,
        ),
      );
    }
    if (data.containsKey('note')) {
      context.handle(
        _noteMeta,
        note.isAcceptableOrUnknown(data['note']!, _noteMeta),
      );
    }
    if (data.containsKey('status')) {
      context.handle(
        _statusMeta,
        status.isAcceptableOrUnknown(data['status']!, _statusMeta),
      );
    }
    if (data.containsKey('edit_count')) {
      context.handle(
        _editCountMeta,
        editCount.isAcceptableOrUnknown(data['edit_count']!, _editCountMeta),
      );
    }
    if (data.containsKey('revision')) {
      context.handle(
        _revisionMeta,
        revision.isAcceptableOrUnknown(data['revision']!, _revisionMeta),
      );
    }
    if (data.containsKey('is_temporary')) {
      context.handle(
        _isTemporaryMeta,
        isTemporary.isAcceptableOrUnknown(
          data['is_temporary']!,
          _isTemporaryMeta,
        ),
      );
    }
    if (data.containsKey('original_therapist_id')) {
      context.handle(
        _originalTherapistIdMeta,
        originalTherapistId.isAcceptableOrUnknown(
          data['original_therapist_id']!,
          _originalTherapistIdMeta,
        ),
      );
    }
    if (data.containsKey('client_uuid')) {
      context.handle(
        _clientUuidMeta,
        clientUuid.isAcceptableOrUnknown(data['client_uuid']!, _clientUuidMeta),
      );
    }
    if (data.containsKey('sync_status')) {
      context.handle(
        _syncStatusMeta,
        syncStatus.isAcceptableOrUnknown(data['sync_status']!, _syncStatusMeta),
      );
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  TreatmentRecord map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return TreatmentRecord(
      id: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}id'],
      )!,
      patientNo: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}patient_no'],
      )!,
      therapistId: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}therapist_id'],
      )!,
      recordDate: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}record_date'],
      )!,
      discipline: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}discipline'],
      )!,
      kind: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}kind'],
      )!,
      seqNo: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}seq_no'],
      ),
      bodyJson: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}body_json'],
      )!,
      renderedText: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}rendered_text'],
      )!,
      note: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}note'],
      ),
      status: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}status'],
      )!,
      editCount: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}edit_count'],
      )!,
      revision: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}revision'],
      )!,
      isTemporary: attachedDatabase.typeMapping.read(
        DriftSqlType.bool,
        data['${effectivePrefix}is_temporary'],
      )!,
      originalTherapistId: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}original_therapist_id'],
      ),
      clientUuid: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}client_uuid'],
      ),
      syncStatus: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}sync_status'],
      )!,
    );
  }

  @override
  $TreatmentRecordsTable createAlias(String alias) {
    return $TreatmentRecordsTable(attachedDatabase, alias);
  }
}

class TreatmentRecord extends DataClass implements Insertable<TreatmentRecord> {
  final int id;
  final String patientNo;
  final int therapistId;
  final String recordDate;

  /// `PT` / `OT` / `ST_SW` / `ST_SP`（四大类）。
  final String discipline;

  /// `initial` / `daily` / `reassessment` / `discharge`（形态）。
  final String kind;

  /// 第几次**日常**记录；评估文书（首评/复评/出院小结）不占次数 → 为 null。
  final int? seqNo;

  /// 答案：`{field_key: value}`（键就是模板字段的 `key`）。
  ///
  /// 这是**唯一**的记录内容载体：服务端 `body` 原样存取，App 不再拆表。
  final String bodyJson;

  /// 服务端在落库时**冻结**的 SOAP 纯文本（时间轴/详情直接显示它）。
  ///
  /// 本地草稿也存一份客户端预览（见 `RecordRepository`），推送成功后会被
  /// 服务端返回的正式文本覆盖。
  final String renderedText;
  final String? note;
  final String status;
  final int editCount;
  final int revision;

  /// 2026-10-03 起"全科白板"，实测这两个字段恒为 false/NULL（协议 §10）。
  /// 保留只为与服务端字段一一对应，**不要**再用它做 UI 判断。
  final bool isTemporary;
  final int? originalTherapistId;
  final String? clientUuid;
  final String syncStatus;
  const TreatmentRecord({
    required this.id,
    required this.patientNo,
    required this.therapistId,
    required this.recordDate,
    required this.discipline,
    required this.kind,
    this.seqNo,
    required this.bodyJson,
    required this.renderedText,
    this.note,
    required this.status,
    required this.editCount,
    required this.revision,
    required this.isTemporary,
    this.originalTherapistId,
    this.clientUuid,
    required this.syncStatus,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<int>(id);
    map['patient_no'] = Variable<String>(patientNo);
    map['therapist_id'] = Variable<int>(therapistId);
    map['record_date'] = Variable<String>(recordDate);
    map['discipline'] = Variable<String>(discipline);
    map['kind'] = Variable<String>(kind);
    if (!nullToAbsent || seqNo != null) {
      map['seq_no'] = Variable<int>(seqNo);
    }
    map['body_json'] = Variable<String>(bodyJson);
    map['rendered_text'] = Variable<String>(renderedText);
    if (!nullToAbsent || note != null) {
      map['note'] = Variable<String>(note);
    }
    map['status'] = Variable<String>(status);
    map['edit_count'] = Variable<int>(editCount);
    map['revision'] = Variable<int>(revision);
    map['is_temporary'] = Variable<bool>(isTemporary);
    if (!nullToAbsent || originalTherapistId != null) {
      map['original_therapist_id'] = Variable<int>(originalTherapistId);
    }
    if (!nullToAbsent || clientUuid != null) {
      map['client_uuid'] = Variable<String>(clientUuid);
    }
    map['sync_status'] = Variable<String>(syncStatus);
    return map;
  }

  TreatmentRecordsCompanion toCompanion(bool nullToAbsent) {
    return TreatmentRecordsCompanion(
      id: Value(id),
      patientNo: Value(patientNo),
      therapistId: Value(therapistId),
      recordDate: Value(recordDate),
      discipline: Value(discipline),
      kind: Value(kind),
      seqNo: seqNo == null && nullToAbsent
          ? const Value.absent()
          : Value(seqNo),
      bodyJson: Value(bodyJson),
      renderedText: Value(renderedText),
      note: note == null && nullToAbsent ? const Value.absent() : Value(note),
      status: Value(status),
      editCount: Value(editCount),
      revision: Value(revision),
      isTemporary: Value(isTemporary),
      originalTherapistId: originalTherapistId == null && nullToAbsent
          ? const Value.absent()
          : Value(originalTherapistId),
      clientUuid: clientUuid == null && nullToAbsent
          ? const Value.absent()
          : Value(clientUuid),
      syncStatus: Value(syncStatus),
    );
  }

  factory TreatmentRecord.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return TreatmentRecord(
      id: serializer.fromJson<int>(json['id']),
      patientNo: serializer.fromJson<String>(json['patientNo']),
      therapistId: serializer.fromJson<int>(json['therapistId']),
      recordDate: serializer.fromJson<String>(json['recordDate']),
      discipline: serializer.fromJson<String>(json['discipline']),
      kind: serializer.fromJson<String>(json['kind']),
      seqNo: serializer.fromJson<int?>(json['seqNo']),
      bodyJson: serializer.fromJson<String>(json['bodyJson']),
      renderedText: serializer.fromJson<String>(json['renderedText']),
      note: serializer.fromJson<String?>(json['note']),
      status: serializer.fromJson<String>(json['status']),
      editCount: serializer.fromJson<int>(json['editCount']),
      revision: serializer.fromJson<int>(json['revision']),
      isTemporary: serializer.fromJson<bool>(json['isTemporary']),
      originalTherapistId: serializer.fromJson<int?>(
        json['originalTherapistId'],
      ),
      clientUuid: serializer.fromJson<String?>(json['clientUuid']),
      syncStatus: serializer.fromJson<String>(json['syncStatus']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<int>(id),
      'patientNo': serializer.toJson<String>(patientNo),
      'therapistId': serializer.toJson<int>(therapistId),
      'recordDate': serializer.toJson<String>(recordDate),
      'discipline': serializer.toJson<String>(discipline),
      'kind': serializer.toJson<String>(kind),
      'seqNo': serializer.toJson<int?>(seqNo),
      'bodyJson': serializer.toJson<String>(bodyJson),
      'renderedText': serializer.toJson<String>(renderedText),
      'note': serializer.toJson<String?>(note),
      'status': serializer.toJson<String>(status),
      'editCount': serializer.toJson<int>(editCount),
      'revision': serializer.toJson<int>(revision),
      'isTemporary': serializer.toJson<bool>(isTemporary),
      'originalTherapistId': serializer.toJson<int?>(originalTherapistId),
      'clientUuid': serializer.toJson<String?>(clientUuid),
      'syncStatus': serializer.toJson<String>(syncStatus),
    };
  }

  TreatmentRecord copyWith({
    int? id,
    String? patientNo,
    int? therapistId,
    String? recordDate,
    String? discipline,
    String? kind,
    Value<int?> seqNo = const Value.absent(),
    String? bodyJson,
    String? renderedText,
    Value<String?> note = const Value.absent(),
    String? status,
    int? editCount,
    int? revision,
    bool? isTemporary,
    Value<int?> originalTherapistId = const Value.absent(),
    Value<String?> clientUuid = const Value.absent(),
    String? syncStatus,
  }) => TreatmentRecord(
    id: id ?? this.id,
    patientNo: patientNo ?? this.patientNo,
    therapistId: therapistId ?? this.therapistId,
    recordDate: recordDate ?? this.recordDate,
    discipline: discipline ?? this.discipline,
    kind: kind ?? this.kind,
    seqNo: seqNo.present ? seqNo.value : this.seqNo,
    bodyJson: bodyJson ?? this.bodyJson,
    renderedText: renderedText ?? this.renderedText,
    note: note.present ? note.value : this.note,
    status: status ?? this.status,
    editCount: editCount ?? this.editCount,
    revision: revision ?? this.revision,
    isTemporary: isTemporary ?? this.isTemporary,
    originalTherapistId: originalTherapistId.present
        ? originalTherapistId.value
        : this.originalTherapistId,
    clientUuid: clientUuid.present ? clientUuid.value : this.clientUuid,
    syncStatus: syncStatus ?? this.syncStatus,
  );
  TreatmentRecord copyWithCompanion(TreatmentRecordsCompanion data) {
    return TreatmentRecord(
      id: data.id.present ? data.id.value : this.id,
      patientNo: data.patientNo.present ? data.patientNo.value : this.patientNo,
      therapistId: data.therapistId.present
          ? data.therapistId.value
          : this.therapistId,
      recordDate: data.recordDate.present
          ? data.recordDate.value
          : this.recordDate,
      discipline: data.discipline.present
          ? data.discipline.value
          : this.discipline,
      kind: data.kind.present ? data.kind.value : this.kind,
      seqNo: data.seqNo.present ? data.seqNo.value : this.seqNo,
      bodyJson: data.bodyJson.present ? data.bodyJson.value : this.bodyJson,
      renderedText: data.renderedText.present
          ? data.renderedText.value
          : this.renderedText,
      note: data.note.present ? data.note.value : this.note,
      status: data.status.present ? data.status.value : this.status,
      editCount: data.editCount.present ? data.editCount.value : this.editCount,
      revision: data.revision.present ? data.revision.value : this.revision,
      isTemporary: data.isTemporary.present
          ? data.isTemporary.value
          : this.isTemporary,
      originalTherapistId: data.originalTherapistId.present
          ? data.originalTherapistId.value
          : this.originalTherapistId,
      clientUuid: data.clientUuid.present
          ? data.clientUuid.value
          : this.clientUuid,
      syncStatus: data.syncStatus.present
          ? data.syncStatus.value
          : this.syncStatus,
    );
  }

  @override
  String toString() {
    return (StringBuffer('TreatmentRecord(')
          ..write('id: $id, ')
          ..write('patientNo: $patientNo, ')
          ..write('therapistId: $therapistId, ')
          ..write('recordDate: $recordDate, ')
          ..write('discipline: $discipline, ')
          ..write('kind: $kind, ')
          ..write('seqNo: $seqNo, ')
          ..write('bodyJson: $bodyJson, ')
          ..write('renderedText: $renderedText, ')
          ..write('note: $note, ')
          ..write('status: $status, ')
          ..write('editCount: $editCount, ')
          ..write('revision: $revision, ')
          ..write('isTemporary: $isTemporary, ')
          ..write('originalTherapistId: $originalTherapistId, ')
          ..write('clientUuid: $clientUuid, ')
          ..write('syncStatus: $syncStatus')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
    id,
    patientNo,
    therapistId,
    recordDate,
    discipline,
    kind,
    seqNo,
    bodyJson,
    renderedText,
    note,
    status,
    editCount,
    revision,
    isTemporary,
    originalTherapistId,
    clientUuid,
    syncStatus,
  );
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is TreatmentRecord &&
          other.id == this.id &&
          other.patientNo == this.patientNo &&
          other.therapistId == this.therapistId &&
          other.recordDate == this.recordDate &&
          other.discipline == this.discipline &&
          other.kind == this.kind &&
          other.seqNo == this.seqNo &&
          other.bodyJson == this.bodyJson &&
          other.renderedText == this.renderedText &&
          other.note == this.note &&
          other.status == this.status &&
          other.editCount == this.editCount &&
          other.revision == this.revision &&
          other.isTemporary == this.isTemporary &&
          other.originalTherapistId == this.originalTherapistId &&
          other.clientUuid == this.clientUuid &&
          other.syncStatus == this.syncStatus);
}

class TreatmentRecordsCompanion extends UpdateCompanion<TreatmentRecord> {
  final Value<int> id;
  final Value<String> patientNo;
  final Value<int> therapistId;
  final Value<String> recordDate;
  final Value<String> discipline;
  final Value<String> kind;
  final Value<int?> seqNo;
  final Value<String> bodyJson;
  final Value<String> renderedText;
  final Value<String?> note;
  final Value<String> status;
  final Value<int> editCount;
  final Value<int> revision;
  final Value<bool> isTemporary;
  final Value<int?> originalTherapistId;
  final Value<String?> clientUuid;
  final Value<String> syncStatus;
  const TreatmentRecordsCompanion({
    this.id = const Value.absent(),
    this.patientNo = const Value.absent(),
    this.therapistId = const Value.absent(),
    this.recordDate = const Value.absent(),
    this.discipline = const Value.absent(),
    this.kind = const Value.absent(),
    this.seqNo = const Value.absent(),
    this.bodyJson = const Value.absent(),
    this.renderedText = const Value.absent(),
    this.note = const Value.absent(),
    this.status = const Value.absent(),
    this.editCount = const Value.absent(),
    this.revision = const Value.absent(),
    this.isTemporary = const Value.absent(),
    this.originalTherapistId = const Value.absent(),
    this.clientUuid = const Value.absent(),
    this.syncStatus = const Value.absent(),
  });
  TreatmentRecordsCompanion.insert({
    this.id = const Value.absent(),
    required String patientNo,
    required int therapistId,
    required String recordDate,
    required String discipline,
    required String kind,
    this.seqNo = const Value.absent(),
    this.bodyJson = const Value.absent(),
    this.renderedText = const Value.absent(),
    this.note = const Value.absent(),
    this.status = const Value.absent(),
    this.editCount = const Value.absent(),
    this.revision = const Value.absent(),
    this.isTemporary = const Value.absent(),
    this.originalTherapistId = const Value.absent(),
    this.clientUuid = const Value.absent(),
    this.syncStatus = const Value.absent(),
  }) : patientNo = Value(patientNo),
       therapistId = Value(therapistId),
       recordDate = Value(recordDate),
       discipline = Value(discipline),
       kind = Value(kind);
  static Insertable<TreatmentRecord> custom({
    Expression<int>? id,
    Expression<String>? patientNo,
    Expression<int>? therapistId,
    Expression<String>? recordDate,
    Expression<String>? discipline,
    Expression<String>? kind,
    Expression<int>? seqNo,
    Expression<String>? bodyJson,
    Expression<String>? renderedText,
    Expression<String>? note,
    Expression<String>? status,
    Expression<int>? editCount,
    Expression<int>? revision,
    Expression<bool>? isTemporary,
    Expression<int>? originalTherapistId,
    Expression<String>? clientUuid,
    Expression<String>? syncStatus,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (patientNo != null) 'patient_no': patientNo,
      if (therapistId != null) 'therapist_id': therapistId,
      if (recordDate != null) 'record_date': recordDate,
      if (discipline != null) 'discipline': discipline,
      if (kind != null) 'kind': kind,
      if (seqNo != null) 'seq_no': seqNo,
      if (bodyJson != null) 'body_json': bodyJson,
      if (renderedText != null) 'rendered_text': renderedText,
      if (note != null) 'note': note,
      if (status != null) 'status': status,
      if (editCount != null) 'edit_count': editCount,
      if (revision != null) 'revision': revision,
      if (isTemporary != null) 'is_temporary': isTemporary,
      if (originalTherapistId != null)
        'original_therapist_id': originalTherapistId,
      if (clientUuid != null) 'client_uuid': clientUuid,
      if (syncStatus != null) 'sync_status': syncStatus,
    });
  }

  TreatmentRecordsCompanion copyWith({
    Value<int>? id,
    Value<String>? patientNo,
    Value<int>? therapistId,
    Value<String>? recordDate,
    Value<String>? discipline,
    Value<String>? kind,
    Value<int?>? seqNo,
    Value<String>? bodyJson,
    Value<String>? renderedText,
    Value<String?>? note,
    Value<String>? status,
    Value<int>? editCount,
    Value<int>? revision,
    Value<bool>? isTemporary,
    Value<int?>? originalTherapistId,
    Value<String?>? clientUuid,
    Value<String>? syncStatus,
  }) {
    return TreatmentRecordsCompanion(
      id: id ?? this.id,
      patientNo: patientNo ?? this.patientNo,
      therapistId: therapistId ?? this.therapistId,
      recordDate: recordDate ?? this.recordDate,
      discipline: discipline ?? this.discipline,
      kind: kind ?? this.kind,
      seqNo: seqNo ?? this.seqNo,
      bodyJson: bodyJson ?? this.bodyJson,
      renderedText: renderedText ?? this.renderedText,
      note: note ?? this.note,
      status: status ?? this.status,
      editCount: editCount ?? this.editCount,
      revision: revision ?? this.revision,
      isTemporary: isTemporary ?? this.isTemporary,
      originalTherapistId: originalTherapistId ?? this.originalTherapistId,
      clientUuid: clientUuid ?? this.clientUuid,
      syncStatus: syncStatus ?? this.syncStatus,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<int>(id.value);
    }
    if (patientNo.present) {
      map['patient_no'] = Variable<String>(patientNo.value);
    }
    if (therapistId.present) {
      map['therapist_id'] = Variable<int>(therapistId.value);
    }
    if (recordDate.present) {
      map['record_date'] = Variable<String>(recordDate.value);
    }
    if (discipline.present) {
      map['discipline'] = Variable<String>(discipline.value);
    }
    if (kind.present) {
      map['kind'] = Variable<String>(kind.value);
    }
    if (seqNo.present) {
      map['seq_no'] = Variable<int>(seqNo.value);
    }
    if (bodyJson.present) {
      map['body_json'] = Variable<String>(bodyJson.value);
    }
    if (renderedText.present) {
      map['rendered_text'] = Variable<String>(renderedText.value);
    }
    if (note.present) {
      map['note'] = Variable<String>(note.value);
    }
    if (status.present) {
      map['status'] = Variable<String>(status.value);
    }
    if (editCount.present) {
      map['edit_count'] = Variable<int>(editCount.value);
    }
    if (revision.present) {
      map['revision'] = Variable<int>(revision.value);
    }
    if (isTemporary.present) {
      map['is_temporary'] = Variable<bool>(isTemporary.value);
    }
    if (originalTherapistId.present) {
      map['original_therapist_id'] = Variable<int>(originalTherapistId.value);
    }
    if (clientUuid.present) {
      map['client_uuid'] = Variable<String>(clientUuid.value);
    }
    if (syncStatus.present) {
      map['sync_status'] = Variable<String>(syncStatus.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('TreatmentRecordsCompanion(')
          ..write('id: $id, ')
          ..write('patientNo: $patientNo, ')
          ..write('therapistId: $therapistId, ')
          ..write('recordDate: $recordDate, ')
          ..write('discipline: $discipline, ')
          ..write('kind: $kind, ')
          ..write('seqNo: $seqNo, ')
          ..write('bodyJson: $bodyJson, ')
          ..write('renderedText: $renderedText, ')
          ..write('note: $note, ')
          ..write('status: $status, ')
          ..write('editCount: $editCount, ')
          ..write('revision: $revision, ')
          ..write('isTemporary: $isTemporary, ')
          ..write('originalTherapistId: $originalTherapistId, ')
          ..write('clientUuid: $clientUuid, ')
          ..write('syncStatus: $syncStatus')
          ..write(')'))
        .toString();
  }
}

class $ChangeQueueTable extends ChangeQueue
    with TableInfo<$ChangeQueueTable, ChangeQueueData> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $ChangeQueueTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _clientUuidMeta = const VerificationMeta(
    'clientUuid',
  );
  @override
  late final GeneratedColumn<String> clientUuid = GeneratedColumn<String>(
    'client_uuid',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _entityMeta = const VerificationMeta('entity');
  @override
  late final GeneratedColumn<String> entity = GeneratedColumn<String>(
    'entity',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _opMeta = const VerificationMeta('op');
  @override
  late final GeneratedColumn<String> op = GeneratedColumn<String>(
    'op',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
    defaultValue: const Constant('insert'),
  );
  static const VerificationMeta _baseRevisionMeta = const VerificationMeta(
    'baseRevision',
  );
  @override
  late final GeneratedColumn<int> baseRevision = GeneratedColumn<int>(
    'base_revision',
    aliasedName,
    true,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _payloadJsonMeta = const VerificationMeta(
    'payloadJson',
  );
  @override
  late final GeneratedColumn<String> payloadJson = GeneratedColumn<String>(
    'payload_json',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _syncStatusMeta = const VerificationMeta(
    'syncStatus',
  );
  @override
  late final GeneratedColumn<String> syncStatus = GeneratedColumn<String>(
    'sync_status',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
    defaultValue: const Constant('pending'),
  );
  static const VerificationMeta _retryCountMeta = const VerificationMeta(
    'retryCount',
  );
  @override
  late final GeneratedColumn<int> retryCount = GeneratedColumn<int>(
    'retry_count',
    aliasedName,
    false,
    type: DriftSqlType.int,
    requiredDuringInsert: false,
    defaultValue: const Constant(0),
  );
  static const VerificationMeta _lastErrorMeta = const VerificationMeta(
    'lastError',
  );
  @override
  late final GeneratedColumn<String> lastError = GeneratedColumn<String>(
    'last_error',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  static const VerificationMeta _createdAtMeta = const VerificationMeta(
    'createdAt',
  );
  @override
  late final GeneratedColumn<String> createdAt = GeneratedColumn<String>(
    'created_at',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [
    clientUuid,
    entity,
    op,
    baseRevision,
    payloadJson,
    syncStatus,
    retryCount,
    lastError,
    createdAt,
  ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'change_queue';
  @override
  VerificationContext validateIntegrity(
    Insertable<ChangeQueueData> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('client_uuid')) {
      context.handle(
        _clientUuidMeta,
        clientUuid.isAcceptableOrUnknown(data['client_uuid']!, _clientUuidMeta),
      );
    } else if (isInserting) {
      context.missing(_clientUuidMeta);
    }
    if (data.containsKey('entity')) {
      context.handle(
        _entityMeta,
        entity.isAcceptableOrUnknown(data['entity']!, _entityMeta),
      );
    } else if (isInserting) {
      context.missing(_entityMeta);
    }
    if (data.containsKey('op')) {
      context.handle(_opMeta, op.isAcceptableOrUnknown(data['op']!, _opMeta));
    }
    if (data.containsKey('base_revision')) {
      context.handle(
        _baseRevisionMeta,
        baseRevision.isAcceptableOrUnknown(
          data['base_revision']!,
          _baseRevisionMeta,
        ),
      );
    }
    if (data.containsKey('payload_json')) {
      context.handle(
        _payloadJsonMeta,
        payloadJson.isAcceptableOrUnknown(
          data['payload_json']!,
          _payloadJsonMeta,
        ),
      );
    } else if (isInserting) {
      context.missing(_payloadJsonMeta);
    }
    if (data.containsKey('sync_status')) {
      context.handle(
        _syncStatusMeta,
        syncStatus.isAcceptableOrUnknown(data['sync_status']!, _syncStatusMeta),
      );
    }
    if (data.containsKey('retry_count')) {
      context.handle(
        _retryCountMeta,
        retryCount.isAcceptableOrUnknown(data['retry_count']!, _retryCountMeta),
      );
    }
    if (data.containsKey('last_error')) {
      context.handle(
        _lastErrorMeta,
        lastError.isAcceptableOrUnknown(data['last_error']!, _lastErrorMeta),
      );
    }
    if (data.containsKey('created_at')) {
      context.handle(
        _createdAtMeta,
        createdAt.isAcceptableOrUnknown(data['created_at']!, _createdAtMeta),
      );
    } else if (isInserting) {
      context.missing(_createdAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {clientUuid};
  @override
  ChangeQueueData map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return ChangeQueueData(
      clientUuid: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}client_uuid'],
      )!,
      entity: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}entity'],
      )!,
      op: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}op'],
      )!,
      baseRevision: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}base_revision'],
      ),
      payloadJson: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}payload_json'],
      )!,
      syncStatus: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}sync_status'],
      )!,
      retryCount: attachedDatabase.typeMapping.read(
        DriftSqlType.int,
        data['${effectivePrefix}retry_count'],
      )!,
      lastError: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}last_error'],
      ),
      createdAt: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}created_at'],
      )!,
    );
  }

  @override
  $ChangeQueueTable createAlias(String alias) {
    return $ChangeQueueTable(attachedDatabase, alias);
  }
}

class ChangeQueueData extends DataClass implements Insertable<ChangeQueueData> {
  final String clientUuid;
  final String entity;
  final String op;

  /// 乐观锁基线。**重试时保持为 null**——带上过期基线会被服务端判成冲突
  /// （`entity_prefers_server`），幂等就失效了（协议 §4.4 的 ★）。
  final int? baseRevision;

  /// 推送体（服务端 `SyncChangeIn.payload`）。
  final String payloadJson;
  final String syncStatus;
  final int retryCount;
  final String? lastError;
  final String createdAt;
  const ChangeQueueData({
    required this.clientUuid,
    required this.entity,
    required this.op,
    this.baseRevision,
    required this.payloadJson,
    required this.syncStatus,
    required this.retryCount,
    this.lastError,
    required this.createdAt,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['client_uuid'] = Variable<String>(clientUuid);
    map['entity'] = Variable<String>(entity);
    map['op'] = Variable<String>(op);
    if (!nullToAbsent || baseRevision != null) {
      map['base_revision'] = Variable<int>(baseRevision);
    }
    map['payload_json'] = Variable<String>(payloadJson);
    map['sync_status'] = Variable<String>(syncStatus);
    map['retry_count'] = Variable<int>(retryCount);
    if (!nullToAbsent || lastError != null) {
      map['last_error'] = Variable<String>(lastError);
    }
    map['created_at'] = Variable<String>(createdAt);
    return map;
  }

  ChangeQueueCompanion toCompanion(bool nullToAbsent) {
    return ChangeQueueCompanion(
      clientUuid: Value(clientUuid),
      entity: Value(entity),
      op: Value(op),
      baseRevision: baseRevision == null && nullToAbsent
          ? const Value.absent()
          : Value(baseRevision),
      payloadJson: Value(payloadJson),
      syncStatus: Value(syncStatus),
      retryCount: Value(retryCount),
      lastError: lastError == null && nullToAbsent
          ? const Value.absent()
          : Value(lastError),
      createdAt: Value(createdAt),
    );
  }

  factory ChangeQueueData.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return ChangeQueueData(
      clientUuid: serializer.fromJson<String>(json['clientUuid']),
      entity: serializer.fromJson<String>(json['entity']),
      op: serializer.fromJson<String>(json['op']),
      baseRevision: serializer.fromJson<int?>(json['baseRevision']),
      payloadJson: serializer.fromJson<String>(json['payloadJson']),
      syncStatus: serializer.fromJson<String>(json['syncStatus']),
      retryCount: serializer.fromJson<int>(json['retryCount']),
      lastError: serializer.fromJson<String?>(json['lastError']),
      createdAt: serializer.fromJson<String>(json['createdAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'clientUuid': serializer.toJson<String>(clientUuid),
      'entity': serializer.toJson<String>(entity),
      'op': serializer.toJson<String>(op),
      'baseRevision': serializer.toJson<int?>(baseRevision),
      'payloadJson': serializer.toJson<String>(payloadJson),
      'syncStatus': serializer.toJson<String>(syncStatus),
      'retryCount': serializer.toJson<int>(retryCount),
      'lastError': serializer.toJson<String?>(lastError),
      'createdAt': serializer.toJson<String>(createdAt),
    };
  }

  ChangeQueueData copyWith({
    String? clientUuid,
    String? entity,
    String? op,
    Value<int?> baseRevision = const Value.absent(),
    String? payloadJson,
    String? syncStatus,
    int? retryCount,
    Value<String?> lastError = const Value.absent(),
    String? createdAt,
  }) => ChangeQueueData(
    clientUuid: clientUuid ?? this.clientUuid,
    entity: entity ?? this.entity,
    op: op ?? this.op,
    baseRevision: baseRevision.present ? baseRevision.value : this.baseRevision,
    payloadJson: payloadJson ?? this.payloadJson,
    syncStatus: syncStatus ?? this.syncStatus,
    retryCount: retryCount ?? this.retryCount,
    lastError: lastError.present ? lastError.value : this.lastError,
    createdAt: createdAt ?? this.createdAt,
  );
  ChangeQueueData copyWithCompanion(ChangeQueueCompanion data) {
    return ChangeQueueData(
      clientUuid: data.clientUuid.present
          ? data.clientUuid.value
          : this.clientUuid,
      entity: data.entity.present ? data.entity.value : this.entity,
      op: data.op.present ? data.op.value : this.op,
      baseRevision: data.baseRevision.present
          ? data.baseRevision.value
          : this.baseRevision,
      payloadJson: data.payloadJson.present
          ? data.payloadJson.value
          : this.payloadJson,
      syncStatus: data.syncStatus.present
          ? data.syncStatus.value
          : this.syncStatus,
      retryCount: data.retryCount.present
          ? data.retryCount.value
          : this.retryCount,
      lastError: data.lastError.present ? data.lastError.value : this.lastError,
      createdAt: data.createdAt.present ? data.createdAt.value : this.createdAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('ChangeQueueData(')
          ..write('clientUuid: $clientUuid, ')
          ..write('entity: $entity, ')
          ..write('op: $op, ')
          ..write('baseRevision: $baseRevision, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('syncStatus: $syncStatus, ')
          ..write('retryCount: $retryCount, ')
          ..write('lastError: $lastError, ')
          ..write('createdAt: $createdAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
    clientUuid,
    entity,
    op,
    baseRevision,
    payloadJson,
    syncStatus,
    retryCount,
    lastError,
    createdAt,
  );
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is ChangeQueueData &&
          other.clientUuid == this.clientUuid &&
          other.entity == this.entity &&
          other.op == this.op &&
          other.baseRevision == this.baseRevision &&
          other.payloadJson == this.payloadJson &&
          other.syncStatus == this.syncStatus &&
          other.retryCount == this.retryCount &&
          other.lastError == this.lastError &&
          other.createdAt == this.createdAt);
}

class ChangeQueueCompanion extends UpdateCompanion<ChangeQueueData> {
  final Value<String> clientUuid;
  final Value<String> entity;
  final Value<String> op;
  final Value<int?> baseRevision;
  final Value<String> payloadJson;
  final Value<String> syncStatus;
  final Value<int> retryCount;
  final Value<String?> lastError;
  final Value<String> createdAt;
  final Value<int> rowid;
  const ChangeQueueCompanion({
    this.clientUuid = const Value.absent(),
    this.entity = const Value.absent(),
    this.op = const Value.absent(),
    this.baseRevision = const Value.absent(),
    this.payloadJson = const Value.absent(),
    this.syncStatus = const Value.absent(),
    this.retryCount = const Value.absent(),
    this.lastError = const Value.absent(),
    this.createdAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  ChangeQueueCompanion.insert({
    required String clientUuid,
    required String entity,
    this.op = const Value.absent(),
    this.baseRevision = const Value.absent(),
    required String payloadJson,
    this.syncStatus = const Value.absent(),
    this.retryCount = const Value.absent(),
    this.lastError = const Value.absent(),
    required String createdAt,
    this.rowid = const Value.absent(),
  }) : clientUuid = Value(clientUuid),
       entity = Value(entity),
       payloadJson = Value(payloadJson),
       createdAt = Value(createdAt);
  static Insertable<ChangeQueueData> custom({
    Expression<String>? clientUuid,
    Expression<String>? entity,
    Expression<String>? op,
    Expression<int>? baseRevision,
    Expression<String>? payloadJson,
    Expression<String>? syncStatus,
    Expression<int>? retryCount,
    Expression<String>? lastError,
    Expression<String>? createdAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (clientUuid != null) 'client_uuid': clientUuid,
      if (entity != null) 'entity': entity,
      if (op != null) 'op': op,
      if (baseRevision != null) 'base_revision': baseRevision,
      if (payloadJson != null) 'payload_json': payloadJson,
      if (syncStatus != null) 'sync_status': syncStatus,
      if (retryCount != null) 'retry_count': retryCount,
      if (lastError != null) 'last_error': lastError,
      if (createdAt != null) 'created_at': createdAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  ChangeQueueCompanion copyWith({
    Value<String>? clientUuid,
    Value<String>? entity,
    Value<String>? op,
    Value<int?>? baseRevision,
    Value<String>? payloadJson,
    Value<String>? syncStatus,
    Value<int>? retryCount,
    Value<String?>? lastError,
    Value<String>? createdAt,
    Value<int>? rowid,
  }) {
    return ChangeQueueCompanion(
      clientUuid: clientUuid ?? this.clientUuid,
      entity: entity ?? this.entity,
      op: op ?? this.op,
      baseRevision: baseRevision ?? this.baseRevision,
      payloadJson: payloadJson ?? this.payloadJson,
      syncStatus: syncStatus ?? this.syncStatus,
      retryCount: retryCount ?? this.retryCount,
      lastError: lastError ?? this.lastError,
      createdAt: createdAt ?? this.createdAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (clientUuid.present) {
      map['client_uuid'] = Variable<String>(clientUuid.value);
    }
    if (entity.present) {
      map['entity'] = Variable<String>(entity.value);
    }
    if (op.present) {
      map['op'] = Variable<String>(op.value);
    }
    if (baseRevision.present) {
      map['base_revision'] = Variable<int>(baseRevision.value);
    }
    if (payloadJson.present) {
      map['payload_json'] = Variable<String>(payloadJson.value);
    }
    if (syncStatus.present) {
      map['sync_status'] = Variable<String>(syncStatus.value);
    }
    if (retryCount.present) {
      map['retry_count'] = Variable<int>(retryCount.value);
    }
    if (lastError.present) {
      map['last_error'] = Variable<String>(lastError.value);
    }
    if (createdAt.present) {
      map['created_at'] = Variable<String>(createdAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('ChangeQueueCompanion(')
          ..write('clientUuid: $clientUuid, ')
          ..write('entity: $entity, ')
          ..write('op: $op, ')
          ..write('baseRevision: $baseRevision, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('syncStatus: $syncStatus, ')
          ..write('retryCount: $retryCount, ')
          ..write('lastError: $lastError, ')
          ..write('createdAt: $createdAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $SyncStateTable extends SyncState
    with TableInfo<$SyncStateTable, SyncStateData> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $SyncStateTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _keyMeta = const VerificationMeta('key');
  @override
  late final GeneratedColumn<String> key = GeneratedColumn<String>(
    'key',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _valueMeta = const VerificationMeta('value');
  @override
  late final GeneratedColumn<String> value = GeneratedColumn<String>(
    'value',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  @override
  List<GeneratedColumn> get $columns => [key, value];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'sync_state';
  @override
  VerificationContext validateIntegrity(
    Insertable<SyncStateData> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('key')) {
      context.handle(
        _keyMeta,
        key.isAcceptableOrUnknown(data['key']!, _keyMeta),
      );
    } else if (isInserting) {
      context.missing(_keyMeta);
    }
    if (data.containsKey('value')) {
      context.handle(
        _valueMeta,
        value.isAcceptableOrUnknown(data['value']!, _valueMeta),
      );
    } else if (isInserting) {
      context.missing(_valueMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {key};
  @override
  SyncStateData map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return SyncStateData(
      key: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}key'],
      )!,
      value: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}value'],
      )!,
    );
  }

  @override
  $SyncStateTable createAlias(String alias) {
    return $SyncStateTable(attachedDatabase, alias);
  }
}

class SyncStateData extends DataClass implements Insertable<SyncStateData> {
  final String key;
  final String value;
  const SyncStateData({required this.key, required this.value});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['key'] = Variable<String>(key);
    map['value'] = Variable<String>(value);
    return map;
  }

  SyncStateCompanion toCompanion(bool nullToAbsent) {
    return SyncStateCompanion(key: Value(key), value: Value(value));
  }

  factory SyncStateData.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return SyncStateData(
      key: serializer.fromJson<String>(json['key']),
      value: serializer.fromJson<String>(json['value']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'key': serializer.toJson<String>(key),
      'value': serializer.toJson<String>(value),
    };
  }

  SyncStateData copyWith({String? key, String? value}) =>
      SyncStateData(key: key ?? this.key, value: value ?? this.value);
  SyncStateData copyWithCompanion(SyncStateCompanion data) {
    return SyncStateData(
      key: data.key.present ? data.key.value : this.key,
      value: data.value.present ? data.value.value : this.value,
    );
  }

  @override
  String toString() {
    return (StringBuffer('SyncStateData(')
          ..write('key: $key, ')
          ..write('value: $value')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(key, value);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is SyncStateData &&
          other.key == this.key &&
          other.value == this.value);
}

class SyncStateCompanion extends UpdateCompanion<SyncStateData> {
  final Value<String> key;
  final Value<String> value;
  final Value<int> rowid;
  const SyncStateCompanion({
    this.key = const Value.absent(),
    this.value = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  SyncStateCompanion.insert({
    required String key,
    required String value,
    this.rowid = const Value.absent(),
  }) : key = Value(key),
       value = Value(value);
  static Insertable<SyncStateData> custom({
    Expression<String>? key,
    Expression<String>? value,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (key != null) 'key': key,
      if (value != null) 'value': value,
      if (rowid != null) 'rowid': rowid,
    });
  }

  SyncStateCompanion copyWith({
    Value<String>? key,
    Value<String>? value,
    Value<int>? rowid,
  }) {
    return SyncStateCompanion(
      key: key ?? this.key,
      value: value ?? this.value,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (key.present) {
      map['key'] = Variable<String>(key.value);
    }
    if (value.present) {
      map['value'] = Variable<String>(value.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('SyncStateCompanion(')
          ..write('key: $key, ')
          ..write('value: $value, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $RefCacheTable extends RefCache
    with TableInfo<$RefCacheTable, RefCacheData> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $RefCacheTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _keyMeta = const VerificationMeta('key');
  @override
  late final GeneratedColumn<String> key = GeneratedColumn<String>(
    'key',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _payloadJsonMeta = const VerificationMeta(
    'payloadJson',
  );
  @override
  late final GeneratedColumn<String> payloadJson = GeneratedColumn<String>(
    'payload_json',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _fetchedAtMeta = const VerificationMeta(
    'fetchedAt',
  );
  @override
  late final GeneratedColumn<String> fetchedAt = GeneratedColumn<String>(
    'fetched_at',
    aliasedName,
    false,
    type: DriftSqlType.string,
    requiredDuringInsert: true,
  );
  static const VerificationMeta _etagMeta = const VerificationMeta('etag');
  @override
  late final GeneratedColumn<String> etag = GeneratedColumn<String>(
    'etag',
    aliasedName,
    true,
    type: DriftSqlType.string,
    requiredDuringInsert: false,
  );
  @override
  List<GeneratedColumn> get $columns => [key, payloadJson, fetchedAt, etag];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'ref_cache';
  @override
  VerificationContext validateIntegrity(
    Insertable<RefCacheData> instance, {
    bool isInserting = false,
  }) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('key')) {
      context.handle(
        _keyMeta,
        key.isAcceptableOrUnknown(data['key']!, _keyMeta),
      );
    } else if (isInserting) {
      context.missing(_keyMeta);
    }
    if (data.containsKey('payload_json')) {
      context.handle(
        _payloadJsonMeta,
        payloadJson.isAcceptableOrUnknown(
          data['payload_json']!,
          _payloadJsonMeta,
        ),
      );
    } else if (isInserting) {
      context.missing(_payloadJsonMeta);
    }
    if (data.containsKey('fetched_at')) {
      context.handle(
        _fetchedAtMeta,
        fetchedAt.isAcceptableOrUnknown(data['fetched_at']!, _fetchedAtMeta),
      );
    } else if (isInserting) {
      context.missing(_fetchedAtMeta);
    }
    if (data.containsKey('etag')) {
      context.handle(
        _etagMeta,
        etag.isAcceptableOrUnknown(data['etag']!, _etagMeta),
      );
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {key};
  @override
  RefCacheData map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return RefCacheData(
      key: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}key'],
      )!,
      payloadJson: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}payload_json'],
      )!,
      fetchedAt: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}fetched_at'],
      )!,
      etag: attachedDatabase.typeMapping.read(
        DriftSqlType.string,
        data['${effectivePrefix}etag'],
      ),
    );
  }

  @override
  $RefCacheTable createAlias(String alias) {
    return $RefCacheTable(attachedDatabase, alias);
  }
}

class RefCacheData extends DataClass implements Insertable<RefCacheData> {
  /// 如 `dict_tree`、`options:side`、`templates`、`response_defs`。
  final String key;
  final String payloadJson;
  final String fetchedAt;
  final String? etag;
  const RefCacheData({
    required this.key,
    required this.payloadJson,
    required this.fetchedAt,
    this.etag,
  });
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['key'] = Variable<String>(key);
    map['payload_json'] = Variable<String>(payloadJson);
    map['fetched_at'] = Variable<String>(fetchedAt);
    if (!nullToAbsent || etag != null) {
      map['etag'] = Variable<String>(etag);
    }
    return map;
  }

  RefCacheCompanion toCompanion(bool nullToAbsent) {
    return RefCacheCompanion(
      key: Value(key),
      payloadJson: Value(payloadJson),
      fetchedAt: Value(fetchedAt),
      etag: etag == null && nullToAbsent ? const Value.absent() : Value(etag),
    );
  }

  factory RefCacheData.fromJson(
    Map<String, dynamic> json, {
    ValueSerializer? serializer,
  }) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return RefCacheData(
      key: serializer.fromJson<String>(json['key']),
      payloadJson: serializer.fromJson<String>(json['payloadJson']),
      fetchedAt: serializer.fromJson<String>(json['fetchedAt']),
      etag: serializer.fromJson<String?>(json['etag']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'key': serializer.toJson<String>(key),
      'payloadJson': serializer.toJson<String>(payloadJson),
      'fetchedAt': serializer.toJson<String>(fetchedAt),
      'etag': serializer.toJson<String?>(etag),
    };
  }

  RefCacheData copyWith({
    String? key,
    String? payloadJson,
    String? fetchedAt,
    Value<String?> etag = const Value.absent(),
  }) => RefCacheData(
    key: key ?? this.key,
    payloadJson: payloadJson ?? this.payloadJson,
    fetchedAt: fetchedAt ?? this.fetchedAt,
    etag: etag.present ? etag.value : this.etag,
  );
  RefCacheData copyWithCompanion(RefCacheCompanion data) {
    return RefCacheData(
      key: data.key.present ? data.key.value : this.key,
      payloadJson: data.payloadJson.present
          ? data.payloadJson.value
          : this.payloadJson,
      fetchedAt: data.fetchedAt.present ? data.fetchedAt.value : this.fetchedAt,
      etag: data.etag.present ? data.etag.value : this.etag,
    );
  }

  @override
  String toString() {
    return (StringBuffer('RefCacheData(')
          ..write('key: $key, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('fetchedAt: $fetchedAt, ')
          ..write('etag: $etag')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(key, payloadJson, fetchedAt, etag);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is RefCacheData &&
          other.key == this.key &&
          other.payloadJson == this.payloadJson &&
          other.fetchedAt == this.fetchedAt &&
          other.etag == this.etag);
}

class RefCacheCompanion extends UpdateCompanion<RefCacheData> {
  final Value<String> key;
  final Value<String> payloadJson;
  final Value<String> fetchedAt;
  final Value<String?> etag;
  final Value<int> rowid;
  const RefCacheCompanion({
    this.key = const Value.absent(),
    this.payloadJson = const Value.absent(),
    this.fetchedAt = const Value.absent(),
    this.etag = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  RefCacheCompanion.insert({
    required String key,
    required String payloadJson,
    required String fetchedAt,
    this.etag = const Value.absent(),
    this.rowid = const Value.absent(),
  }) : key = Value(key),
       payloadJson = Value(payloadJson),
       fetchedAt = Value(fetchedAt);
  static Insertable<RefCacheData> custom({
    Expression<String>? key,
    Expression<String>? payloadJson,
    Expression<String>? fetchedAt,
    Expression<String>? etag,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (key != null) 'key': key,
      if (payloadJson != null) 'payload_json': payloadJson,
      if (fetchedAt != null) 'fetched_at': fetchedAt,
      if (etag != null) 'etag': etag,
      if (rowid != null) 'rowid': rowid,
    });
  }

  RefCacheCompanion copyWith({
    Value<String>? key,
    Value<String>? payloadJson,
    Value<String>? fetchedAt,
    Value<String?>? etag,
    Value<int>? rowid,
  }) {
    return RefCacheCompanion(
      key: key ?? this.key,
      payloadJson: payloadJson ?? this.payloadJson,
      fetchedAt: fetchedAt ?? this.fetchedAt,
      etag: etag ?? this.etag,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (key.present) {
      map['key'] = Variable<String>(key.value);
    }
    if (payloadJson.present) {
      map['payload_json'] = Variable<String>(payloadJson.value);
    }
    if (fetchedAt.present) {
      map['fetched_at'] = Variable<String>(fetchedAt.value);
    }
    if (etag.present) {
      map['etag'] = Variable<String>(etag.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('RefCacheCompanion(')
          ..write('key: $key, ')
          ..write('payloadJson: $payloadJson, ')
          ..write('fetchedAt: $fetchedAt, ')
          ..write('etag: $etag, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

abstract class _$AppDatabase extends GeneratedDatabase {
  _$AppDatabase(QueryExecutor e) : super(e);
  $AppDatabaseManager get managers => $AppDatabaseManager(this);
  late final $PatientsTable patients = $PatientsTable(this);
  late final $TreatmentRecordsTable treatmentRecords = $TreatmentRecordsTable(
    this,
  );
  late final $ChangeQueueTable changeQueue = $ChangeQueueTable(this);
  late final $SyncStateTable syncState = $SyncStateTable(this);
  late final $RefCacheTable refCache = $RefCacheTable(this);
  @override
  Iterable<TableInfo<Table, Object?>> get allTables =>
      allSchemaEntities.whereType<TableInfo<Table, Object?>>();
  @override
  List<DatabaseSchemaEntity> get allSchemaEntities => [
    patients,
    treatmentRecords,
    changeQueue,
    syncState,
    refCache,
  ];
}

typedef $$PatientsTableCreateCompanionBuilder = PatientsCompanion Function({
  required String inpatientNo,
  required String name,
  Value<String?> diagnosis,
  Value<String?> adminNote,
  Value<int?> assignedTherapistId,
  Value<String?> assignedTherapistName,
  Value<int?> visibleTherapistId,
  required String status,
  Value<int> revision,
  Value<bool> visible,
  required String fetchedAt,
  Value<int> rowid,
});
typedef $$PatientsTableUpdateCompanionBuilder = PatientsCompanion Function({
  Value<String> inpatientNo,
  Value<String> name,
  Value<String?> diagnosis,
  Value<String?> adminNote,
  Value<int?> assignedTherapistId,
  Value<String?> assignedTherapistName,
  Value<int?> visibleTherapistId,
  Value<String> status,
  Value<int> revision,
  Value<bool> visible,
  Value<String> fetchedAt,
  Value<int> rowid,
});

class $$PatientsTableFilterComposer
    extends Composer<_$AppDatabase, $PatientsTable> {
  $$PatientsTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get inpatientNo => $composableBuilder(
    column: $table.inpatientNo,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get name => $composableBuilder(
    column: $table.name,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get diagnosis => $composableBuilder(
    column: $table.diagnosis,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get adminNote => $composableBuilder(
    column: $table.adminNote,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<int> get assignedTherapistId => $composableBuilder(
    column: $table.assignedTherapistId,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get assignedTherapistName => $composableBuilder(
    column: $table.assignedTherapistName,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<int> get visibleTherapistId => $composableBuilder(
    column: $table.visibleTherapistId,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get status => $composableBuilder(
    column: $table.status,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<int> get revision => $composableBuilder(
    column: $table.revision,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<bool> get visible => $composableBuilder(
    column: $table.visible,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get fetchedAt => $composableBuilder(
    column: $table.fetchedAt,
    builder: (column) => ColumnFilters(column),
  );
}

class $$PatientsTableOrderingComposer
    extends Composer<_$AppDatabase, $PatientsTable> {
  $$PatientsTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get inpatientNo => $composableBuilder(
    column: $table.inpatientNo,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get name => $composableBuilder(
    column: $table.name,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get diagnosis => $composableBuilder(
    column: $table.diagnosis,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get adminNote => $composableBuilder(
    column: $table.adminNote,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<int> get assignedTherapistId => $composableBuilder(
    column: $table.assignedTherapistId,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get assignedTherapistName => $composableBuilder(
    column: $table.assignedTherapistName,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<int> get visibleTherapistId => $composableBuilder(
    column: $table.visibleTherapistId,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get status => $composableBuilder(
    column: $table.status,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<int> get revision => $composableBuilder(
    column: $table.revision,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<bool> get visible => $composableBuilder(
    column: $table.visible,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get fetchedAt => $composableBuilder(
    column: $table.fetchedAt,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$PatientsTableAnnotationComposer
    extends Composer<_$AppDatabase, $PatientsTable> {
  $$PatientsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get inpatientNo => $composableBuilder(
    column: $table.inpatientNo,
    builder: (column) => column,
  );

  GeneratedColumn<String> get name =>
      $composableBuilder(column: $table.name, builder: (column) => column);

  GeneratedColumn<String> get diagnosis =>
      $composableBuilder(column: $table.diagnosis, builder: (column) => column);

  GeneratedColumn<String> get adminNote =>
      $composableBuilder(column: $table.adminNote, builder: (column) => column);

  GeneratedColumn<int> get assignedTherapistId => $composableBuilder(
    column: $table.assignedTherapistId,
    builder: (column) => column,
  );

  GeneratedColumn<String> get assignedTherapistName => $composableBuilder(
    column: $table.assignedTherapistName,
    builder: (column) => column,
  );

  GeneratedColumn<int> get visibleTherapistId => $composableBuilder(
    column: $table.visibleTherapistId,
    builder: (column) => column,
  );

  GeneratedColumn<String> get status =>
      $composableBuilder(column: $table.status, builder: (column) => column);

  GeneratedColumn<int> get revision =>
      $composableBuilder(column: $table.revision, builder: (column) => column);

  GeneratedColumn<bool> get visible =>
      $composableBuilder(column: $table.visible, builder: (column) => column);

  GeneratedColumn<String> get fetchedAt =>
      $composableBuilder(column: $table.fetchedAt, builder: (column) => column);
}

class $$PatientsTableTableManager
    extends
        RootTableManager<
          _$AppDatabase,
          $PatientsTable,
          Patient,
          $$PatientsTableFilterComposer,
          $$PatientsTableOrderingComposer,
          $$PatientsTableAnnotationComposer,
          $$PatientsTableCreateCompanionBuilder,
          $$PatientsTableUpdateCompanionBuilder,
          (Patient, BaseReferences<_$AppDatabase, $PatientsTable, Patient>),
          Patient,
          PrefetchHooks Function()
        > {
  $$PatientsTableTableManager(_$AppDatabase db, $PatientsTable table)
    : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$PatientsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$PatientsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$PatientsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<String> inpatientNo = const Value.absent(),
                Value<String> name = const Value.absent(),
                Value<String?> diagnosis = const Value.absent(),
                Value<String?> adminNote = const Value.absent(),
                Value<int?> assignedTherapistId = const Value.absent(),
                Value<String?> assignedTherapistName = const Value.absent(),
                Value<int?> visibleTherapistId = const Value.absent(),
                Value<String> status = const Value.absent(),
                Value<int> revision = const Value.absent(),
                Value<bool> visible = const Value.absent(),
                Value<String> fetchedAt = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => PatientsCompanion(
                inpatientNo: inpatientNo,
                name: name,
                diagnosis: diagnosis,
                adminNote: adminNote,
                assignedTherapistId: assignedTherapistId,
                assignedTherapistName: assignedTherapistName,
                visibleTherapistId: visibleTherapistId,
                status: status,
                revision: revision,
                visible: visible,
                fetchedAt: fetchedAt,
                rowid: rowid,
              ),
          createCompanionCallback:
              ({
                required String inpatientNo,
                required String name,
                Value<String?> diagnosis = const Value.absent(),
                Value<String?> adminNote = const Value.absent(),
                Value<int?> assignedTherapistId = const Value.absent(),
                Value<String?> assignedTherapistName = const Value.absent(),
                Value<int?> visibleTherapistId = const Value.absent(),
                required String status,
                Value<int> revision = const Value.absent(),
                Value<bool> visible = const Value.absent(),
                required String fetchedAt,
                Value<int> rowid = const Value.absent(),
              }) => PatientsCompanion.insert(
                inpatientNo: inpatientNo,
                name: name,
                diagnosis: diagnosis,
                adminNote: adminNote,
                assignedTherapistId: assignedTherapistId,
                assignedTherapistName: assignedTherapistName,
                visibleTherapistId: visibleTherapistId,
                status: status,
                revision: revision,
                visible: visible,
                fetchedAt: fetchedAt,
                rowid: rowid,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$PatientsTable, Patient>(table),
                  BaseReferences<_$AppDatabase, $PatientsTable, Patient>(
                    db,
                    table,
                    e,
                  ),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$PatientsTableProcessedTableManager =
    ProcessedTableManager<
      _$AppDatabase,
      $PatientsTable,
      Patient,
      $$PatientsTableFilterComposer,
      $$PatientsTableOrderingComposer,
      $$PatientsTableAnnotationComposer,
      $$PatientsTableCreateCompanionBuilder,
      $$PatientsTableUpdateCompanionBuilder,
      (Patient, BaseReferences<_$AppDatabase, $PatientsTable, Patient>),
      Patient,
      PrefetchHooks Function()
    >;
typedef $$TreatmentRecordsTableCreateCompanionBuilder =
    TreatmentRecordsCompanion Function({
      Value<int> id,
      required String patientNo,
      required int therapistId,
      required String recordDate,
      required String discipline,
      required String kind,
      Value<int?> seqNo,
      Value<String> bodyJson,
      Value<String> renderedText,
      Value<String?> note,
      Value<String> status,
      Value<int> editCount,
      Value<int> revision,
      Value<bool> isTemporary,
      Value<int?> originalTherapistId,
      Value<String?> clientUuid,
      Value<String> syncStatus,
    });
typedef $$TreatmentRecordsTableUpdateCompanionBuilder =
    TreatmentRecordsCompanion Function({
      Value<int> id,
      Value<String> patientNo,
      Value<int> therapistId,
      Value<String> recordDate,
      Value<String> discipline,
      Value<String> kind,
      Value<int?> seqNo,
      Value<String> bodyJson,
      Value<String> renderedText,
      Value<String?> note,
      Value<String> status,
      Value<int> editCount,
      Value<int> revision,
      Value<bool> isTemporary,
      Value<int?> originalTherapistId,
      Value<String?> clientUuid,
      Value<String> syncStatus,
    });

class $$TreatmentRecordsTableFilterComposer
    extends Composer<_$AppDatabase, $TreatmentRecordsTable> {
  $$TreatmentRecordsTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<int> get id => $composableBuilder(
    column: $table.id,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get patientNo => $composableBuilder(
    column: $table.patientNo,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<int> get therapistId => $composableBuilder(
    column: $table.therapistId,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get recordDate => $composableBuilder(
    column: $table.recordDate,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get discipline => $composableBuilder(
    column: $table.discipline,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get kind => $composableBuilder(
    column: $table.kind,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<int> get seqNo => $composableBuilder(
    column: $table.seqNo,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get bodyJson => $composableBuilder(
    column: $table.bodyJson,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get renderedText => $composableBuilder(
    column: $table.renderedText,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get note => $composableBuilder(
    column: $table.note,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get status => $composableBuilder(
    column: $table.status,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<int> get editCount => $composableBuilder(
    column: $table.editCount,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<int> get revision => $composableBuilder(
    column: $table.revision,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<bool> get isTemporary => $composableBuilder(
    column: $table.isTemporary,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<int> get originalTherapistId => $composableBuilder(
    column: $table.originalTherapistId,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get clientUuid => $composableBuilder(
    column: $table.clientUuid,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get syncStatus => $composableBuilder(
    column: $table.syncStatus,
    builder: (column) => ColumnFilters(column),
  );
}

class $$TreatmentRecordsTableOrderingComposer
    extends Composer<_$AppDatabase, $TreatmentRecordsTable> {
  $$TreatmentRecordsTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<int> get id => $composableBuilder(
    column: $table.id,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get patientNo => $composableBuilder(
    column: $table.patientNo,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<int> get therapistId => $composableBuilder(
    column: $table.therapistId,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get recordDate => $composableBuilder(
    column: $table.recordDate,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get discipline => $composableBuilder(
    column: $table.discipline,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get kind => $composableBuilder(
    column: $table.kind,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<int> get seqNo => $composableBuilder(
    column: $table.seqNo,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get bodyJson => $composableBuilder(
    column: $table.bodyJson,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get renderedText => $composableBuilder(
    column: $table.renderedText,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get note => $composableBuilder(
    column: $table.note,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get status => $composableBuilder(
    column: $table.status,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<int> get editCount => $composableBuilder(
    column: $table.editCount,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<int> get revision => $composableBuilder(
    column: $table.revision,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<bool> get isTemporary => $composableBuilder(
    column: $table.isTemporary,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<int> get originalTherapistId => $composableBuilder(
    column: $table.originalTherapistId,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get clientUuid => $composableBuilder(
    column: $table.clientUuid,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get syncStatus => $composableBuilder(
    column: $table.syncStatus,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$TreatmentRecordsTableAnnotationComposer
    extends Composer<_$AppDatabase, $TreatmentRecordsTable> {
  $$TreatmentRecordsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<int> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get patientNo =>
      $composableBuilder(column: $table.patientNo, builder: (column) => column);

  GeneratedColumn<int> get therapistId => $composableBuilder(
    column: $table.therapistId,
    builder: (column) => column,
  );

  GeneratedColumn<String> get recordDate => $composableBuilder(
    column: $table.recordDate,
    builder: (column) => column,
  );

  GeneratedColumn<String> get discipline => $composableBuilder(
    column: $table.discipline,
    builder: (column) => column,
  );

  GeneratedColumn<String> get kind =>
      $composableBuilder(column: $table.kind, builder: (column) => column);

  GeneratedColumn<int> get seqNo =>
      $composableBuilder(column: $table.seqNo, builder: (column) => column);

  GeneratedColumn<String> get bodyJson =>
      $composableBuilder(column: $table.bodyJson, builder: (column) => column);

  GeneratedColumn<String> get renderedText => $composableBuilder(
    column: $table.renderedText,
    builder: (column) => column,
  );

  GeneratedColumn<String> get note =>
      $composableBuilder(column: $table.note, builder: (column) => column);

  GeneratedColumn<String> get status =>
      $composableBuilder(column: $table.status, builder: (column) => column);

  GeneratedColumn<int> get editCount =>
      $composableBuilder(column: $table.editCount, builder: (column) => column);

  GeneratedColumn<int> get revision =>
      $composableBuilder(column: $table.revision, builder: (column) => column);

  GeneratedColumn<bool> get isTemporary => $composableBuilder(
    column: $table.isTemporary,
    builder: (column) => column,
  );

  GeneratedColumn<int> get originalTherapistId => $composableBuilder(
    column: $table.originalTherapistId,
    builder: (column) => column,
  );

  GeneratedColumn<String> get clientUuid => $composableBuilder(
    column: $table.clientUuid,
    builder: (column) => column,
  );

  GeneratedColumn<String> get syncStatus => $composableBuilder(
    column: $table.syncStatus,
    builder: (column) => column,
  );
}

class $$TreatmentRecordsTableTableManager
    extends
        RootTableManager<
          _$AppDatabase,
          $TreatmentRecordsTable,
          TreatmentRecord,
          $$TreatmentRecordsTableFilterComposer,
          $$TreatmentRecordsTableOrderingComposer,
          $$TreatmentRecordsTableAnnotationComposer,
          $$TreatmentRecordsTableCreateCompanionBuilder,
          $$TreatmentRecordsTableUpdateCompanionBuilder,
          (
            TreatmentRecord,
            BaseReferences<
              _$AppDatabase,
              $TreatmentRecordsTable,
              TreatmentRecord
            >,
          ),
          TreatmentRecord,
          PrefetchHooks Function()
        > {
  $$TreatmentRecordsTableTableManager(
    _$AppDatabase db,
    $TreatmentRecordsTable table,
  ) : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$TreatmentRecordsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$TreatmentRecordsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$TreatmentRecordsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<int> id = const Value.absent(),
                Value<String> patientNo = const Value.absent(),
                Value<int> therapistId = const Value.absent(),
                Value<String> recordDate = const Value.absent(),
                Value<String> discipline = const Value.absent(),
                Value<String> kind = const Value.absent(),
                Value<int?> seqNo = const Value.absent(),
                Value<String> bodyJson = const Value.absent(),
                Value<String> renderedText = const Value.absent(),
                Value<String?> note = const Value.absent(),
                Value<String> status = const Value.absent(),
                Value<int> editCount = const Value.absent(),
                Value<int> revision = const Value.absent(),
                Value<bool> isTemporary = const Value.absent(),
                Value<int?> originalTherapistId = const Value.absent(),
                Value<String?> clientUuid = const Value.absent(),
                Value<String> syncStatus = const Value.absent(),
              }) => TreatmentRecordsCompanion(
                id: id,
                patientNo: patientNo,
                therapistId: therapistId,
                recordDate: recordDate,
                discipline: discipline,
                kind: kind,
                seqNo: seqNo,
                bodyJson: bodyJson,
                renderedText: renderedText,
                note: note,
                status: status,
                editCount: editCount,
                revision: revision,
                isTemporary: isTemporary,
                originalTherapistId: originalTherapistId,
                clientUuid: clientUuid,
                syncStatus: syncStatus,
              ),
          createCompanionCallback:
              ({
                Value<int> id = const Value.absent(),
                required String patientNo,
                required int therapistId,
                required String recordDate,
                required String discipline,
                required String kind,
                Value<int?> seqNo = const Value.absent(),
                Value<String> bodyJson = const Value.absent(),
                Value<String> renderedText = const Value.absent(),
                Value<String?> note = const Value.absent(),
                Value<String> status = const Value.absent(),
                Value<int> editCount = const Value.absent(),
                Value<int> revision = const Value.absent(),
                Value<bool> isTemporary = const Value.absent(),
                Value<int?> originalTherapistId = const Value.absent(),
                Value<String?> clientUuid = const Value.absent(),
                Value<String> syncStatus = const Value.absent(),
              }) => TreatmentRecordsCompanion.insert(
                id: id,
                patientNo: patientNo,
                therapistId: therapistId,
                recordDate: recordDate,
                discipline: discipline,
                kind: kind,
                seqNo: seqNo,
                bodyJson: bodyJson,
                renderedText: renderedText,
                note: note,
                status: status,
                editCount: editCount,
                revision: revision,
                isTemporary: isTemporary,
                originalTherapistId: originalTherapistId,
                clientUuid: clientUuid,
                syncStatus: syncStatus,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$TreatmentRecordsTable, TreatmentRecord>(table),
                  BaseReferences<
                    _$AppDatabase,
                    $TreatmentRecordsTable,
                    TreatmentRecord
                  >(db, table, e),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$TreatmentRecordsTableProcessedTableManager =
    ProcessedTableManager<
      _$AppDatabase,
      $TreatmentRecordsTable,
      TreatmentRecord,
      $$TreatmentRecordsTableFilterComposer,
      $$TreatmentRecordsTableOrderingComposer,
      $$TreatmentRecordsTableAnnotationComposer,
      $$TreatmentRecordsTableCreateCompanionBuilder,
      $$TreatmentRecordsTableUpdateCompanionBuilder,
      (
        TreatmentRecord,
        BaseReferences<_$AppDatabase, $TreatmentRecordsTable, TreatmentRecord>,
      ),
      TreatmentRecord,
      PrefetchHooks Function()
    >;
typedef $$ChangeQueueTableCreateCompanionBuilder =
    ChangeQueueCompanion Function({
      required String clientUuid,
      required String entity,
      Value<String> op,
      Value<int?> baseRevision,
      required String payloadJson,
      Value<String> syncStatus,
      Value<int> retryCount,
      Value<String?> lastError,
      required String createdAt,
      Value<int> rowid,
    });
typedef $$ChangeQueueTableUpdateCompanionBuilder =
    ChangeQueueCompanion Function({
      Value<String> clientUuid,
      Value<String> entity,
      Value<String> op,
      Value<int?> baseRevision,
      Value<String> payloadJson,
      Value<String> syncStatus,
      Value<int> retryCount,
      Value<String?> lastError,
      Value<String> createdAt,
      Value<int> rowid,
    });

class $$ChangeQueueTableFilterComposer
    extends Composer<_$AppDatabase, $ChangeQueueTable> {
  $$ChangeQueueTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get clientUuid => $composableBuilder(
    column: $table.clientUuid,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get entity => $composableBuilder(
    column: $table.entity,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get op => $composableBuilder(
    column: $table.op,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<int> get baseRevision => $composableBuilder(
    column: $table.baseRevision,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get syncStatus => $composableBuilder(
    column: $table.syncStatus,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<int> get retryCount => $composableBuilder(
    column: $table.retryCount,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get lastError => $composableBuilder(
    column: $table.lastError,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get createdAt => $composableBuilder(
    column: $table.createdAt,
    builder: (column) => ColumnFilters(column),
  );
}

class $$ChangeQueueTableOrderingComposer
    extends Composer<_$AppDatabase, $ChangeQueueTable> {
  $$ChangeQueueTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get clientUuid => $composableBuilder(
    column: $table.clientUuid,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get entity => $composableBuilder(
    column: $table.entity,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get op => $composableBuilder(
    column: $table.op,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<int> get baseRevision => $composableBuilder(
    column: $table.baseRevision,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get syncStatus => $composableBuilder(
    column: $table.syncStatus,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<int> get retryCount => $composableBuilder(
    column: $table.retryCount,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get lastError => $composableBuilder(
    column: $table.lastError,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get createdAt => $composableBuilder(
    column: $table.createdAt,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$ChangeQueueTableAnnotationComposer
    extends Composer<_$AppDatabase, $ChangeQueueTable> {
  $$ChangeQueueTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get clientUuid => $composableBuilder(
    column: $table.clientUuid,
    builder: (column) => column,
  );

  GeneratedColumn<String> get entity =>
      $composableBuilder(column: $table.entity, builder: (column) => column);

  GeneratedColumn<String> get op =>
      $composableBuilder(column: $table.op, builder: (column) => column);

  GeneratedColumn<int> get baseRevision => $composableBuilder(
    column: $table.baseRevision,
    builder: (column) => column,
  );

  GeneratedColumn<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => column,
  );

  GeneratedColumn<String> get syncStatus => $composableBuilder(
    column: $table.syncStatus,
    builder: (column) => column,
  );

  GeneratedColumn<int> get retryCount => $composableBuilder(
    column: $table.retryCount,
    builder: (column) => column,
  );

  GeneratedColumn<String> get lastError =>
      $composableBuilder(column: $table.lastError, builder: (column) => column);

  GeneratedColumn<String> get createdAt =>
      $composableBuilder(column: $table.createdAt, builder: (column) => column);
}

class $$ChangeQueueTableTableManager
    extends
        RootTableManager<
          _$AppDatabase,
          $ChangeQueueTable,
          ChangeQueueData,
          $$ChangeQueueTableFilterComposer,
          $$ChangeQueueTableOrderingComposer,
          $$ChangeQueueTableAnnotationComposer,
          $$ChangeQueueTableCreateCompanionBuilder,
          $$ChangeQueueTableUpdateCompanionBuilder,
          (
            ChangeQueueData,
            BaseReferences<_$AppDatabase, $ChangeQueueTable, ChangeQueueData>,
          ),
          ChangeQueueData,
          PrefetchHooks Function()
        > {
  $$ChangeQueueTableTableManager(_$AppDatabase db, $ChangeQueueTable table)
    : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$ChangeQueueTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$ChangeQueueTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$ChangeQueueTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<String> clientUuid = const Value.absent(),
                Value<String> entity = const Value.absent(),
                Value<String> op = const Value.absent(),
                Value<int?> baseRevision = const Value.absent(),
                Value<String> payloadJson = const Value.absent(),
                Value<String> syncStatus = const Value.absent(),
                Value<int> retryCount = const Value.absent(),
                Value<String?> lastError = const Value.absent(),
                Value<String> createdAt = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => ChangeQueueCompanion(
                clientUuid: clientUuid,
                entity: entity,
                op: op,
                baseRevision: baseRevision,
                payloadJson: payloadJson,
                syncStatus: syncStatus,
                retryCount: retryCount,
                lastError: lastError,
                createdAt: createdAt,
                rowid: rowid,
              ),
          createCompanionCallback:
              ({
                required String clientUuid,
                required String entity,
                Value<String> op = const Value.absent(),
                Value<int?> baseRevision = const Value.absent(),
                required String payloadJson,
                Value<String> syncStatus = const Value.absent(),
                Value<int> retryCount = const Value.absent(),
                Value<String?> lastError = const Value.absent(),
                required String createdAt,
                Value<int> rowid = const Value.absent(),
              }) => ChangeQueueCompanion.insert(
                clientUuid: clientUuid,
                entity: entity,
                op: op,
                baseRevision: baseRevision,
                payloadJson: payloadJson,
                syncStatus: syncStatus,
                retryCount: retryCount,
                lastError: lastError,
                createdAt: createdAt,
                rowid: rowid,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$ChangeQueueTable, ChangeQueueData>(table),
                  BaseReferences<
                    _$AppDatabase,
                    $ChangeQueueTable,
                    ChangeQueueData
                  >(db, table, e),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$ChangeQueueTableProcessedTableManager =
    ProcessedTableManager<
      _$AppDatabase,
      $ChangeQueueTable,
      ChangeQueueData,
      $$ChangeQueueTableFilterComposer,
      $$ChangeQueueTableOrderingComposer,
      $$ChangeQueueTableAnnotationComposer,
      $$ChangeQueueTableCreateCompanionBuilder,
      $$ChangeQueueTableUpdateCompanionBuilder,
      (
        ChangeQueueData,
        BaseReferences<_$AppDatabase, $ChangeQueueTable, ChangeQueueData>,
      ),
      ChangeQueueData,
      PrefetchHooks Function()
    >;
typedef $$SyncStateTableCreateCompanionBuilder = SyncStateCompanion Function({
  required String key,
  required String value,
  Value<int> rowid,
});
typedef $$SyncStateTableUpdateCompanionBuilder = SyncStateCompanion Function({
  Value<String> key,
  Value<String> value,
  Value<int> rowid,
});

class $$SyncStateTableFilterComposer
    extends Composer<_$AppDatabase, $SyncStateTable> {
  $$SyncStateTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get key => $composableBuilder(
    column: $table.key,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get value => $composableBuilder(
    column: $table.value,
    builder: (column) => ColumnFilters(column),
  );
}

class $$SyncStateTableOrderingComposer
    extends Composer<_$AppDatabase, $SyncStateTable> {
  $$SyncStateTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get key => $composableBuilder(
    column: $table.key,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get value => $composableBuilder(
    column: $table.value,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$SyncStateTableAnnotationComposer
    extends Composer<_$AppDatabase, $SyncStateTable> {
  $$SyncStateTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get key =>
      $composableBuilder(column: $table.key, builder: (column) => column);

  GeneratedColumn<String> get value =>
      $composableBuilder(column: $table.value, builder: (column) => column);
}

class $$SyncStateTableTableManager
    extends
        RootTableManager<
          _$AppDatabase,
          $SyncStateTable,
          SyncStateData,
          $$SyncStateTableFilterComposer,
          $$SyncStateTableOrderingComposer,
          $$SyncStateTableAnnotationComposer,
          $$SyncStateTableCreateCompanionBuilder,
          $$SyncStateTableUpdateCompanionBuilder,
          (
            SyncStateData,
            BaseReferences<_$AppDatabase, $SyncStateTable, SyncStateData>,
          ),
          SyncStateData,
          PrefetchHooks Function()
        > {
  $$SyncStateTableTableManager(_$AppDatabase db, $SyncStateTable table)
    : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$SyncStateTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$SyncStateTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$SyncStateTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> key = const Value.absent(),
            Value<String> value = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) => SyncStateCompanion(key: key, value: value, rowid: rowid),
          createCompanionCallback: ({
            required String key,
            required String value,
            Value<int> rowid = const Value.absent(),
          }) => SyncStateCompanion.insert(key: key, value: value, rowid: rowid),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$SyncStateTable, SyncStateData>(table),
                  BaseReferences<_$AppDatabase, $SyncStateTable, SyncStateData>(
                    db,
                    table,
                    e,
                  ),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$SyncStateTableProcessedTableManager =
    ProcessedTableManager<
      _$AppDatabase,
      $SyncStateTable,
      SyncStateData,
      $$SyncStateTableFilterComposer,
      $$SyncStateTableOrderingComposer,
      $$SyncStateTableAnnotationComposer,
      $$SyncStateTableCreateCompanionBuilder,
      $$SyncStateTableUpdateCompanionBuilder,
      (
        SyncStateData,
        BaseReferences<_$AppDatabase, $SyncStateTable, SyncStateData>,
      ),
      SyncStateData,
      PrefetchHooks Function()
    >;
typedef $$RefCacheTableCreateCompanionBuilder = RefCacheCompanion Function({
  required String key,
  required String payloadJson,
  required String fetchedAt,
  Value<String?> etag,
  Value<int> rowid,
});
typedef $$RefCacheTableUpdateCompanionBuilder = RefCacheCompanion Function({
  Value<String> key,
  Value<String> payloadJson,
  Value<String> fetchedAt,
  Value<String?> etag,
  Value<int> rowid,
});

class $$RefCacheTableFilterComposer
    extends Composer<_$AppDatabase, $RefCacheTable> {
  $$RefCacheTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get key => $composableBuilder(
    column: $table.key,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get fetchedAt => $composableBuilder(
    column: $table.fetchedAt,
    builder: (column) => ColumnFilters(column),
  );

  ColumnFilters<String> get etag => $composableBuilder(
    column: $table.etag,
    builder: (column) => ColumnFilters(column),
  );
}

class $$RefCacheTableOrderingComposer
    extends Composer<_$AppDatabase, $RefCacheTable> {
  $$RefCacheTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get key => $composableBuilder(
    column: $table.key,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get fetchedAt => $composableBuilder(
    column: $table.fetchedAt,
    builder: (column) => ColumnOrderings(column),
  );

  ColumnOrderings<String> get etag => $composableBuilder(
    column: $table.etag,
    builder: (column) => ColumnOrderings(column),
  );
}

class $$RefCacheTableAnnotationComposer
    extends Composer<_$AppDatabase, $RefCacheTable> {
  $$RefCacheTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get key =>
      $composableBuilder(column: $table.key, builder: (column) => column);

  GeneratedColumn<String> get payloadJson => $composableBuilder(
    column: $table.payloadJson,
    builder: (column) => column,
  );

  GeneratedColumn<String> get fetchedAt =>
      $composableBuilder(column: $table.fetchedAt, builder: (column) => column);

  GeneratedColumn<String> get etag =>
      $composableBuilder(column: $table.etag, builder: (column) => column);
}

class $$RefCacheTableTableManager
    extends
        RootTableManager<
          _$AppDatabase,
          $RefCacheTable,
          RefCacheData,
          $$RefCacheTableFilterComposer,
          $$RefCacheTableOrderingComposer,
          $$RefCacheTableAnnotationComposer,
          $$RefCacheTableCreateCompanionBuilder,
          $$RefCacheTableUpdateCompanionBuilder,
          (
            RefCacheData,
            BaseReferences<_$AppDatabase, $RefCacheTable, RefCacheData>,
          ),
          RefCacheData,
          PrefetchHooks Function()
        > {
  $$RefCacheTableTableManager(_$AppDatabase db, $RefCacheTable table)
    : super(
        TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$RefCacheTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$RefCacheTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$RefCacheTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback:
              ({
                Value<String> key = const Value.absent(),
                Value<String> payloadJson = const Value.absent(),
                Value<String> fetchedAt = const Value.absent(),
                Value<String?> etag = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => RefCacheCompanion(
                key: key,
                payloadJson: payloadJson,
                fetchedAt: fetchedAt,
                etag: etag,
                rowid: rowid,
              ),
          createCompanionCallback:
              ({
                required String key,
                required String payloadJson,
                required String fetchedAt,
                Value<String?> etag = const Value.absent(),
                Value<int> rowid = const Value.absent(),
              }) => RefCacheCompanion.insert(
                key: key,
                payloadJson: payloadJson,
                fetchedAt: fetchedAt,
                etag: etag,
                rowid: rowid,
              ),
          withReferenceMapper: (p0) => p0
              .map(
                (e) => (
                  e.readTable<$RefCacheTable, RefCacheData>(table),
                  BaseReferences<_$AppDatabase, $RefCacheTable, RefCacheData>(
                    db,
                    table,
                    e,
                  ),
                ),
              )
              .toList(),
          prefetchHooksCallback: null,
        ),
      );
}

typedef $$RefCacheTableProcessedTableManager =
    ProcessedTableManager<
      _$AppDatabase,
      $RefCacheTable,
      RefCacheData,
      $$RefCacheTableFilterComposer,
      $$RefCacheTableOrderingComposer,
      $$RefCacheTableAnnotationComposer,
      $$RefCacheTableCreateCompanionBuilder,
      $$RefCacheTableUpdateCompanionBuilder,
      (
        RefCacheData,
        BaseReferences<_$AppDatabase, $RefCacheTable, RefCacheData>,
      ),
      RefCacheData,
      PrefetchHooks Function()
    >;

class $AppDatabaseManager {
  final _$AppDatabase _db;
  $AppDatabaseManager(this._db);
  $$PatientsTableTableManager get patients =>
      $$PatientsTableTableManager(_db, _db.patients);
  $$TreatmentRecordsTableTableManager get treatmentRecords =>
      $$TreatmentRecordsTableTableManager(_db, _db.treatmentRecords);
  $$ChangeQueueTableTableManager get changeQueue =>
      $$ChangeQueueTableTableManager(_db, _db.changeQueue);
  $$SyncStateTableTableManager get syncState =>
      $$SyncStateTableTableManager(_db, _db.syncState);
  $$RefCacheTableTableManager get refCache =>
      $$RefCacheTableTableManager(_db, _db.refCache);
}

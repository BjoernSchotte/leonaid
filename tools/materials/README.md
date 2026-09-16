# Material-Upload bereinigen

Ein abgebrochener Upload kann eine private S3-Version ohne `material_version` hinterlassen. Derselbe Upload-Befehl übernimmt sie bei Wiederholung. Wenn die Wiederholung endgültig aufgegeben wurde, erlaubt `cleanup.py` die kontrollierte Bereinigung einer konkret identifizierten Version. Es gibt keinen pauschalen Bucket-Scan und keine automatische Löschung anhand eines Dateialters.

Vorbereitung: Alle API-/Worker-Instanzen müssen den Stand mit Upload-Sperre enthalten; alte laufende Prozesse zuerst regulär beenden. Die Wartung verwendet dieselbe Core-Datenbank und S3-Konfiguration wie die Anwendung. Nur Materialobjekte des konfigurierten Buckets werden berücksichtigt; keine Survey- oder Rechnungsdateien.

1. In der administrativen S3-Versionsansicht den konkreten Schlüssel `materials/<material-uuid>/<upload-uuid>` und die exakte Storage-Version-ID bestimmen. Nicht die fachliche Versionsnummer verwenden. Einen Materialbereich niemals vollständig löschen.
2. Mit einem aktuell aktiven System-Admin-Konto und nachvollziehbarer Begründung zuerst prüfen. Die normale Laufzeitkonfiguration muss im Prozess-Environment vorliegen (einschließlich der Secrets; niemals in die Kommandozeile oder Git kopieren):

```sh
PYTHONPATH=src python tools/materials/cleanup.py \
  --actor "$ADMIN_USER_ID" \
  --material "$MATERIAL_ID" \
  --upload "$UPLOAD_ID" \
  --storage-version "$STORAGE_VERSION_ID" \
  --reason 'Endgültig abgebrochener Upload, Vorgang geprüft'
```

3. `would-delete` bedeutet: aktuell unreferenziert und als Materialobjekt bestätigt. Für die Löschung denselben Aufruf mit `--apply` wiederholen. Die Prüfung erfolgt dabei erneut, nicht auf Basis des früheren Prüfergebnisses. `already-absent` ist bei Wiederholung ein erfolgreicher Zustand.

Uploader und Bereinigung halten dieselbe PostgreSQL-Transaktionssperre pro Bucket/Objektschlüssel. Ein noch laufender Upload wird abgewartet: nach Commit verhindert seine Referenz die Löschung; nach Rollback kann die verwaiste Version entfernt werden. Auch ein äußerer Transaktionsrahmen bleibt geschützt. Löschen trifft ausschließlich die angegebene Storage-Version und prüft anschließend ihre Abwesenheit. Referenzierte Versionen werden mit `material_upload_referenced` abgewiesen.

Vor einer tatsächlichen Löschung wird `material.upload_cleanup_requested` dauerhaft mit Selektoren und Begründung protokolliert. `material.upload_cleanup_completed` bestätigt den abgeschlossenen Versuch; beide verwenden dieselbe Request-ID. Ein angeforderter Versuch ohne Abschluss kann abgewiesen oder unterbrochen worden sein und verlangt Prüfung. Bei Speicherfehler oder Prozessabbruch denselben exakten Aufruf wiederholen: er prüft erneut Datenbank und Speicher. Ein später wiederholter ursprünglicher Upload kann die entfernten Bytes neu speichern; bestehende erfolgreich gespeicherte Dateiversionen bleiben unverändert.

Nach Restore gelten die bestehenden Restore-/Wiederanlaufregeln. Die Wartung nicht gegen eine unvollständige oder gerade restaurierte Datenbank ausführen: nur die autoritative, vollständig wiederhergestellte Datenbank kann Referenzen zuverlässig bestätigen.

Nachweis: `tools/materials/cleanup_contract.py` verwendet echte PostgreSQL-Transaktionen, konkurrierende Sperren, RustFS-Versionen und den tatsächlichen CLI-Prozess. Der Vertrag ist Bestandteil des Schema-Gates.

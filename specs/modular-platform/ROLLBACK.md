# Rücknahme mit erweitertem Schema

Eine ältere API kann das additive Schema lesen; daraus folgt keine Kompatibilität
ihres Workers mit neuen Aufträgen. Vor einer Rücknahme API- und Worker-Images
einschließlich Digest festhalten und den bestehenden Backup-Pfad verwenden.
`compose` bezeichnet unten den bereits konfigurierten Aufruf für genau das
betroffene Deployment mit dessen Projekt, Compose-Dateien und Umgebung.

## Neue Eingänge stoppen und kompatiblen Worker behalten

1. `compose stop api` stoppt alle API-Schreibzugänge, auch Direktaufrufe. Eine
   ausgeblendete Navigation genügt nicht. Am öffentlichen Proxy prüfen, dass
   neue Einreichungen nicht mehr angenommen werden. Das ist ein Wartungsfenster.
2. Das bisherige Worker-Image mit den neuen Handlern unverändert weiterbetreiben.
   Keinen alten Worker parallel starten: Er könnte neue Jobs beanspruchen und
   mit `handler_not_registered` in den Retry schicken.
3. In Core PostgreSQL den tatsächlichen Bestand prüfen:

   ```sql
   SELECT event_type, status, count(*) AS jobs,
          min(available_at) AS next_attempt
   FROM outbox_event
   WHERE status <> 'completed'
   GROUP BY event_type, status
   ORDER BY event_type, status;
   ```

   Zukünftige `pending`-Jobs, aktive `processing`-Jobs und `dead_letter` zählen
   weiterhin als offen. Ein leerer fälliger Batch oder `run-until-idle` mit
   `handled: 0` beweist keine leere Queue. Der laufende Survey-Sweep kann selbst
   weitere Jobs erzeugen; auch deshalb ist ein einzelner Snapshot unzureichend.
4. Neue Inbox-Aufträge müssen mit dem kompatiblen Worker abgeschlossen oder über
   die vorhandene autorisierte Kontaktklärung fachlich aufgelöst werden.
   `needs_review` nicht blind wiederholen: Ein externer Create kann bereits
   erfolgt sein. Keine Queue-Zeilen löschen oder Statuswerte per SQL umschreiben.
5. Bei ausstehender Klärung, künftigen Jobs oder unbewiesener Kompatibilität den
   aktuellen Worker erhalten und einen Forward-Fix ausrollen. Auch nach leerer
   Queue darf ein alter Worker erst eingesetzt werden, wenn Handler, Payloads
   und alle weiterhin aktiven Produzenten nachweislich kompatibel sind.
6. Kompatible API bzw. Forward-Fix starten, Readiness, Anmeldung, aktuelle
   Objektberechtigungen und eine neue Einreichung prüfen. Bestehende Fachobjekte,
   Referenzen, Dateien und Bestätigungen müssen erhalten bleiben. Kein Schema-
   Downgrade und keine Löschung von Tabellen, Volumes oder Nutzerdaten.

## Nachweisgrenzen

`sh tools/schema/test.sh . code-rollback` prüft frühere API-Quellstände auf dem
aktuellen Schema in der heutigen gepinnten Python-Laufzeit. Er ersetzt weder
einen Image-Rollback noch die oben beschriebene Queue-Prüfung.

Der konkrete Lauf mit gestoppter API und kompatiblem Produktionsworker wird in
`PROGRESS.md` festgehalten. Eine erfolgreiche Verarbeitung eines neuen Jobs ist
ein Nachweis für diesen Ablauf; sie ist keine Freigabe, einen Worker ohne dessen
Handler zu starten.

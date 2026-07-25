# RustFS

RustFS ist der S3-kompatible Objektspeicher des Corestacks. API und Worker
erreichen ausschließlich den internen S3-Endpunkt; weder S3-Port noch
Administrationskonsole werden am Host veröffentlicht.

Zugangsdaten entstehen lokal durch `./leonaid bootstrap`. Der
POC-010-Integrationstest schreibt das vollständige Golden Dataset über Boto3
als echtes Objekt und verifiziert Bytes, SHA-256 und Metadaten nach dem
Neustart aller Container. Die fachliche Dokumentablage folgt in POC-092.

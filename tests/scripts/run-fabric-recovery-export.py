#!/usr/bin/env python3
"""Qualify actual PostgreSQL dump/export provenance in a disposable fixture.

Only the cached immutable image, a new labelled loopback container, fixture-only
roles and a controlled empty S3 listing adapter are used. This is PostgreSQL
provenance/application readback evidence, never native MinIO or production DR.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

IMAGE = "docker.io/library/postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
LABEL = "io.genomes.fabric.backup-provenance-fixture"
SOURCE_SQL = """SELECT json_build_object('schemaVersion','execution-fabric-postgres-source/v1',
'systemId',c.system_identifier::text,'database',current_database(),'databaseOid',d.oid::text,
'majorVersion',current_setting('server_version_num')::integer/10000,
'serverVersionNum',current_setting('server_version_num')::integer)
FROM pg_control_system() c JOIN pg_database d ON d.datname=current_database();"""

def run(argv, *, data=None, timeout=45):
    result = subprocess.run(argv, input=data, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        detail = result.stderr.lower()
        category = next((name for needle, name in (
            (b"connection refused", "connection_refused"),
            (b"starting up", "database_starting"),
            (b"syntax error", "syntax_error"),
            (b"permission denied", "permission_denied"),
            (b"does not exist", "missing_native_object"),
            (b"authentication failed", "authentication_failed"),
        ) if needle in detail), "native_actor_failed")
        raise ValueError(category+"; exit="+str(result.returncode))
    return result.stdout

def private(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True, indent=2)+"\n").encode())

def inspected(cid):
    return json.loads(run(["docker", "inspect", cid, "--format", "{{json .}}"]))

def own(value, name, token, cid=None):
    identity = value.get("Id", "")
    if (not re.fullmatch("[a-f0-9]{64}", identity) or value.get("Name") != "/"+name
        or value.get("Config", {}).get("Labels", {}).get(LABEL) != token or (cid and identity != cid)):
        raise ValueError("fixture ownership changed")
    return identity

class Listing(BaseHTTPRequestHandler):
    calls = []
    def do_GET(self):
        self.calls.append(self.path)
        if "versions" not in parse_qs(urlsplit(self.path).query, keep_blank_values=True):
            self.send_error(405)
            return
        body = b'<ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>fixture-artifacts</Name><Prefix/><KeyMarker/><VersionIdMarker/><MaxKeys>1000</MaxKeys><IsTruncated>false</IsTruncated></ListVersionsResult>'
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        self.send_error(405)
    do_PUT = do_POST
    do_DELETE = do_POST
    def log_message(self, *args):
        pass

def execute(root, output):
    from genomes_agentic_os import execution_fabric_recovery as recovery
    root = root.resolve(strict=True)
    if root != Path(__file__).resolve().parents[2]:
        raise ValueError("exact owned source root required")
    files = [root/"deploy/execution-fabric/scripts/postgres-backup.sh",
        root/"services/execution-fabric-control-plane/dist/src/recovery-export-main.js",
        root/"services/execution-fabric-control-plane/dist/src/recovery-export.js",
        Path(__file__).resolve(), root/"src/genomes_agentic_os/execution_fabric_recovery.py"]
    if any(not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o022 for path in files):
        raise ValueError("owned built source actors required")
    if output.exists() or output.is_symlink() or not output.is_absolute():
        raise ValueError("new absolute private output required")
    output.mkdir(mode=0o700, parents=True)
    token = uuid4().hex
    name = "rubicon-backup-provenance-"+token[:12]
    database = "fixture_"+token[:12]
    password, reader_password = secrets.token_hex(24), secrets.token_hex(24)
    cid, attempted, server, accepted, cleaned = None, False, None, False, False
    stage = "cached_image_identity"
    credential = output/"reader-secret.json"
    evidence = {"schemaVersion":"execution-fabric-postgres-provenance-fixture/v1",
        "fixtureOnly":True, "image":IMAGE, "sourceRoot":str(root),
        "actorSha256":{str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
        "productionRecoveryQualified":False, "nativeMinioQualified":False,
        "authorityTransferAuthorized":False}
    try:
        image = json.loads(run(["docker","image","inspect",IMAGE,"--format","{{json .}}"]))
        image_id = image["Id"]
        stage = "fresh_container_creation"
        attempted = True
        cid = run(["docker","run","--pull=never","--detach","--name",name,"--label",LABEL+"="+token,
            "--restart=no","--memory=512m","--cpus=1","--publish","127.0.0.1::5432",
            "--env","POSTGRES_USER=recovery_admin","--env","POSTGRES_DB="+database,
            "--env","POSTGRES_PASSWORD="+password,IMAGE]).decode().strip()
        value = inspected(cid)
        own(value,name,token,cid)
        host = value["HostConfig"]
        ports = value["NetworkSettings"]["Ports"]["5432/tcp"]
        if (value["Image"] != image_id or host.get("Binds") or host.get("Privileged")
            or host["RestartPolicy"]["Name"] != "no" or host["Memory"] != 512*1024*1024
            or host["NanoCpus"] != 1_000_000_000 or any(m["Type"]=="bind" for m in value.get("Mounts",[]))
            or len(ports)!=1 or ports[0]["HostIp"]!="127.0.0.1"):
            raise ValueError("isolated fixture image/resources/mounts/loopback differ")
        port = int(ports[0]["HostPort"])
        stage = "source_readiness"
        for _ in range(150):
            # The image starts a socket-only initialization server before the
            # requested database exists. Only its final TCP server qualifies.
            result = subprocess.run(["docker","exec",cid,"pg_isready","--host=127.0.0.1",
                "-U","recovery_admin","-d",database],
                capture_output=True,timeout=5,check=False)
            if result.returncode == 0:
                break
            time.sleep(.2)
        else:
            raise ValueError("fresh fixture database readiness failed")
        def sql(text, db=database):
            return run(["docker","exec","-i",cid,"psql","--no-psqlrc","--set=ON_ERROR_STOP=1",
                "--tuples-only","--no-align","--username=recovery_admin","--dbname="+db],data=text.encode())
        stage = "fixture_schema_and_readonly_role"
        sql("""CREATE TABLE fabric_artifacts(id text PRIMARY KEY,task_id text,attempt_id text,object_key text,
storage_uri text,sha256 text,size_bytes bigint,status text);
CREATE TABLE recovery_canary(id integer PRIMARY KEY,payload text);
INSERT INTO recovery_canary VALUES(1,'immutable source row');
CREATE ROLE recovery_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '""" + reader_password + """';
GRANT CONNECT ON DATABASE """+database+""" TO recovery_reader;
GRANT USAGE ON SCHEMA public TO recovery_reader;
GRANT SELECT ON TABLE fabric_artifacts TO recovery_reader;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO recovery_reader;""")
        source = recovery.postgres_source_identity(json.loads(sql(SOURCE_SQL)))
        stage = "native_dump_restore_source_provenance"
        pgpass = ("127.0.0.1:5432:*:recovery_admin:"+password+"\n").encode()
        run(["docker","exec","-i",cid,"sh","-c","umask 077; cat > /tmp/recovery-fixture.pgpass"],data=pgpass)
        run(["docker","exec","-i","--env","PGHOST=127.0.0.1","--env","PGDATABASE="+database,
            "--env","PGUSER=recovery_admin","--env","PGPASSFILE=/tmp/recovery-fixture.pgpass",
            "--env","FABRIC_RECOVERY_REQUIRE_PG_PROVENANCE=1","--env","FABRIC_BACKUP_RUN_ID=fixture-"+token,
            "--env","FABRIC_BACKUP_DIR=/tmp/recovery-backups","--env",
            "FABRIC_BACKUP_HEALTH_RECEIPT_FILE=/tmp/recovery-proof/backup-health.json",cid,"sh","-s"],
            data=files[0].read_bytes(),timeout=90)
        health = json.loads(run(["docker","exec",cid,"cat","/tmp/recovery-proof/backup-health.json"]))
        sidecar = json.loads(run(["docker","exec",cid,"cat","/tmp/recovery-proof/"+health["restoreManifest"]["file"]]))
        dump = run(["docker","exec",cid,"cat","/tmp/recovery-backups/"+health["backupFile"]])
        sidecar_bytes = run(["docker","exec",cid,"cat","/tmp/recovery-proof/"+health["restoreManifest"]["file"]])
        if (health.get("status")!="passed" or health.get("sourceIdentityVerified") is not True
            or health.get("sourceIdentity")!=source or sidecar.get("sourceIdentityBefore")!=source
            or sidecar.get("sourceIdentityAfter")!=source or sidecar.get("sourceIdentityVerified") is not True
            or sidecar["backupSha256"]!=hashlib.sha256(dump).hexdigest() or sidecar["backupBytes"]!=len(dump)
            or health["restoreManifest"]["sha256"]!=hashlib.sha256(sidecar_bytes).hexdigest()
            or any(sidecar.get(flag) is not True for flag in ("restoreDatabaseCreated","restoreCompleted",
                "readbackCompleted","restoreDatabaseDropped"))):
            raise ValueError("actual backup/source/disposable restore byte provenance differs")
        private(output/"native-backup-health.json",health)
        # The native health receipt binds the original writer's sidecar bytes;
        # reserializing its parsed object would destroy that byte provenance.
        private(output/"native-restore-sidecar.json",sidecar_bytes)
        private(output/"native-ledger.dump",dump)
        stage = "native_readonly_export"
        server = ThreadingHTTPServer(("127.0.0.1",0),Listing)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        url = "postgres://recovery_reader:"+quote(reader_password,safe="")+"@127.0.0.1:"+str(port)+"/"+database
        private(credential,{"accessKeyId":"fixture-only","secretAccessKey":"fixture-only","databaseUrl":url})
        plan = {"schemaVersion":"execution-fabric-recovery-export-plan/v1","sourceHost":"isolated-fixture",
            "endpoint":"http://127.0.0.1:"+str(server.server_port),"bucket":"fixture-artifacts","region":"us-east-1",
            "credentialFile":str(credential),"readOnlyDatabaseRole":"recovery_reader","ownerBinding":"isolated-fixture-owner",
            "maxVersions":100,"maxBytes":1024,"expectedPostgresSource":{k:source[k] for k in
                ("systemId","database","databaseOid","majorVersion")}}
        def export(label, value, expected_ok):
            plan_path = output/(label+".plan.json")
            receipt = output/(label+".receipt.json")
            private(plan_path,value)
            result = subprocess.run(["node",str(files[1]),"--plan",str(plan_path),"--receipt",str(receipt),
                "--watermark-only"],env={**os.environ,"FABRIC_HOST_ID":"isolated-fixture"},capture_output=True,timeout=45,check=False)
            if (result.returncode==0) != expected_ok or receipt.exists()!=expected_ok:
                try:
                    failure = json.loads(result.stderr).get("failureClass", "unclassified_export_result")
                except (ValueError, AttributeError):
                    failure = "unclassified_export_result"
                raise ValueError("actual read-only exporter qualification/refusal differs: "+str(failure))
            return json.loads(receipt.read_text()) if expected_ok else None
        exported = export("actual-source",plan,True)
        if exported.get("postgresSourceVerified") is not True or exported.get("postgresSource")!=source:
            raise ValueError("actual readonly export and source backup identities differ")
        for field in ("systemId","database","databaseOid","majorVersion"):
            stage = "wrong_declaration_"+field
            changed = json.loads(json.dumps(plan))
            changed["expectedPostgresSource"][field] = source[field]+1 if field=="majorVersion" else "99999"
            export("wrong-"+field,changed,False)
        other = database+"_other"
        stage = "foreign_database_refusal"
        sql("CREATE DATABASE "+other+";")
        credential.unlink()
        private(credential,{"accessKeyId":"fixture-only","secretAccessKey":"fixture-only",
            "databaseUrl":url.rsplit("/",1)[0]+"/"+other})
        export("foreign-database-endpoint",plan,False)
        credential.unlink()
        private(credential,{"accessKeyId":"fixture-only","secretAccessKey":"fixture-only","databaseUrl":url})
        sql("REVOKE EXECUTE ON FUNCTION pg_catalog.pg_control_system() FROM PUBLIC, recovery_reader;")
        stage = "missing_function_access_refusal"
        export("missing-readonly-function-access",plan,False)
        if json.loads(sql(SOURCE_SQL))!=source or sql("SELECT count(*) FROM recovery_canary WHERE payload='immutable source row';").strip()!=b"1":
            raise ValueError("source authority/canary changed during readonly qualification")
        accepted = True
        evidence.update(sourceIdentity=source, backupRunId=health["runId"],
            backupSha256=health["backupSha256"],backupBytes=len(dump),
            restoreSidecarSha256=hashlib.sha256(sidecar_bytes).hexdigest(),
            restoreReadbackSha256=sidecar["readbackManifestSha256"],dumpRestoreReadbackVerified=True,
            nonElevatedReadonlyExportVerified=True,actualWrongDeclarationRefusals=4,
            actualForeignDatabaseRefused=True,missingFunctionAccessRefusedWithoutFallback=True,
            sourceCanaryPreserved=True,s3ListingAdapterOnly=True,containerId=cid,imageId=image_id)
    except Exception as exc:
        evidence["status"]="held"
        evidence["reason"]="isolated native PostgreSQL provenance qualification failed; private details withheld"
        evidence["failedStage"]=stage
        evidence["failureClass"]=str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    finally:
        credential.unlink(missing_ok=True)
        if server:
            server.shutdown()
            server.server_close()
        if attempted:
            try:
                value = inspected(cid or name)
                actual = own(value,name,token,cid)
                run(["docker","rm","--force","--volumes",actual])
                cleaned = not run(["docker","container","ls","--all","--filter","id="+actual,"--format","{{.ID}}"]).strip()
            except Exception:
                cleaned = False
        else:
            cleaned = True
        evidence["containerTeardownVerified"]=cleaned
        evidence["status"]="postgres_provenance_qualified" if accepted and cleaned else "held"
        evidence["finishedAt"]=datetime.now(timezone.utc).isoformat()
        private(output/"terminal.json",evidence)
    return 0 if accepted and cleaned else 1

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args = parser.parse_args()
    return execute(args.root,args.output)

if __name__=="__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "earthai:latest"


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout


def main():
    service = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]["earthai"]
    assert service["image"] == IMAGE
    assert service["user"] == "0:0"
    assert service["ports"] == ["0.0.0.0:8000:8000"]
    assert service.get("privileged", False) is False
    document = yaml.safe_load((ROOT / "compose.yaml").read_text())
    assert set(document) == {"services"}
    assert "volumes" not in service
    assert not (ROOT / "compose.nas.yaml").exists()
    assert "EARTHAI_STATE_DIR" not in service["environment"]
    assert "EARTHAI_UPLOADS_DIR" not in service["environment"]
    assert "EARTHAI_NAS_DIR" not in service["environment"]
    assert service["environment"]["EARTHAI_DATA_DIR"] == "/app/data"
    assert service["environment"]["EARTHAI_SQLITE_JOURNAL_MODE"] == "DELETE"
    code = '''import os,pwd,grp,json
from pathlib import Path
from fastapi.testclient import TestClient
from backend import store
from backend.main import app
assert os.getuid()==0
assert [u.pw_name for u in pwd.getpwall()]==["root"]
assert [g.gr_name for g in grp.getgrall()]==["root"]
assert len(list(Path("frontend/dist/fonts").glob("*.woff2")))==103
with TestClient(app) as client:
 response=client.post("/api/auth/login",json={"email":"admin","password":"admin"})
 assert response.status_code==200 and response.json()["must_change_password"]
 assert client.get("/api/admin/overview").status_code==403
 response=client.post("/api/auth/password",json={"current_password":"admin","new_password":"Temporary-Smoke-2026!"})
 assert response.status_code==200
 counts=client.get("/api/admin/overview").json()["counts"]
 defaults_per_kind={kind:counts[kind] for kind in ("agents","knowledge","skills")}
 assert defaults_per_kind=={"agents":50,"knowledge":50,"skills":100}
 knowledge=client.get("/api/admin/defaults/knowledge").json()
 assert len(knowledge)==50 and all(3<=item["document_count"]<=12 for item in knowledge)
 document_count=sum(item["document_count"] for item in knowledge)
 assert 150<=document_count<=600
 with store.connect() as db:
  assert db.execute("SELECT count(*) FROM template_documents").fetchone()[0]==document_count
 assert client.get("/api/health").status_code==200
 assert client.get("/fonts/fonts.css").status_code==200
 assert client.get("/vendor/docs/swagger-ui/swagger-ui-bundle.js").status_code==200
 assert client.get("/site.webmanifest").json()["short_name"]=="EarthAI"
 assert len(client.get("/api/guides").json())==11
 assert len(client.get("/api/admin/guides?audience=user").json())==12
print(json.dumps({"uid":os.getuid(),"accounts":[u.pw_name for u in pwd.getpwall()],"groups":[g.gr_name for g in grp.getgrall()],"fonts":103,"defaults_per_kind":defaults_per_kind,"knowledge_document_count":document_count,"knowledge_document_counts":sorted({item["document_count"] for item in knowledge}),"initial_admin":True,"forced_password_change":True,"health":"ok"}))'''
    result = json.loads(docker("run", "--rm", "--network", "none", "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER", "--security-opt", "no-new-privileges:true", "--entrypoint", "python", "-e", "EARTHAI_DATA_DIR=/tmp/earthai-admin-image-smoke", IMAGE, "-c", code))
    nas_code = '''import base64,json,os
from pathlib import Path
from fastapi.testclient import TestClient
from backend import store,usage
from backend.main import app
root=Path("/app/data")
assert store.DATA_ROOT==root and store.DATA==root and store.UPLOADS==root/"uploads"
phase=os.environ["EARTHAI_SMOKE_PHASE"]
fixture=json.loads(os.environ.get("EARTHAI_SMOKE_FIXTURE","{}"))
shared_content=b"single mount shared team upload evidence"
with TestClient(app) as client:
 with store.connect() as db:
  assert db.execute("PRAGMA journal_mode").fetchone()[0]=="delete"
  assert db.execute("PRAGMA synchronous").fetchone()[0]==2
 if phase=="create":
  login=client.post("/api/auth/login",json={"email":"admin","password":"admin"})
  assert login.status_code==200,login.text
  admin_id=login.json()["id"]
  assert client.post("/api/auth/password",json={"current_password":"admin","new_password":"NAS-Smoke-2026!"}).status_code==200
  png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII=")
  asset=client.post("/api/admin/branding/assets",files={"file":("isolated.png",png,"image/png")})
  assert asset.status_code==200,asset.text
  assert client.patch("/api/admin/branding",json={"name":"NAS persistence smoke","icon_url":asset.json()["url"]}).status_code==200
  remote_source=client.post("/api/admin/defaults/agents",json={"name":"Persistent default remote","kind":"remote","url":"https://isolated.example.invalid/remote","control_level":"observe"})
  assert remote_source.status_code==200,remote_source.text
  remote_template=remote_source.json()["id"]
  user=client.post("/api/auth/register",json={"email":"nas-smoke@example.com","password":"NAS-Smoke-2026!","name":"Isolated NAS persistence smoke"})
  assert user.status_code==200,user.text
  owner=user.json()["id"]
  assert user.json()["role"]=="user" and user.json()["space_modules"]==["personal"]
  assert client.get("/api/team-spaces").status_code==403
  catalogs={kind:client.get("/api/"+kind).json() for kind in ("agents","knowledge","skills")}
  assert {kind:len(items) for kind,items in catalogs.items()}=={"agents":51,"knowledge":50,"skills":100}
  assert all(3<=item["document_count"]<=12 for item in catalogs["knowledge"])
  document_count=sum(item["document_count"] for item in catalogs["knowledge"])
  assert 150<=document_count<=600
  with store.connect() as db:
   assert db.execute("SELECT count(*) FROM template_documents").fetchone()[0]==document_count
   assert db.execute("SELECT count(*) FROM documents WHERE owner=?",(owner,)).fetchone()[0]==document_count
   assert db.execute("SELECT count(DISTINCT document_id) FROM chunks WHERE owner=?",(owner,)).fetchone()[0]==document_count
   assert db.execute("SELECT count(*) FROM chunks WHERE owner=?",(owner,)).fetchone()[0]==sum(item["chunk_count"] for item in catalogs["knowledge"])
  response=client.post("/api/files",files={"file":("isolated.txt",b"single mount upload evidence","text/plain")})
  assert response.status_code==200,response.text
  personal_file=response.json()["id"]
  store.save_entity(owner,"providers",{"name":"Offline credential evidence","api_key":store.seal("isolated-provider-secret")})
  resources=[(kind,next(item for item in catalogs[kind] if kind!="agents" or item.get("kind","local")=="local" and item.get("control_level","observe")=="observe")) for kind in ("agents","knowledge","skills")]
  usage.record(owner,"isolated-nas-usage",resources)
  usage.record(owner,"isolated-nas-usage",resources)
  remote_copy=next(item for item in client.get("/api/agents").json() if item.get("default_template_id")==remote_template)
  assert remote_copy["read_only"] is True
  assert client.post("/api/agents/"+remote_copy["id"]+"/open").status_code==200
  assert client.post("/api/agents/"+remote_copy["id"]+"/open").status_code==200
  local=next(value for kind,value in resources if kind=="agents")
  response=client.patch("/api/agents/"+local["id"],json={"name":"Persistent personal local","control_level":"observe"})
  assert response.status_code==200 and response.json()["personal_override"] is True,response.text
  skill=next(value for kind,value in resources if kind=="skills")
  assert client.patch("/api/skills/"+skill["id"],json={"name":"Persistent personal skill","enabled":False}).json()["personal_override"] is True
  knowledge=next(value for kind,value in resources if kind=="knowledge")
  assert client.delete("/api/knowledge/"+knowledge["id"]).status_code==200
  owner_token=client.cookies.get("earthai_session")
  response=client.post("/api/auth/register",json={"email":"nas-team-member@example.com","password":"NAS-Smoke-2026!","name":"Isolated team member"})
  assert response.status_code==200,response.text
  member=response.json()["id"]
  assert response.json()["role"]=="user" and response.json()["space_modules"]==["personal"]
  assert client.get("/api/team-spaces").status_code==403
  member_token=client.cookies.get("earthai_session")
  assert client.post("/api/auth/login",json={"email":"admin","password":"NAS-Smoke-2026!"}).status_code==200
  admin_token=client.cookies.get("earthai_session")
  response=client.patch("/api/admin/users/"+admin_id,json={"space_modules":[]})
  assert response.status_code==200 and response.json()["role"]=="admin" and response.json()["space_modules"]==[],response.text
  assert client.get("/api/admin/team-spaces").json()==[]
  response=client.patch("/api/admin/users/"+owner,json={"space_modules":["personal","team"]})
  assert response.status_code==200 and response.json()["space_modules"]==["personal","team"] and response.json()["team_invites_blocked"] is False,response.text
  client.cookies.clear()
  client.cookies.set("earthai_session",owner_token)
  assert client.get("/api/auth/me").json()["space_modules"]==["personal","team"]
  response=client.post("/api/team-spaces",json={"name":"Persistent shared team","description":"Single temporary bind fixture"})
  assert response.status_code==200,response.text
  space=response.json()["id"]
  assert response.json()["owner_id"]==owner and response.json()["role"]=="owner"
  team_path="/api/team-spaces/"+space
  admin_team_path="/api/admin/team-spaces/"+space
  response=client.post(team_path+"/members",json={"email":"nas-team-member@example.com","role":"editor"})
  assert response.status_code==200 and response.json()["user_id"]==member and response.json()["role"]=="editor" and response.json()["team_module_enabled"] is True,response.text
  client.cookies.clear()
  client.cookies.set("earthai_session",member_token)
  assert client.get("/api/auth/me").json()["space_modules"]==["personal","team"]
  assert client.get(team_path).json()["role"]=="editor"
  response=client.post(team_path+"/files",files={"file":("shared-isolated.txt",shared_content,"text/plain")})
  assert response.status_code==200,response.text
  shared_file=response.json()["id"]
  assert response.json()["space_id"]==space and response.json()["uploader_id"]==member
  client.cookies.clear()
  client.cookies.set("earthai_session",admin_token)
  response=client.patch("/api/admin/users/"+owner,json={"space_modules":["team"]})
  assert response.status_code==200 and response.json()["space_modules"]==["team"] and response.json()["team_invites_blocked"] is False,response.text
  response=client.patch("/api/admin/users/"+member,json={"space_modules":["personal"]})
  assert response.status_code==200 and response.json()["space_modules"]==["personal"] and response.json()["team_invites_blocked"] is True,response.text
  client.cookies.clear()
  client.cookies.set("earthai_session",member_token)
  assert client.get(team_path+"/files/"+shared_file+"/download").status_code==403
  client.cookies.clear()
  client.cookies.set("earthai_session",owner_token)
  assert client.get("/api/files").status_code==403
  assert client.get("/api/files/"+personal_file+"/download").status_code==403
  assert client.delete("/api/files/"+personal_file).status_code==403
  assert client.get(team_path+"/files/"+shared_file+"/download").content==shared_content
  assert {item["user_id"]:item["role"] for item in client.get(team_path+"/members").json()}=={owner:"owner",member:"editor"}
  assert client.delete(team_path+"/members/"+member).status_code==200
  response=client.post(team_path+"/members",json={"email":"nas-team-member@example.com","role":"manager"})
  assert response.status_code==409 and "平台关闭" in response.json()["detail"],response.text
  assert [item["user_id"] for item in client.get(team_path+"/members").json()]==[owner]
  client.cookies.clear()
  client.cookies.set("earthai_session",admin_token)
  response=client.post(admin_team_path+"/members",json={"email":"nas-team-member@example.com","role":"manager"})
  assert response.status_code==409 and "平台关闭" in response.json()["detail"],response.text
  response=client.patch("/api/admin/users/"+member,json={"space_modules":["personal","team"]})
  assert response.status_code==200 and response.json()["space_modules"]==["personal","team"] and response.json()["team_invites_blocked"] is False,response.text
  client.cookies.clear()
  client.cookies.set("earthai_session",owner_token)
  response=client.post(team_path+"/members",json={"email":"nas-team-member@example.com","role":"manager"})
  assert response.status_code==200 and response.json()["role"]=="manager" and response.json()["team_module_enabled"] is True,response.text
  client.cookies.clear()
  client.cookies.set("earthai_session",admin_token)
  response=client.patch("/api/admin/users/"+owner,json={"space_modules":[]})
  assert response.status_code==200 and response.json()["space_modules"]==[] and response.json()["team_invites_blocked"] is True,response.text
  client.cookies.clear()
  client.cookies.set("earthai_session",owner_token)
  me=client.get("/api/auth/me").json()
  assert me["role"]=="user" and me["space_modules"]==[] and me["team_invites_blocked"] is True
  assert client.get("/api/files").status_code==403 and client.get("/api/files/"+personal_file+"/download").status_code==403
  assert client.get("/api/team-spaces").status_code==403 and client.get(team_path+"/members").status_code==403
  assert client.get(team_path+"/files/"+shared_file+"/download").status_code==403
  client.cookies.clear()
  client.cookies.set("earthai_session",admin_token)
  assert client.get("/api/auth/me").json()["space_modules"]==[]
  response=client.patch(admin_team_path,json={"description":"Admin governance without personal or team modules"})
  assert response.status_code==200 and response.json()["role"]=="admin" and response.json()["file_count"]==1 and response.json()["member_count"]==2,response.text
  assert client.get(admin_team_path+"/files/"+shared_file+"/download").content==shared_content
  assert client.delete(admin_team_path).status_code==200
  assert client.get("/api/admin/team-spaces").json()==[]
  archived=client.get("/api/admin/team-spaces?include_archived=true").json()
  assert len(archived)==1 and archived[0]["id"]==space and archived[0]["archived"] is True
  assert client.get(admin_team_path+"/files/"+shared_file+"/download").status_code==409
  assert client.delete("/api/admin/users/"+owner).status_code==409
  assert client.patch("/api/admin/users/"+owner,json={"role":"admin"}).status_code==409
  fixture={"admin_id":admin_id,"owner_id":owner,"member_id":member,"space_id":space,"personal_file_id":personal_file,"team_file_id":shared_file}
  conversation=store.save_entity(owner,"conversations",{"title":"persisted conversation"})
  store.add_message(owner,conversation["id"],"user","persisted conversation message")
  with store.connect() as db:
   db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)",("isolated-active-run",owner,conversation["id"],"running",store.dumps({"goal":"isolated interrupted task"}),store.now(),store.now()))
  store.emit("isolated-active-run","status",{"status":"running"})
 else:
  client.cookies.clear()
  login=client.post("/api/auth/login",json={"email":"nas-smoke@example.com","password":"NAS-Smoke-2026!"})
  assert login.status_code==200,login.text
  owner=login.json()["id"]
  assert owner==fixture["owner_id"] and login.json()["role"]=="user" and login.json()["space_modules"]==[] and login.json()["team_invites_blocked"] is True
  personal_file=fixture["personal_file_id"]
  space=fixture["space_id"]
  shared_file=fixture["team_file_id"]
  member=fixture["member_id"]
  team_path="/api/team-spaces/"+space
  admin_team_path="/api/admin/team-spaces/"+space
  assert client.get("/api/files").status_code==403 and client.get("/api/files/"+personal_file+"/download").status_code==403
  assert client.get("/api/team-spaces").status_code==403 and client.get(team_path+"/files/"+shared_file+"/download").status_code==403
  login=client.post("/api/auth/login",json={"email":"nas-team-member@example.com","password":"NAS-Smoke-2026!"})
  assert login.status_code==200 and login.json()["id"]==member and login.json()["role"]=="user" and login.json()["space_modules"]==["personal","team"] and login.json()["team_invites_blocked"] is False,login.text
  member_token=client.cookies.get("earthai_session")
  assert client.get("/api/team-spaces").json()==[]
  archived=client.get("/api/team-spaces?include_archived=true").json()
  assert len(archived)==1 and archived[0]["id"]==space and archived[0]["role"]=="manager" and archived[0]["archived"] is True
  assert client.get(team_path+"/files/"+shared_file+"/download").status_code==409
  login=client.post("/api/auth/login",json={"email":"admin","password":"NAS-Smoke-2026!"})
  assert login.status_code==200 and login.json()["id"]==fixture["admin_id"] and login.json()["role"]=="admin" and login.json()["space_modules"]==[],login.text
  admin_token=client.cookies.get("earthai_session")
  assert client.get("/api/admin/overview").status_code==200
  assert client.get("/api/admin/team-spaces").json()==[]
  archived=client.get("/api/admin/team-spaces?include_archived=true").json()
  assert len(archived)==1 and archived[0]["id"]==space and archived[0]["owner_id"]==owner and archived[0]["archived"] is True
  assert archived[0]["member_count"]==2 and archived[0]["file_count"]==1
  assert client.get(admin_team_path+"/files/"+shared_file+"/download").status_code==409
  assert client.delete("/api/admin/users/"+owner).status_code==409
  assert client.patch("/api/admin/users/"+owner,json={"role":"admin"}).status_code==409
  response=client.post(admin_team_path+"/restore")
  assert response.status_code==200 and response.json()["id"]==space and response.json()["owner_id"]==owner and response.json()["archived"] is False and response.json()["role"]=="admin",response.text
  files=client.get(admin_team_path+"/files").json()
  assert len(files)==1 and files[0]["id"]==shared_file and files[0]["uploader_id"]==member
  assert client.get(admin_team_path+"/files/"+shared_file+"/download").content==shared_content
  client.cookies.clear()
  client.cookies.set("earthai_session",member_token)
  assert client.get(team_path).json()["role"]=="manager"
  assert client.get(team_path+"/files/"+shared_file+"/download").content==shared_content
  client.cookies.clear()
  client.cookies.set("earthai_session",admin_token)
  response=client.patch("/api/admin/users/"+owner,json={"space_modules":["personal","team"]})
  assert response.status_code==200 and response.json()["space_modules"]==["personal","team"] and response.json()["team_invites_blocked"] is False,response.text
  client.cookies.clear()
  login=client.post("/api/auth/login",json={"email":"nas-smoke@example.com","password":"NAS-Smoke-2026!"})
  assert login.status_code==200 and login.json()["id"]==owner and login.json()["role"]=="user" and login.json()["space_modules"]==["personal","team"] and login.json()["team_invites_blocked"] is False,login.text
  assert client.get(team_path).json()["role"]=="owner"
  members=client.get(team_path+"/members").json()
  assert {item["user_id"]:item["role"] for item in members}=={owner:"owner",member:"manager"} and all(item["team_module_enabled"] for item in members)
  assert client.get(team_path+"/files/"+shared_file+"/download").content==shared_content
  files=client.get("/api/files").json()
  assert len(files)==1 and files[0]["id"]==personal_file and client.get("/api/files/"+personal_file+"/download").content==b"single mount upload evidence"
  provider=next(p for p in store.list_entities(owner,"providers") if p["name"]=="Offline credential evidence")
  assert store.unseal(provider["api_key"])=="isolated-provider-secret"
  conversations=store.list_entities(owner,"conversations")
  assert len(conversations)==1
  assert store.list_messages(owner,conversations[0]["id"])[0]["content"]=="persisted conversation message"
  assert store.get_run(owner,"isolated-active-run")["status"]=="interrupted"
  assert store.events("isolated-active-run")[-1]["type"]=="done"
  with store.connect() as db:
   states=db.execute("SELECT * FROM default_owner_states WHERE owner=? ORDER BY state,template_id",(owner,)).fetchall()
   assert len(states)==3 and sum(row["state"]=="override" for row in states)==2
   assert db.execute("SELECT count(*) FROM remote_agent_clicks WHERE owner=?",(owner,)).fetchone()[0]==2
  for state in states:
   current=store.get_entity(owner,"knowledge" if state["state"]=="deleted" else "agents",state["entity_id"])
   if state["state"]=="deleted":
    assert current is None
  assert next(item for item in client.get("/api/agents").json() if item["name"]=="Persistent personal local")["personal_override"] is True
  assert next(item for item in client.get("/api/skills").json() if item["name"]=="Persistent personal skill")["enabled"] is False
 personal=store.get_entity(owner,"files",fixture["personal_file_id"])
 assert personal is not None and (store.UPLOADS/personal["storage_name"]).read_bytes()==b"single mount upload evidence"
 with store.connect() as db:
  team=db.execute("SELECT * FROM team_spaces WHERE id=?",(fixture["space_id"],)).fetchone()
  assert team is not None and team["owner_id"]==owner and (team["deleted_at"] is not None)==(phase=="create")
  shared=db.execute("SELECT * FROM team_files WHERE id=?",(fixture["team_file_id"],)).fetchone()
  assert shared is not None and shared["space_id"]==fixture["space_id"] and shared["uploader_id"]==fixture["member_id"] and shared["size"]==len(shared_content)
  assert (store.UPLOADS/shared["storage_name"]).read_bytes()==shared_content
  assert {row["user_id"]:row["role"] for row in db.execute("SELECT user_id,role FROM team_members WHERE space_id=?",(fixture["space_id"],))}=={owner:"owner",fixture["member_id"]:"manager"}
  assert db.execute("SELECT count(*) FROM team_spaces").fetchone()[0]==1
  assert db.execute("SELECT count(*) FROM team_files").fetchone()[0]==1
  assert db.execute("SELECT count(*) FROM team_members").fetchone()[0]==2
 client.cookies.clear()
 assert client.post("/api/auth/login",json={"email":"admin","password":"NAS-Smoke-2026!"}).status_code==200
 assert client.get("/api/auth/me").json()["space_modules"]==[]
 accounts={item["id"]:item for item in client.get("/api/admin/users").json()}
 assert len(accounts)==3 and accounts[fixture["admin_id"]]["role"]=="admin"
 assert accounts[owner]["role"]=="user" and accounts[owner]["space_modules"]==([] if phase=="create" else ["personal","team"]) and accounts[owner]["team_invites_blocked"] is (phase=="create")
 assert accounts[fixture["member_id"]]["role"]=="user" and accounts[fixture["member_id"]]["space_modules"]==["personal","team"] and accounts[fixture["member_id"]]["team_invites_blocked"] is False
 members=client.get("/api/admin/team-spaces/"+fixture["space_id"]+"/members").json()
 assert {item["user_id"]:item["role"] for item in members}=={owner:"owner",fixture["member_id"]:"manager"}
 assert {item["user_id"]:item["team_module_enabled"] for item in members}=={owner:phase!="create",fixture["member_id"]:True}
 totals=client.get("/api/admin/overview").json()["usage"]["totals"]
 assert totals=={"agents":3,"knowledge":1,"skills":1}
 assert client.get("/api/branding").json()["name"]=="NAS persistence smoke"
 assert client.get(client.get("/api/branding").json()["icon_url"]).status_code==200
 assert (root/"earthai.db").is_file() and (root/"master.key").is_file()
 assert len(list((root/"uploads").iterdir()))==2 and len(list((root/"branding").iterdir()))==1
 assert not Path("/app/state").exists()
print(json.dumps({"ok":True,"phase":phase,"fixture":fixture,"single_mount":True,"all_data_at":"/app/data","journal_mode":"DELETE","synchronous":"FULL","usage_totals_with_remote_clicks":totals,"personal_states_preserved":True,"team_module_persistence":True,"team_archive_preserved":phase=="create","team_restored_after_recreation":phase=="reopen","invitation_auto_enable":True,"explicit_team_disable_blocks_invites":True,"admin_governance_without_modules":True,"owner_account_protected":True,"original_file_ids_and_bytes_preserved":True,"real_nas_measured":False}))'''
    with tempfile.TemporaryDirectory(prefix="earthai-single-nas-smoke-", dir=ROOT.parent / ".tools") as directory:
        arguments = ("run", "--rm", "--network", "none", "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER", "--security-opt", "no-new-privileges:true", "--entrypoint", "python", "--mount", f"type=bind,source={directory},target=/app/data", "-e", "EARTHAI_DATA_DIR=/app/data", "-e", "EARTHAI_SQLITE_JOURNAL_MODE=DELETE")
        key_check = "import hashlib; from pathlib import Path; print(hashlib.sha256(Path('/app/data/master.key').read_bytes()).hexdigest())"
        try:
            created = json.loads(docker(*arguments, "-e", "EARTHAI_SMOKE_PHASE=create", IMAGE, "-c", nas_code))
            original_key_digest = docker(*arguments, IMAGE, "-c", key_check)
            reopened = json.loads(docker(*arguments, "-e", "EARTHAI_SMOKE_PHASE=reopen", "-e", "EARTHAI_SMOKE_FIXTURE=" + json.dumps(created["fixture"]), IMAGE, "-c", nas_code))
            assert reopened["fixture"] == created["fixture"]
            assert docker(*arguments, IMAGE, "-c", key_check) == original_key_digest
        finally:
            cleanup = f"import os; from pathlib import Path; p=Path('/app/data'); [os.chown(x,{os.getuid()},{os.getgid()}) for x in [*p.rglob('*'),p]]"
            docker("run", "--rm", "--network", "none", "--entrypoint", "python", "--mount", f"type=bind,source={directory},target=/app/data", IMAGE, "-c", cleanup)
    nas_result = {"ok": True, "create_container": created, "recreated_container": reopened, "original_key_preserved": True, "separate_container_recreation": True, "only_one_bind_mount": True, "real_nas_measured": False}
    image = json.loads(docker("image", "inspect", IMAGE))[0]
    config = image["Config"]
    assert config["User"] == "root"
    assert config["Cmd"][config["Cmd"].index("--host") + 1] == "0.0.0.0"
    report = {"ok": True, "image": IMAGE, "image_id": image["Id"], "image_created_at": image["Created"], "network": "none", "container_smoke": result, "single_nas_storage_smoke": nas_result, "compose_user": service["user"], "ports": service["ports"], "privileged": service.get("privileged", False), "privileged_field_present": "privileged" in service, "cap_drop": service["cap_drop"], "cap_add": service["cap_add"], "compose_defines_data_mount": False, "data_mount_managed_by": "deployment_platform", "user_data_volumes_used": False, "temporary_test_bind_used": True, "app_bind": "0.0.0.0"}
    (ROOT / "docs" / "admin-container-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

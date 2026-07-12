"""Auth + persistence routes (demo-grade). Mounted under /api by main.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import auth
import db
from auth import current_user
from inflectiv import InflectivClient, InflectivError
from schemas import (
    ComponentSave, DashboardSave, ForgotRequest, LoginRequest, ProfileUpdate,
    ResetRequest, SessionRequest, SettingsUpdate, SignupRequest, TeamInvite, WorkspaceSave,
)

router = APIRouter(prefix="/api")


# ---------------- auth ----------------
@router.post("/auth/signup")
def signup(req: SignupRequest):
    email = req.email.strip().lower()
    if db.one("SELECT id FROM users WHERE email=%s", (email,)):
        raise HTTPException(400, "An account with this email already exists.")
    salt = auth.make_salt()
    token = auth.make_token()
    user = db.execute(
        """INSERT INTO users (email,name,company,pw_hash,pw_salt,api_token,
             inflectiv_key,inflectiv_dataset_id,inflectiv_dataset_name,
             db_type,db_connection_string,db_table_name,onboarding,ai_prefs)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (email, req.name, req.company, auth.hash_pw(req.password, salt), salt, token,
         req.inflectiv_key, req.inflectiv_dataset_id, req.inflectiv_dataset_name,
         req.db_type, req.db_connection_string, req.db_table_name,
         db.Json(req.onboarding or {}), db.Json(req.ai_prefs or {})),
    )
    # seed the owner into team_members
    db.execute("INSERT INTO team_members (owner_id,email,name,role,status) VALUES (%s,%s,%s,'owner','active')",
               (user["id"], email, req.name))
    db.log_activity(user["id"], "signup", email)
    return {"token": token, "user": auth.public_user(user)}


@router.post("/auth/login")
def login(req: LoginRequest):
    user = db.one("SELECT * FROM users WHERE email=%s", (req.email.strip().lower(),))
    if not user or not auth.verify_pw(user, req.password):
        raise HTTPException(401, "Invalid email or password.")
    db.log_activity(user["id"], "login", user["email"])
    return {"token": user["api_token"], "user": auth.public_user(user)}


@router.post("/auth/forgot")
def forgot(req: ForgotRequest):
    # demo stub: never reveal existence; the reset wizard just advances
    return {"ok": True}


@router.post("/auth/reset")
def reset(req: ResetRequest):
    user = db.one("SELECT * FROM users WHERE email=%s", (req.email.strip().lower(),))
    if user:
        salt = auth.make_salt()
        db.execute("UPDATE users SET pw_hash=%s, pw_salt=%s WHERE id=%s",
                   (auth.hash_pw(req.password, salt), salt, user["id"]))
    return {"ok": True}


# ---------------- me / settings ----------------
@router.get("/me")
def get_me(user: dict = Depends(current_user)):
    return {"user": auth.public_user(user), "stats": _stats(user["id"])}


@router.patch("/me")
def update_me(req: ProfileUpdate, user: dict = Depends(current_user)):
    fields, vals = [], []
    for k in ("name", "company", "inflectiv_dataset_id", "inflectiv_dataset_name",
              "db_type", "db_connection_string", "db_table_name"):
        v = getattr(req, k)
        if v is not None:
            fields.append(f"{k}=%s"); vals.append(v)
    if req.ai_prefs is not None:
        fields.append("ai_prefs=%s"); vals.append(db.Json(req.ai_prefs))
    if fields:
        vals.append(user["id"])
        db.execute(f"UPDATE users SET {','.join(fields)} WHERE id=%s", tuple(vals))
    return {"user": auth.public_user(db.one("SELECT * FROM users WHERE id=%s", (user["id"],)))}


@router.get("/settings")
def get_settings(user: dict = Depends(current_user)):
    return {"settings": user.get("settings") or {}}


@router.patch("/settings")
def patch_settings(req: SettingsUpdate, user: dict = Depends(current_user)):
    db.execute("UPDATE users SET settings=%s WHERE id=%s", (db.Json(req.settings), user["id"]))
    db.log_activity(user["id"], "settings_change", "")
    return {"settings": req.settings}


# ---------------- dashboards ----------------
@router.get("/dashboards")
def list_dashboards(user: dict = Depends(current_user)):
    return {"dashboards": db.query(
        "SELECT id,name,dataset_name,jsonb_array_length(widgets) AS widget_count,updated_at "
        "FROM dashboards WHERE user_id=%s ORDER BY updated_at DESC", (user["id"],))}


@router.post("/dashboards")
def save_dashboard(req: DashboardSave, user: dict = Depends(current_user)):
    row = db.execute(
        "INSERT INTO dashboards (user_id,name,widgets,dataset_id,dataset_name) "
        "VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (user["id"], req.name, db.Json(req.widgets), req.dataset_id, req.dataset_name))
    db.log_activity(user["id"], "save_dashboard", req.name)
    return {"id": row["id"]}


@router.get("/dashboards/{dash_id}")
def get_dashboard(dash_id: int, user: dict = Depends(current_user)):
    d = db.one("SELECT * FROM dashboards WHERE id=%s AND user_id=%s", (dash_id, user["id"]))
    if not d:
        raise HTTPException(404, "Not found")
    return {"id": d["id"], "name": d["name"], "widgets": d["widgets"], "dataset_name": d.get("dataset_name")}


@router.put("/dashboards/{dash_id}")
def update_dashboard(dash_id: int, req: DashboardSave, user: dict = Depends(current_user)):
    db.execute("UPDATE dashboards SET name=%s,widgets=%s,updated_at=now() WHERE id=%s AND user_id=%s",
               (req.name, db.Json(req.widgets), dash_id, user["id"]))
    return {"id": dash_id}


@router.delete("/dashboards/{dash_id}")
def delete_dashboard(dash_id: int, user: dict = Depends(current_user)):
    db.execute("DELETE FROM dashboards WHERE id=%s AND user_id=%s", (dash_id, user["id"]))
    return {"ok": True}


# ---------------- datasets for the logged-in user (App Datasets page) ----------------
@router.get("/my-datasets")
async def my_datasets(user: dict = Depends(current_user)):
    result = {"datasets": [], "db": None}
    key = user.get("inflectiv_key")
    if key:
        try:
            result["datasets"] = await InflectivClient(key).list_datasets()
        except InflectivError:
            pass
    if user.get("db_type"):
        result["db"] = {
            "type": user["db_type"],
            "table_name": user.get("db_table_name"),
        }
    return result


# ---------------- workspace (live canvas autosave) ----------------
@router.get("/workspace")
def get_workspace(user: dict = Depends(current_user)):
    row = db.one("SELECT workspace FROM users WHERE id=%s", (user["id"],))
    return {"workspace": (row or {}).get("workspace") or {}}


@router.put("/workspace")
def put_workspace(req: WorkspaceSave, user: dict = Depends(current_user)):
    db.execute("UPDATE users SET workspace=%s WHERE id=%s",
               (db.Json({"widgets": req.widgets, "drafts": req.drafts,
                         "chatMessages": req.chatMessages}), user["id"]))
    return {"ok": True}


# ---------------- components / insights ----------------
@router.get("/components")
def list_components(type: str = "", fav: str = "", user: dict = Depends(current_user)):
    sql = "SELECT id,spec,goal,type,fav,dataset_name,created_at FROM saved_components WHERE user_id=%s"
    params: list = [user["id"]]
    if type and type != "all":
        sql += " AND type=%s"; params.append(type)
    if fav == "1":
        sql += " AND fav=true"
    sql += " ORDER BY created_at DESC LIMIT 200"
    return {"components": db.query(sql, tuple(params))}


@router.post("/components")
def save_component(req: ComponentSave, user: dict = Depends(current_user)):
    spec = req.spec or {}
    row = db.execute(
        "INSERT INTO saved_components (user_id,spec,goal,type,dataset_name) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (user["id"], db.Json(spec), req.goal, spec.get("type"), spec.get("source")))
    return {"id": row["id"]}


@router.patch("/components/{cid}")
def toggle_fav(cid: int, user: dict = Depends(current_user)):
    db.execute("UPDATE saved_components SET fav = NOT fav WHERE id=%s AND user_id=%s", (cid, user["id"]))
    return {"ok": True}


@router.delete("/components/{cid}")
def delete_component(cid: int, user: dict = Depends(current_user)):
    db.execute("DELETE FROM saved_components WHERE id=%s AND user_id=%s", (cid, user["id"]))
    return {"ok": True}


@router.get("/insights")
def list_insights(user: dict = Depends(current_user)):
    return {"insights": db.query(
        "SELECT id,spec,headline,tone,created_at FROM saved_insights WHERE user_id=%s "
        "ORDER BY created_at DESC LIMIT 200", (user["id"],))}


# ---------------- activity / team / apikeys / stats ----------------
@router.get("/activity")
def get_activity(user: dict = Depends(current_user)):
    return {"activity": db.query(
        "SELECT kind,detail,created_at FROM activity_log WHERE user_id=%s ORDER BY created_at DESC LIMIT 40",
        (user["id"],))}


@router.get("/team")
def get_team(user: dict = Depends(current_user)):
    return {"members": db.query(
        "SELECT id,email,name,role,status,created_at FROM team_members WHERE owner_id=%s ORDER BY created_at",
        (user["id"],))}


@router.post("/team")
def invite_member(req: TeamInvite, user: dict = Depends(current_user)):
    row = db.execute(
        "INSERT INTO team_members (owner_id,email,name,role,status) VALUES (%s,%s,%s,%s,'invited') RETURNING id",
        (user["id"], req.email.strip().lower(), req.name, req.role))
    return {"id": row["id"]}


@router.delete("/team/{mid}")
def remove_member(mid: int, user: dict = Depends(current_user)):
    db.execute("DELETE FROM team_members WHERE id=%s AND owner_id=%s", (mid, user["id"]))
    return {"ok": True}


@router.get("/apikeys")
def list_keys(user: dict = Depends(current_user)):
    rows = db.query("SELECT id,label,token,created_at,last_used FROM api_keys WHERE user_id=%s ORDER BY created_at DESC",
                    (user["id"],))
    for r in rows:  # mask
        t = r.get("token") or ""
        r["masked"] = (t[:7] + "••••" + t[-4:]) if len(t) > 12 else "••••"
        del r["token"]
    return {"keys": rows}


@router.post("/apikeys")
def create_key(user: dict = Depends(current_user)):
    tok = "ada_" + auth.make_token()
    row = db.execute("INSERT INTO api_keys (user_id,label,token) VALUES (%s,%s,%s) RETURNING id",
                     (user["id"], "Production key", tok))
    return {"id": row["id"], "token": tok}  # shown once


@router.delete("/apikeys/{kid}")
def delete_key(kid: int, user: dict = Depends(current_user)):
    db.execute("DELETE FROM api_keys WHERE id=%s AND user_id=%s", (kid, user["id"]))
    return {"ok": True}


def _stats(user_id: int) -> dict:
    def cnt(sql):
        r = db.one(sql, (user_id,))
        return (r or {}).get("n", 0)
    credits = db.one("SELECT COALESCE(SUM((detail)::int),0) AS n FROM activity_log WHERE user_id=%s AND kind='credits'",
                     (user_id,))
    return {
        "dashboards": cnt("SELECT COUNT(*) n FROM dashboards WHERE user_id=%s"),
        "components": cnt("SELECT COUNT(*) n FROM saved_components WHERE user_id=%s"),
        "insights": cnt("SELECT COUNT(*) n FROM saved_insights WHERE user_id=%s"),
        "analyses": cnt("SELECT COUNT(*) n FROM activity_log WHERE user_id=%s AND kind='generate'"),
        "credits_used": (credits or {}).get("n", 0),
    }


@router.get("/stats")
def get_stats(user: dict = Depends(current_user)):
    return _stats(user["id"])

from __future__ import annotations
from pathlib import Path
import uuid
import json
import math
from datetime import date, datetime, timedelta, time
from starlette.responses import RedirectResponse
from sqlalchemy import Column, Integer, Date, DateTime, Enum, DECIMAL, Float, String
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from datetime import date, datetime, time, timedelta
from fastapi import FastAPI, Request,Form,Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import UploadFile, File
from sqlalchemy import and_, func, text
from sqlalchemy.orm import Session
from fastapi import FastAPI, Request, Depends
from fastapi import APIRouter

from db import Base, engine, get_db
from models import (
    Employee,
    AttendanceLog,
    WorkDocumentation,
    User,
    DailySettings,
    SupportTicket,
    AttendanceAdjustment,
    PayrollAdjustment,
    Message,
    EmployeeNote,
    SupportTicketReply,
    PayrollBatch,
    PayrollRecord,
    AttendanceEarlyLeaveSegment,
)
from auth import hash_pin, verify_pin, create_token, verify_token
from config import TIMEZONE_NAME

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

from sqlalchemy import text
 


import urllib.request
import urllib.parse
from db import engine
from models import Base
# IMPORTANT: app must be defined BEFORE any @app.* decorators below.
Base.metadata.create_all(bind=engine)
def cleanup_old_videos(db: Session, days: int = 7) -> int:
    """Delete video files + clear video_path for logs older than `days` days."""
    cutoff = (now_tz() - timedelta(days=days)).replace(tzinfo=None)

    old_logs = (
        db.query(AttendanceLog)
        .filter(
            AttendanceLog.video_path.isnot(None),
            AttendanceLog.video_path != "",
            AttendanceLog.server_timestamp < cutoff,
        )
        .limit(500)  # دفعات حتى ما يعمل ضغط
        .all()
    )

    deleted = 0
    for log in old_logs:
        try:
            vp = (log.video_path or "").lstrip("/")
            # يتعامل مع paths مثل "media/videos/..." أو "videos/..."
            if vp.startswith("media/"):
                rel = vp.replace("media/", "", 1)
                fpath = (MEDIA_DIR / rel).resolve()
            else:
                fpath = (BASE_DIR / vp).resolve()

            if fpath.exists() and fpath.is_file():
                fpath.unlink(missing_ok=True)
        except Exception:
            pass

        # أهم شيء: ما نخلي HR يشوفه بعد الأسبوع
        log.video_path = None
        deleted += 1

    if deleted:
        db.commit()
    return deleted
def reverse_geocode_nominatim(lat: float, lng: float) -> tuple[str | None, str | None]:
    """Return (area_name, region_name) using OpenStreetMap Nominatim reverse API.
    Best-effort; returns (None, None) on failure. Stores short strings.
    """
    try:
        params = urllib.parse.urlencode({
            "format": "jsonv2",
            "lat": f"{float(lat):.7f}",
            "lon": f"{float(lng):.7f}",
            "zoom": "18",
            "addressdetails": "1",
        })
        url = "https://nominatim.openstreetmap.org/reverse?" + params
        req = urllib.request.Request(url, headers={"User-Agent": "attendance_app/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        addr = data.get("address") or {}
        area = (
            addr.get("neighbourhood")
            or addr.get("suburb")
            or addr.get("quarter")
            or addr.get("hamlet")
            or addr.get("village")
            or addr.get("town")
            or addr.get("city_district")
        )
        region = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("state")
            or addr.get("county")
        )
        if area:
            area = str(area)[:100]
        if region:
            region = str(region)[:100]
        return area, region
    except Exception:
        return None, None


def ensure_schema():
    """Best-effort lightweight migrations for existing SQLite/MySQL DBs."""
    try:
        with engine.begin() as conn:
            def _cols(table_name: str) -> set[str]:
                try:
                    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
                    return {str(r[1]) for r in rows}
                except Exception:
                    return set()

            ds_cols = _cols("daily_settings")
            if ds_cols and "official_work_minutes" not in ds_cols:
                conn.execute(text("ALTER TABLE daily_settings ADD COLUMN official_work_minutes INTEGER NOT NULL DEFAULT 480"))

            adj_cols = _cols("attendance_adjustments")
            if adj_cols:
                if "decision_overtime" not in adj_cols:
                    conn.execute(text("ALTER TABLE attendance_adjustments ADD COLUMN decision_overtime VARCHAR(20) NOT NULL DEFAULT 'PENDING'"))
                if "excuse_overtime" not in adj_cols:
                    conn.execute(text("ALTER TABLE attendance_adjustments ADD COLUMN excuse_overtime BOOLEAN NOT NULL DEFAULT 0"))
                if "manual_late_minutes" not in adj_cols:
                    conn.execute(text("ALTER TABLE attendance_adjustments ADD COLUMN manual_late_minutes INTEGER NULL"))
                if "manual_early_leave_minutes" not in adj_cols:
                    conn.execute(text("ALTER TABLE attendance_adjustments ADD COLUMN manual_early_leave_minutes INTEGER NULL"))
                if "manual_overtime_minutes" not in adj_cols:
                    conn.execute(text("ALTER TABLE attendance_adjustments ADD COLUMN manual_overtime_minutes INTEGER NULL"))
                if "manual_absence_status" not in adj_cols:
                    conn.execute(text("ALTER TABLE attendance_adjustments ADD COLUMN manual_absence_status VARCHAR(20) NULL"))

                
                conn.execute(text("UPDATE attendance_adjustments SET decision_late='REJECTED' WHERE decision_late='EXCUSED'"))
                conn.execute(text("UPDATE attendance_adjustments SET decision_early_leave='REJECTED' WHERE decision_early_leave='EXCUSED'"))
                conn.execute(text("UPDATE attendance_adjustments SET decision_absence='REJECTED' WHERE decision_absence='EXCUSED'"))
                conn.execute(text("UPDATE attendance_adjustments SET decision_overtime='REJECTED' WHERE decision_overtime='EXCUSED'")) 
    except Exception:
        pass
    
    
        
      
       
        
      


app = FastAPI()
@app.on_event("startup")
def startup_event():
    try:
        ensure_schema()
    except Exception:
        # ignore migration errors; app can still run with SQLAlchemy create_all
        pass

templates = Jinja2Templates(directory="templates")

# Static media (videos/photos)
BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR =  BASE_DIR / "media"
VIDEOS_DIR = MEDIA_DIR / "videos"
PHOTOS_DIR = MEDIA_DIR / "photos"
VIDEOS_DIR = MEDIA_DIR / "videos"
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

# Backward-compatible static mounts.
# Some older templates/DB values referenced "/photos/<file>" and "/videos/<file>" directly.
# Keep them working by mapping those routes to the same media subfolders.
app.mount("/photos", StaticFiles(directory=str(PHOTOS_DIR)), name="photos")
app.mount("/videos", StaticFiles(directory=str(VIDEOS_DIR)), name="videos")

EMP_COOKIE = "emp_token"
HR_COOKIE = "hr_token"
ADMIN_COOKIE = "admin_token"


def tz() -> ZoneInfo:
    return ZoneInfo(TIMEZONE_NAME)


def now_tz() -> datetime:
    return datetime.now(tz())


def today_tz() -> date:
    return now_tz().date()



def _as_naive(dt: datetime | None) -> datetime | None:
    # خليه فقط يشيل tzinfo بدون أي تحويل ساعات
    if dt is None:
        return None
    return dt.replace(tzinfo=None)

def _ceil_minutes(delta_seconds: int) -> int:
    if delta_seconds <= 0:
        return 0
    return int(math.ceil(delta_seconds / 60.0))


def compute_early_leave_segments(
    sessions: list[dict],
    d: date,
    work_end: time | None,
    early_leave_grace: int,
):
    """Return list of early-leave segments for the day.

    - Break segment: OUT -> next IN (clamped to scheduled end)
    - Final segment: last OUT -> scheduled end (with grace)
    """
    segs = []
    if not work_end:
        return segs

    end_dt = datetime.combine(d, work_end)
    end_ts = _as_naive(end_dt)
    if not end_ts:
        return segs

    # Breaks inside the day (OUT -> next IN), clamped to sched end.
    try:
        for i in range(len(sessions) - 1):
            out_log = sessions[i].get("out")
            next_in = sessions[i + 1].get("in")
            if not out_log or not next_in:
                continue
            out_ts = _as_naive(out_log.server_timestamp)
            in_ts = _as_naive(next_in.server_timestamp)
            if not out_ts or not in_ts or in_ts <= out_ts:
                continue
            if out_ts >= end_ts:
                continue
            effective_end = min(in_ts, end_ts)
            if effective_end <= out_ts:
                continue
            mins = _ceil_minutes(int((effective_end - out_ts).total_seconds()))
            if mins > 0:
                segs.append(
                    {
                        "out_ts": out_ts,
                        "in_ts": in_ts,
                        "end_ts": effective_end,
                        "minutes": mins,
                        "type": "BREAK",
                    }
                )
    except Exception:
        pass
    
      # Final early leave (last OUT before end, with grace).
    try:
      if sessions:
         last_out_log = sessions[-1].get("out")
         if last_out_log:
             last_out_ts = _as_naive(last_out_log.server_timestamp)
             if last_out_ts and last_out_ts < end_ts:
                # ✅ apply grace (do not count within grace window)
                effective_end = end_ts - timedelta(minutes=int(early_leave_grace or 0))
                effective_end = _as_naive(effective_end)
                if effective_end and last_out_ts < effective_end:
                    mins = _ceil_minutes(int((effective_end - last_out_ts).total_seconds()))
                    if mins > 0:
                        segs.append(
                            {
                                "out_ts": last_out_ts,
                                "in_ts": None,
                                "end_ts": effective_end,
                                "minutes": mins,
                                "type": "FINAL",
                            }
                        )
    except Exception:
       pass
    return segs


def sync_early_leave_segments(db: Session, emp_id: int, d: date, segs: list[dict]):
    """Upsert early leave segments for the day (idempotent).

    Important behavior:
    - If an employee clocks OUT and later clocks back IN, we must NOT keep the provisional
      OUT->scheduled_end segment. Instead we replace it with the real OUT->IN segment.
    - Therefore, we delete any existing *PENDING* segments for that day that are not present in `segs`.
    """
    # If no segments are currently computed, remove obsolete pending ones (if any).
    if not segs:
        existing_pending = (
            db.query(AttendanceEarlyLeaveSegment)
            .filter(
                AttendanceEarlyLeaveSegment.employee_id == emp_id,
                AttendanceEarlyLeaveSegment.day_date == d,
                AttendanceEarlyLeaveSegment.decision == "PENDING",
            )
            .all()
        )
        if existing_pending:
            for e in existing_pending:
                db.delete(e)
            db.commit()
        return []

    existing = (
        db.query(AttendanceEarlyLeaveSegment)
        .filter(AttendanceEarlyLeaveSegment.employee_id == emp_id, AttendanceEarlyLeaveSegment.day_date == d)
        .all()
    )
    by_key = {}
    for e in existing:
        key = (e.out_ts.replace(microsecond=0), e.end_ts.replace(microsecond=0))
        by_key[key] = e

    new_keys = set()
    out = []
    changed = False
    for s in segs:
        out_ts = s["out_ts"].replace(microsecond=0)
        end_ts = s["end_ts"].replace(microsecond=0)
        key = (out_ts, end_ts)
        new_keys.add(key)
        rec = by_key.get(key)
        if not rec:
            rec = AttendanceEarlyLeaveSegment(
                employee_id=emp_id,
                day_date=d,
                out_ts=out_ts,
                in_ts=(s["in_ts"].replace(microsecond=0) if s.get("in_ts") else None),
                end_ts=end_ts,
                minutes=int(s.get("minutes") or 0),
            )
            db.add(rec)
            changed = True
        else:
            # keep decision/note, only refresh minutes/in_ts if needed
            new_minutes = int(s.get("minutes") or 0)
            new_in = s.get("in_ts")
            new_in = new_in.replace(microsecond=0) if new_in else None
            if rec.minutes != new_minutes or rec.in_ts != new_in:
                rec.minutes = new_minutes
                rec.in_ts = new_in
                changed = True
        out.append(rec)

    # Delete obsolete pending segments (e.g., provisional OUT->end) that are no longer valid.
    for e in existing:
        key = (e.out_ts.replace(microsecond=0), e.end_ts.replace(microsecond=0))
        if key not in new_keys and (e.decision or "PENDING") == "PENDING":
            db.delete(e)
            changed = True

    if changed:
        db.commit()
        for r in out:
            try:
                db.refresh(r)
            except Exception:
                pass
    return out


def day_bounds(d: date) -> tuple[datetime, datetime]:
    # MySQL stores naive datetimes by default; keep bounds naive to avoid naive/aware comparisons
    start = datetime(d.year, d.month, d.day, 0, 0, 0)
    end = start + timedelta(days=1)
    return start, end


# -------------------------
# Auth helpers
# -------------------------

def get_current_employee(request: Request, db: Session) -> Employee:
    token = request.cookies.get(EMP_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")

    payload = verify_token(token)
    if not payload or "employee_id" not in payload:
        raise HTTPException(status_code=401, detail="Invalid session")

    emp = db.get(Employee, int(payload["employee_id"]))
    if not emp or not emp.is_active:
        raise HTTPException(status_code=401, detail="Employee not active")
    return emp


def get_current_hr_user(request: Request, db: Session) -> User:
    token = request.cookies.get(HR_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")

    payload = verify_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Invalid session")

    u = db.get(User, int(payload["user_id"]))
    if not u or not u.is_active:
        raise HTTPException(status_code=401, detail="User not active")
    if u.role not in ("HR", "ADMIN"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return u

def get_current_admin_user(request: Request, db: Session) -> User:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")

    payload = verify_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Invalid session")

    u = db.get(User, int(payload["user_id"]))
    if not u or not u.is_active:
        raise HTTPException(status_code=401, detail="User not active")
    if u.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Forbidden")
    return u

def get_current_manager_user(request: Request, db: Session) -> User:
    """Manager portal auth. Uses the same HR cookie, but restricts role."""
    token = request.cookies.get(HR_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")

    payload = verify_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Invalid session")

    u = db.get(User, int(payload["user_id"]))
    if not u or not u.is_active:
        raise HTTPException(status_code=401, detail="User not active")
    if u.role not in ("MANAGER", "ADMIN"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return u





# -------------------------
# Daily settings enforcement
# -------------------------

def get_or_none_daily_settings(db: Session, d: date) -> DailySettings | None:
    return db.get(DailySettings, d)


def enforce_daily_window(db: Session, when: datetime) -> DailySettings:
    settings = get_or_none_daily_settings(db, when.date())
    if not settings:
        raise HTTPException(status_code=400, detail="الدوام غير مفعل اليوم. راجع HR/المدير.")
    if settings.is_holiday:
        raise HTTPException(status_code=400, detail="اليوم عطلة. لا يمكن التسجيل.")
    return settings


# -------------------------
# Employee portal
# -------------------------

@app.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(
    request: Request,
    employee_code: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).filter(Employee.employee_code == employee_code).first()
    if not emp or not emp.is_active:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "بيانات الدخول غلط."},
            status_code=400,
        )

    if not verify_pin(pin, emp.pin_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "بيانات الدخول غلط."},
            status_code=400,
        )

    token = create_token({"employee_id": emp.id})
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie(
        EMP_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=False,  # set True when you move to HTTPS
        max_age=60 * 60 * 24 * 7,
    )
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(EMP_COOKIE)
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("dashboard.html", {"request": request, "employee": emp})


@app.get("/clock", response_class=HTMLResponse)
def clock_page(request: Request, db: Session = Depends(get_db)):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    # show today's settings status (optional)
    settings = get_or_none_daily_settings(db, today_tz())
    return templates.TemplateResponse(
        "clock.html",
        {
            "request": request,
            "employee": emp,
            "today_settings": settings,
        },
    )

@app.post("/api/work-doc")
async def work_doc_api(
    request: Request,
    lat: float = Form(...),
    lng: float = Form(...),
    accuracy_m: float = Form(...),
    request_id: str | None = Form(None),
    video: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    ):
    cleanup_old_videos(db, days=7)  # إذا بدك نفس سياسة الحذف بعد 7 أيام

    emp = get_current_employee(request, db)

    # اختياري: تقيدها بساعات الدوام
    enforce_daily_window(db, now_tz())

    # idempotent لو نفس request_id
    if request_id:
        ex = (
            db.query(WorkDocumentation)
            .filter(WorkDocumentation.employee_id == emp.id, WorkDocumentation.client_request_id == request_id)
            .order_by(WorkDocumentation.id.desc())
            .first()
        )
        if ex:
            return {"ok": True, "media_path": ex.video_path, "ts": str(ex.server_timestamp), "note": "idempotent"}

    if not video or not video.filename:
        raise HTTPException(status_code=400, detail="الفيديو مطلوب لتوثيق العمل.")

    ext = Path(video.filename).suffix.lower()
    if ext not in (".webm", ".mp4"):
        ext = ".webm"

    fname = f"{emp.employee_code}_WORK_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    out_path = VIDEOS_DIR / fname
    content = await video.read()
    if len(content) > 120 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="حجم الفيديو كبير جداً (الحد 120MB).")
    out_path.write_bytes(content)
    media_rel_path = str(out_path.relative_to(MEDIA_DIR)).replace("\\", "/")

    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None

    row = WorkDocumentation(
        employee_id=emp.id,
        day_date=today_tz(),
        server_timestamp=now_tz().replace(tzinfo=None),
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
        video_path=media_rel_path,
        user_agent=ua[:255] if ua else None,
        ip=ip,
        client_request_id=request_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return {"ok": True, "media_path": media_rel_path, "ts": str(row.server_timestamp)}
@app.post("/api/clock")
async def clock_api(
    request: Request,
    action: str = Form(...),  # IN / OUT
    lat: float = Form(...),
    lng: float = Form(...),
    accuracy_m: float = Form(...),
    request_id: str | None = Form(None),
    video: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    ):
    # keep videos only 7 days (HR verification window)
    cleanup_old_videos(db, days=7)
    emp = get_current_employee(request, db)
    action = action.upper().strip()
    if action not in ("IN", "OUT"):
        raise HTTPException(status_code=400, detail="Invalid action")

    # Enforce daily window
    enforce_daily_window(db, now_tz())

    # Prevent invalid sequences using *valid* logs only.
    last = (
        db.query(AttendanceLog)
        .filter(AttendanceLog.employee_id == emp.id, AttendanceLog.is_valid == True)
        .order_by(AttendanceLog.id.desc())
        .first()
    )

    # If the client sends a request_id, make the operation idempotent:
    # same request_id => return success without creating a duplicate row.
    if request_id:
        existing = (
            db.query(AttendanceLog)
            .filter(
                AttendanceLog.employee_id == emp.id,
                AttendanceLog.is_valid == True,
                AttendanceLog.client_request_id == request_id,
            )
            .order_by(AttendanceLog.id.desc())
            .first()
        )
        if existing:
            return {
                "ok": True,
                "media_path": existing.video_path,
                "ts": str(existing.server_timestamp),
                "map_url": (
                    f"https://www.google.com/maps?q={float(existing.lat):.7f},{float(existing.lng):.7f}"
                    if (existing.lat is not None and existing.lng is not None)
                    else None
                ),
                "note": "idempotent",
            }

    if last:
        if last.action == action:
            # Retry window: if the previous record is very recent, invalidate it and allow retry.
            # This handles cases where the server committed but the client didn't get the response.
            retry_allowed = False
            try:
                last_ts = _as_naive(last.server_timestamp)
                now_ts = _as_naive(now_tz().replace(tzinfo=None))
                if last_ts and now_ts and (now_ts - last_ts) <= timedelta(minutes=2):
                    retry_allowed = True
            except Exception:
                retry_allowed = False

            if retry_allowed:
                last.is_valid = False
                last.invalid_reason = "retry_same_action"
                db.add(last)
                db.commit()
            else:
                raise HTTPException(status_code=400, detail="لا يمكن تكرار نفس العملية. يجب عمل خروج قبل دخول جديد.")

        if action == "OUT" and last.action != "IN":
            raise HTTPException(status_code=400, detail="لا يمكن خروج بدون دخول.")
    else:
        if action == "OUT":
            raise HTTPException(status_code=400, detail="لا يمكن خروج بدون دخول.")

    # Require a 5-second camera proof VIDEO on each action (5 seconds)
    media_rel_path = None
    if video and video.filename:
        ext = Path(video.filename).suffix.lower()
        if ext not in (".webm", ".mp4"):
            # default to webm
            ext = ".webm"
        fname = f"{emp.employee_code}_{action}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
        out_path = VIDEOS_DIR / fname
        content = await video.read()
        if len(content) > 80 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="حجم الفيديو كبير جداً (الحد 80MB).")
        out_path.write_bytes(content)
        media_rel_path = str(out_path.relative_to(MEDIA_DIR)).replace("\\", "/")
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None

    log = AttendanceLog(
        employee_id=emp.id,
        action=action,
        day_date=today_tz(),  # ✅ هذا المهم
        server_timestamp=now_tz().replace(tzinfo=None),
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
        area_name=(reverse_geocode_nominatim(lat, lng)[0] if (lat is not None and lng is not None) else None),
        region_name=(reverse_geocode_nominatim(lat, lng)[1] if (lat is not None and lng is not None) else None),
        video_path=media_rel_path,
        user_agent=ua[:255] if ua else None,
        ip=ip,
        is_valid=True,
        invalid_reason=None,
        client_request_id=request_id,
    )

    db.add(log)
    db.commit()
    db.refresh(log)

    # Find today's first IN and last OUT (for map_url reference)
    d = today_tz()
    today_logs = (
        db.query(AttendanceLog)
        .filter(
           AttendanceLog.employee_id == emp.id,
           AttendanceLog.is_valid == True,
           AttendanceLog.day_date == d,
        )
        .order_by(AttendanceLog.server_timestamp.asc())
        .all()
    )
    
    first_in = next((l for l in today_logs if l.action == "IN"), None)
    last_out = next((l for l in reversed(today_logs) if l.action == "OUT"), None)

    map_url = None
    ref_loc = None
    if last_out and last_out.lat is not None and last_out.lng is not None:
        ref_loc = last_out
    elif first_in and first_in.lat is not None and first_in.lng is not None:
        ref_loc = first_in
    if ref_loc:
        try:
            map_url = f"https://www.google.com/maps?q={float(ref_loc.lat):.7f},{float(ref_loc.lng):.7f}"
        except Exception:
            map_url = None

    return {"ok": True, "media_path": media_rel_path, "ts": str(log.server_timestamp), "map_url": map_url}

@app.get("/me/change-password", response_class=HTMLResponse)
def change_password_page(request: Request, db: Session = Depends(get_db)):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("change_password.html", {"request": request, "employee": emp})

@app.post("/me/change-password")
def change_password(
    request: Request,
    old_pin: str = Form(...),
    new_pin: str = Form(...),
    new_pin_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if not verify_pin(old_pin, emp.pin_hash):
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "employee": emp, "error": "الـ PIN القديم غلط."},
            status_code=400,
        )

    if new_pin.strip() != new_pin_confirm.strip():
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "employee": emp, "error": "الـ PIN الجديد لازم ينكتب مرتين ويكون متطابق."},
            status_code=400,
        )

    emp.pin_hash = hash_pin(new_pin.strip())
    db.add(emp)
    db.commit()
    return templates.TemplateResponse(
        "change_password.html",
        {"request": request, "employee": emp, "success": "تم تغيير الـ PIN بنجاح."},
    )

@app.get("/me/attendance", response_class=HTMLResponse)
def my_attendance(
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    today = today_tz()
    first_day = date(today.year, today.month, 1)
    # compute last day
    import calendar
    last_day = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])

    rows = []
    d = first_day
    while d <= last_day:
        settings = get_or_none_daily_settings(db, d)
        row = compute_day(db, emp, d, settings)
        # employee view: hide exact location text, but show accuracy
        acc = None
        if row.get("first_in") and isinstance(row.get("first_in"), datetime):
            pass
        if row.get("first_in_log"):
            acc = row["first_in_log"].accuracy_m
        rows.append({
            "date": d,
            "status": row["status"],
            "in_time": row["first_in"].strftime("%H:%M") if row["first_in"] else "-",
            "out_time": row["last_out"].strftime("%H:%M") if row["last_out"] else "-",
            "late_minutes": row["late"],
            "overtime_minutes": row["overtime"],
            "accuracy_m": acc,
        })
        d += timedelta(days=1)

    return templates.TemplateResponse(
        "attendance.html",
        {
            "request": request,
            "employee": emp,
            "month_label": f"{today.year}-{today.month:02d}",
            "rows": rows,
        },
    )


@app.get("/me/profile", response_class=HTMLResponse)
def me_profile(request: Request, db: Session = Depends(get_db)):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    notes = (
        db.query(EmployeeNote)
        .filter(EmployeeNote.employee_id == emp.id, EmployeeNote.visible_to_employee == True)
        .order_by(EmployeeNote.created_at.desc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse("me_profile.html", {"request": request, "employee": emp, "notes": notes})

@app.post("/me/profile", response_class=HTMLResponse)
async def me_profile_save(request: Request, photo: UploadFile = File(...), db: Session = Depends(get_db)):
    emp = get_current_employee(request, db)
    ext = Path(photo.filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    content = await photo.read()
    if len(content) > 5 * 1024 * 1024:
        return templates.TemplateResponse("me_profile.html", {"request": request, "employee": emp, "error": "حجم الصورة كبير (حد أقصى 5MB)."})
    fname = f"profile_{emp.employee_code}_{uuid.uuid4().hex[:10]}{ext}"
    out_path = PHOTOS_DIR / fname
    out_path.write_bytes(content)
    emp.profile_photo_path = f"photos/{fname}"
    db.add(emp)
    db.commit()
    return templates.TemplateResponse("me_profile.html", {"request": request, "employee": emp, "success": "تم حفظ الصورة."})

@app.get("/me/support", response_class=HTMLResponse)
def me_support(request: Request, db: Session = Depends(get_db)):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    tickets = (
        db.query(SupportTicket)
        .filter(SupportTicket.employee_id == emp.id)
        .order_by(SupportTicket.id.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse("me_support.html", {"request": request, "employee": emp, "tickets": tickets})

@app.post("/me/support", response_class=HTMLResponse)
def me_support_submit(
    request: Request,
    category: str = Form("ISSUE"),
    message: str = Form(...),
    db: Session = Depends(get_db),
):
    emp = get_current_employee(request, db)
    cat = category.upper().strip()
    if cat not in ("ISSUE", "SUGGESTION", "INQUIRY"):
        cat = "ISSUE"
    t = SupportTicket(employee_id=emp.id, category=cat, message=message.strip(), status="OPEN")
    db.add(t)
    db.commit()
    return RedirectResponse(url=f"/me/support/{t.id}", status_code=302)


@app.get("/me/support/{ticket_id}", response_class=HTMLResponse)
def me_support_thread(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    t = db.get(SupportTicket, ticket_id)
    if not t or t.employee_id != emp.id:
        raise HTTPException(status_code=404, detail="Not found")

    replies = (
        db.query(SupportTicketReply)
        .filter(SupportTicketReply.ticket_id == t.id)
        .order_by(SupportTicketReply.created_at.asc())
        .all()
    )
    return templates.TemplateResponse(
        "me_support_thread.html",
        {"request": request, "employee": emp, "ticket": t, "replies": replies},
    )


@app.post("/me/support/{ticket_id}/reply", response_class=HTMLResponse)
def me_support_reply(ticket_id: int, request: Request, body: str = Form(...), db: Session = Depends(get_db)):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    t = db.get(SupportTicket, ticket_id)
    if not t or t.employee_id != emp.id:
        raise HTTPException(status_code=404, detail="Not found")

    if t.status == "CLOSED":
        return RedirectResponse(url=f"/me/support/{t.id}", status_code=302)

    body_clean = (body or "").strip()
    if body_clean:
        r = SupportTicketReply(ticket_id=t.id, sender="EMP", body=body_clean)
        db.add(r)
        db.commit()
    return RedirectResponse(url=f"/me/support/{t.id}", status_code=302)

@app.get("/me/messages", response_class=HTMLResponse)
def me_messages(request: Request, db: Session = Depends(get_db)):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    # mark HR->EMP messages as read when viewing inbox
    msgs = (
        db.query(Message)
        .filter(Message.employee_id == emp.id)
        .order_by(Message.created_at.desc())
        .all()
    )
    for m in msgs:
        if m.direction == "HR_TO_EMP" and not m.is_read:
            m.is_read = True
    db.commit()

    return templates.TemplateResponse(
        "me_messages.html",
        {"request": request, "employee": emp, "messages": msgs},
    )


@app.post("/me/messages", response_class=HTMLResponse)
def me_messages_send(
    request: Request,
    body: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    body_clean = (body or "").strip()
    if body_clean:
        msg = Message(employee_id=emp.id, direction="EMP_TO_HR", body=body_clean, is_read=False)
        db.add(msg)
        db.commit()

    return RedirectResponse(url="/me/messages", status_code=302)


def _hr_nav_counts(db: Session) -> dict:
    unread_msgs = db.query(Message).filter(Message.direction == "EMP_TO_HR", Message.is_read == False).count()
    open_tickets = db.query(SupportTicket).filter(SupportTicket.status.in_(["OPEN", "IN_PROGRESS"])).count()

    pending_adj = db.query(AttendanceAdjustment).filter((AttendanceAdjustment.decision_late == "PENDING") | (AttendanceAdjustment.decision_early_leave == "PENDING") | (AttendanceAdjustment.decision_absence == "PENDING")).count()

    pending_early = db.query(AttendanceEarlyLeaveSegment).filter(AttendanceEarlyLeaveSegment.decision == "PENDING").count()

    return {"unread_msgs": unread_msgs, "open_tickets": open_tickets, "pending_adj": (pending_adj + pending_early)}


@app.get("/hr/messages", response_class=HTMLResponse)
def hr_messages(request: Request, db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    # list employees with last message + unread flag
    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.full_name.asc()).all()
    rows = []
    for e in employees:
        last = (
            db.query(Message)
            .filter(Message.employee_id == e.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        unread = (
            db.query(Message)
            .filter(Message.employee_id == e.id, Message.direction == "EMP_TO_HR", Message.is_read == False)
            .count()
        )
        if last or unread:
            rows.append({"emp": e, "last": last, "unread": unread})
    rows.sort(key=lambda r: (0 if r["unread"] else 1, (r["last"].created_at if r["last"] else datetime.datetime.min)), reverse=False)

    counts = _hr_nav_counts(db)
    return templates.TemplateResponse(
        "hr_messages.html",
        {"request": request, "user": u, "rows": rows, "nav": counts},
    )


@app.post("/hr/messages/broadcast", response_class=HTMLResponse)
def hr_messages_broadcast(request: Request, body: str = Form(...), db: Session = Depends(get_db)):
    """إرسال رسالة لكل الموظفين (HR_TO_EMP)."""
    try:
        _u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    body_clean = (body or "").strip()
    if not body_clean:
        return RedirectResponse(url="/hr/messages?err=empty", status_code=302)

    employees = db.query(Employee).filter(Employee.is_active == True).all()
    for e in employees:
        db.add(Message(employee_id=e.id, direction="HR_TO_EMP", body=body_clean, is_read=False))
    db.commit()
    return RedirectResponse(url="/hr/messages?ok=broadcast", status_code=302)


@app.get("/hr/messages/{emp_id}", response_class=HTMLResponse)
def hr_messages_thread(emp_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    msgs = db.query(Message).filter(Message.employee_id == emp.id).order_by(Message.created_at.asc()).all()
    for m in msgs:
        if m.direction == "EMP_TO_HR" and not m.is_read:
            m.is_read = True
    db.commit()

    counts = _hr_nav_counts(db)
    return templates.TemplateResponse(
        "hr_messages_thread.html",
        {"request": request, "user": u, "emp": emp, "messages": msgs, "nav": counts},
    )


@app.post("/hr/messages/{emp_id}", response_class=HTMLResponse)
def hr_messages_send(emp_id: int, request: Request, body: str = Form(...), db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    body_clean = (body or "").strip()
    if body_clean:
        msg = Message(employee_id=emp.id, direction="HR_TO_EMP", body=body_clean, is_read=False)
        db.add(msg)
        db.commit()

    return RedirectResponse(url=f"/hr/messages/{emp.id}", status_code=302)



@app.get("/me/payroll", response_class=HTMLResponse)
def me_payroll(request: Request, db: Session = Depends(get_db), month: str | None = None):
    try:
        emp = get_current_employee(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if month:
        y, m = month.split("-")
        year, mon = int(y), int(m)
    else:
        t = today_tz()
        year, mon = t.year, t.month
        month = f"{year:04d}-{mon:02d}"

    settings = db.get(DailySettings, today_tz())
    upto = today_tz() if (year == today_tz().year and mon == today_tz().month) else None
    summary, breakdown = compute_month(db, emp, year, mon, settings, upto=upto)


    # build daily rows for UI (month-to-date only)
    day_rows = []
    for b in breakdown:
        items = b.get("items", [])
        explain_parts = [it.get("note","") for it in items if it.get("note")]
        day_rows.append(
            {
                "date": b.get("date"),
                "status": b.get("status"),
                "late_minutes": int(b.get("late_minutes", 0)),
                "overtime_minutes": int(b.get("overtime_minutes", 0)),
                "day_adjust": float(b.get("day_adjust", 0.0)),
                "explain": " | ".join(explain_parts)[:900],
            }
        )

    calc = {
        "salary_monthly": float(summary.get("salary_monthly", float(emp.salary_monthly or 0.0))),
        "base_daily": float(summary.get("base_daily", 0.0)),
        "days_absent": int(summary.get("days_absent", 0)),
        "days_present": int(summary.get("days_present", 0)),
        "total_late_minutes": int(summary.get("late_minutes", 0)),
        "total_early_leave_minutes": int(summary.get("early_leave_minutes", 0)),
        "total_overtime_minutes": int(summary.get("overtime_minutes", 0)),
        "absent_deduction": float(summary.get("absent_deduction", 0.0)),
        "late_deduction": float(summary.get("late_deduction", 0.0)),
        "early_leave_deduction": float(summary.get("early_leave_deduction", 0.0)),
        "manual_adjustments_total": float(summary.get("manual_adjustments_total", 0.0)),
        "manual_additions": float(summary.get("manual_additions", 0.0)),
        "manual_deductions": float(summary.get("manual_deductions", 0.0)),
        "total_deductions": float(summary.get("total_deductions", 0.0)),
        "total_additions": float(summary.get("total_additions", 0.0)),
        "adjustments_total": float(summary.get("adjustments_total", 0.0)),
        "total_pay": float(summary.get("total", 0.0)),
        "late_explain": "مجموع التأخير بالدقائق، والخصم يظهر فقط للأيام التي وافق عليها HR.",
        "absent_explain": "الغياب الموافق عليه يُخصم يوم كامل: (الراتب الشهري/30).",
        "early_leave_explain": "المغادرة/نقص الدوام بالدقائق تُخصم مثل التأخير عند الموافقة.",
        "bonus_explain": "الزيادات/الخصومات هنا يدوياً من الإدارة فقط (+/-).",
        "breakdown": day_rows,
    }

    return templates.TemplateResponse("me_payroll.html", {"request": request, "employee": emp, "month": month, "calc": calc})




@app.get("/hr/create-manager", response_class=HTMLResponse)
def hr_create_manager_page(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)
    return templates.TemplateResponse("hr_create_manager.html", {"request": request})


@app.post("/hr/create-manager")
def hr_create_manager(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    username = username.strip()
    if not username:
        return templates.TemplateResponse(
            "hr_create_manager.html",
            {"request": request, "error": "اسم المستخدم مطلوب."},
            status_code=400,
        )

    exists = db.query(User).filter(User.username == username).first()
    if exists:
        return templates.TemplateResponse(
            "hr_create_manager.html",
            {"request": request, "error": "اسم المستخدم موجود مسبقاً."},
            status_code=400,
        )

    u = User(
        username=username,
        password_hash=hash_pin(password.strip()),
        pin_hash=hash_pin(pin.strip()),
        role="MANAGER",
        is_active=True,
    )
    db.add(u)
    db.commit()

    return templates.TemplateResponse(
        "hr_create_manager.html",
        {"request": request, "success": f"تمت إضافة مدير ({username}) بنجاح."},
    )


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@app.post("/admin/login")
def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.username == username).first()
    if not u or not u.is_active or u.role != "ADMIN":
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "بيانات الدخول غلط."},
            status_code=400,
        )
    if not verify_pin(password, u.password_hash) or not verify_pin(pin, u.pin_hash):
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "بيانات الدخول غلط."},
            status_code=400,
        )

    token = create_token({"user_id": u.id})
    resp = RedirectResponse(url="/admin/dashboard", status_code=302)
    resp.set_cookie(
        ADMIN_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 7,
    )
    return resp

@app.get("/admin/logout")
def admin_logout():
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie(ADMIN_COOKIE)
    return resp

@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        _admin = get_current_admin_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/admin/login", status_code=302)
    # reuse HR dashboard view
    return RedirectResponse(url="/hr/dashboard", status_code=302)

# Admin helpers (temporary)
# -------------------------

@app.get("/admin/create-employee", response_class=HTMLResponse)
def admin_create_employee_page(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_admin_user(request, db)
    except HTTPException:
        return RedirectResponse(url='/admin/login', status_code=302)
    return templates.TemplateResponse("admin_create_employee.html", {"request": request})


@app.post("/admin/create-employee")
def admin_create_employee(
    request: Request,
    employee_code: str = Form(...),
    full_name: str = Form(...),
    national_id: str | None = Form(None),
    phone: str | None = Form(None),
    salary_monthly: float | None = Form(None),
    allowed_ip: str | None = Form(None),
    pin: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        get_current_admin_user(request, db)
    except HTTPException:
        return RedirectResponse(url='/admin/login', status_code=302)
    exists = db.query(Employee).filter(Employee.employee_code == employee_code).first()
    if exists:
        return templates.TemplateResponse(
            "admin_create_employee.html",
            {"request": request, "error": "الكود موجود مسبقاً."},
            status_code=400,
        )

    emp = Employee(
        employee_code=employee_code.strip(),
        full_name=full_name.strip(),
        national_id=national_id.strip() if national_id else None,
        phone=phone.strip() if phone else None,
        salary_monthly=float(salary_monthly) if salary_monthly not in (None, "") else None,
        allowed_ip=allowed_ip.strip() if allowed_ip else None,
        pin_hash=hash_pin(pin.strip()),
        is_active=True,
    )
    db.add(emp)
    db.commit()

    return templates.TemplateResponse(
        "admin_create_employee.html",
        {"request": request, "success": f"تمت إضافة الموظف {full_name} بنجاح."},
    )


@app.get("/admin/create-user", response_class=HTMLResponse)
def admin_create_user_page(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_admin_user(request, db)
    except HTTPException:
        return RedirectResponse(url='/admin/login', status_code=302)
    return templates.TemplateResponse("admin_create_user.html", {"request": request})


@app.post("/admin/create-user")
def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    pin: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        get_current_admin_user(request, db)
    except HTTPException:
        return RedirectResponse(url='/admin/login', status_code=302)
    role = role.upper().strip()
    if role not in ("HR", "MANAGER", "ADMIN"):
        return templates.TemplateResponse(
            "admin_create_user.html",
            {"request": request, "error": "Role غير صحيح."},
            status_code=400,
        )

    exists = db.query(User).filter(User.username == username).first()
    if exists:
        return templates.TemplateResponse(
            "admin_create_user.html",
            {"request": request, "error": "اسم المستخدم موجود مسبقاً."},
            status_code=400,
        )

    u = User(username=username.strip(), password_hash=hash_pin(password.strip()), pin_hash=hash_pin(pin.strip()), role=role, is_active=True)
    db.add(u)
    db.commit()

    return templates.TemplateResponse(
        "admin_create_user.html",
        {"request": request, "success": f"تم إنشاء المستخدم {username} بنجاح."},
    )


# -------------------------
# HR / Manager portal
# -------------------------

@app.get("/hr/login", response_class=HTMLResponse)
def hr_login_page(request: Request):
    return templates.TemplateResponse("hr_login.html", {"request": request})


@app.post("/hr/login")
def hr_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.username == username).first()
    if not u or not u.is_active:
        return templates.TemplateResponse(
            "hr_login.html",
            {"request": request, "error": "بيانات الدخول غلط."},
            status_code=400,
        )

    if not verify_pin(password, u.password_hash) or not verify_pin(pin, u.pin_hash):
        return templates.TemplateResponse(
            "hr_login.html",
            {"request": request, "error": "بيانات الدخول غلط."},
            status_code=400,
        )

    token = create_token({"user_id": u.id})
    redirect_url = "/manager" if u.role in ("MANAGER",) else "/hr/dashboard"
    resp = RedirectResponse(url=redirect_url, status_code=302)
    resp.set_cookie(
        HR_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 7,
    )
    return resp


@app.get("/hr/logout")
def hr_logout():
    resp = RedirectResponse(url="/hr/login", status_code=302)
    resp.delete_cookie(HR_COOKIE)
    return resp


def compute_today_sheet(db: Session, d: date, settings: DailySettings) -> tuple[list[dict], dict]:
    start_dt, end_dt = day_bounds(d)

    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.full_name.asc()).all()  # noqa

    rows: list[dict] = []
    counts = {
        "present": 0,
        "late": 0,
        "absent": 0,
        "incomplete": 0,
        "total": len(employees),
        "holiday": 0,
    }

    if settings.is_holiday:
        # everyone is holiday
        for emp in employees:
            logs = (
              db.query(AttendanceLog)
              .filter(
                 AttendanceLog.employee_id == emp.id,
                 AttendanceLog.is_valid == True,
                 AttendanceLog.day_date == d,
              )
              .order_by(AttendanceLog.server_timestamp.asc())
              .all()
              )
        counts["holiday"] = len(employees)
        return rows, counts

    grace = timedelta(minutes=int(settings.grace_minutes or 0))
    start_time_dt = datetime.combine(d, settings.work_start)
    late_after = start_time_dt + grace

    for emp in employees:
        logs = (
           db.query(AttendanceLog)
           .filter(
              AttendanceLog.employee_id == emp.id,
              AttendanceLog.is_valid == True,
              AttendanceLog.day_date == d,
           )
           .order_by(AttendanceLog.server_timestamp.asc())
           .all()
        )
        
        first_in = next((x for x in logs if x.action == "IN"), None)
        last_out = next((x for x in reversed(logs) if x.action == "OUT"), None)

        if not first_in:
            status = "ABSENT"
            late_minutes = 0
            counts["absent"] += 1
        else:
            late_minutes = 0
            fi = _as_naive(first_in.server_timestamp)
            la = _as_naive(late_after)
            if fi and la and fi > la:
                late_minutes = int((fi - la).total_seconds() // 60)

            if not last_out:
                status = "INCOMPLETE"
                counts["incomplete"] += 1
            else:
                if late_minutes > 0:
                    status = "LATE"
                    counts["late"] += 1
                else:
                    status = "PRESENT"
                    counts["present"] += 1

        rows.append(
            {
                "employee_code": emp.employee_code,
                "full_name": emp.full_name,
                "first_in": _as_naive(first_in.server_timestamp) if first_in else None,
                "first_in_log": first_in,
                "last_out": _as_naive(last_out.server_timestamp) if last_out else None,
                "last_out_log": last_out,
                "status": status,
                "sched_start": row.get("sched_start"),
                "sched_end": row.get("sched_end"),
                "late_minutes": late_minutes,
                "sched_start": ss.isoformat() if ss else None,
                "sched_end": se.isoformat() if se else None,
            }
        )

    return rows, counts


@app.get("/hr/dashboard", response_class=HTMLResponse)
def hr_dashboard(request: Request, db: Session = Depends(get_db), view: str | None = None):
    # Cookie-based auth (no Starlette sessions)
    u = get_current_hr_user(request, db)

    d = today_tz()
    settings = db.get(DailySettings, d)

    employees = (
        db.query(Employee)
        .filter(Employee.is_active == True)
        .order_by(Employee.employee_code.asc())
        .all()
    )

    # Build today sheet rows + buckets (present/late/absent)
    rows = []
    present_list: list[dict] = []
    late_list: list[dict] = []
    early_leave_list: list[dict] = []
    absent_list: list[dict] = []

    for e in employees:
        r = compute_day(db, e, d, settings)

        fi = r["first_in"]
        lo = r["last_out"]

        first_in_str = fi.strftime("%H:%M") if fi else None
        last_out_str = lo.strftime("%H:%M") if lo else None

        # pick a video for today (prefer IN then OUT)
        video_path = None
        if r.get("first_in_log") and getattr(r["first_in_log"], "video_path", None):
            video_path = r["first_in_log"].video_path
        elif r.get("last_out_log") and getattr(r["last_out_log"], "video_path", None):
            video_path = r["last_out_log"].video_path

        # duration (OUT - IN)
        work_minutes = r.get("work_minutes")
        work_duration_str = None
        if isinstance(work_minutes, int) and work_minutes >= 0:
            h = work_minutes // 60
            m = work_minutes % 60
            work_duration_str = f"{h:02d}:{m:02d}"

        # IMPORTANT: HR/Admin dashboard is a *review* screen.
        # Show RAW values (what happened) even if not yet approved, otherwise counts look wrong.
        raw_late = int(r.get("raw_late") or 0)
        raw_early = int(r.get("raw_early_leave") or 0)
        item = {
            "emp_id": e.id,
            "employee_code": e.employee_code,
            "full_name": e.full_name,
            "photo": e.profile_photo_path,
            "first_in": first_in_str,
            "last_out": last_out_str,
            "work_duration": work_duration_str,
            # raw values for UI + counts
            "late_minutes": raw_late,
            "early_leave_minutes": raw_early,
            # decisions (None / APPROVED / REJECTED)
            "late_decision": r.get("decision_late"),
            "early_leave_decision": r.get("decision_early_leave"),
            "absence_decision": r.get("decision_absence"),
            "map_url": r.get("map_url"),
            "area": r.get("area"),
            "region": r.get("region"),
            "video_path": video_path,
        }

        rows.append(item)

        # buckets
        st = r.get("status")
        raw_status = r.get("raw_status")

        # present-like
        if st in ("PRESENT", "INCOMPLETE"):
            present_list.append(item)
            if raw_late > 0:
                late_list.append(item)
            if raw_early > 0:
                early_leave_list.append(item)
        # absent-like
        elif st in ("ABSENT", "ABSENT_PENDING", "EXCUSED") or raw_status == "ABSENT":
            item2 = dict(item)
            if st == "EXCUSED":
                item2["excused"] = True
            if st == "ABSENT_PENDING":
                item2["pending"] = True
            absent_list.append(item2)

    from types import SimpleNamespace
    summary = SimpleNamespace(
        present=len(present_list),
        late=len(late_list),
        early_leave=len(early_leave_list),
        absent=len(absent_list),
    )

    view = (view or "").lower().strip()
    if view not in ("present", "late", "early", "absent", "all", ""):
        view = "all"
    if view in ("",):
        view = "all"

    return templates.TemplateResponse(
        "hr_dashboard.html",
        {
            "request": request,
            "user": u,
            "today": d,
            "now_time": now_tz().strftime("%H:%M"),
            "summary": summary,
            "rows": rows,

            "present_list": present_list,
            "late_list": late_list,
            "early_leave_list": early_leave_list,
            "absent_list": absent_list,
            "view": view,
            "settings": settings,
            "err": request.query_params.get("err"),
        },
    )



# -------------------------
# Manager Portal (Read-only)
# -------------------------

def _parse_month_or_default(month: str | None) -> tuple[int, int, str]:
    t = today_tz()
    if month:
        try:
            y, m = month.split("-")
            year, mon = int(y), int(m)
            return year, mon, f"{year:04d}-{mon:02d}"
        except Exception:
            pass
    return t.year, t.month, f"{t.year:04d}-{t.month:02d}"


def _month_range(year: int, mon: int) -> tuple[date, date]:
    first = date(year, mon, 1)
    if mon == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, mon + 1, 1)
    return first, next_first


def _safe_pct(num: float, den: float) -> int:
    if den <= 0:
        return 0
    return int(round((num / den) * 100))



@app.get("/manager/login", response_class=HTMLResponse)
def manager_login_page(request: Request):
    return templates.TemplateResponse("manager_login.html", {"request": request})


@app.post("/manager/login")
def manager_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    pin: str = Form(...),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.username == username).first()
    if not u or not u.is_active:
        return templates.TemplateResponse(
            "manager_login.html",
            {"request": request, "error": "بيانات الدخول غلط."},
            status_code=400,
        )

    if not verify_pin(password, u.password_hash) or not verify_pin(pin, u.pin_hash):
        return templates.TemplateResponse(
            "manager_login.html",
            {"request": request, "error": "بيانات الدخول غلط."},
            status_code=400,
        )

    if u.role not in ("MANAGER", "ADMIN"):
        return templates.TemplateResponse(
            "manager_login.html",
            {"request": request, "error": "ممنوع الدخول من هنا."},
            status_code=403,
        )

    token = create_token({"user_id": u.id})
    resp = RedirectResponse(url="/manager", status_code=302)
    resp.set_cookie(
        HR_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 7,
    )
    return resp


@app.get("/manager", response_class=HTMLResponse)
@app.get("/manager/dashboard", response_class=HTMLResponse)
def manager_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = None,
    late_limit: int | None = None,
    ot_budget: float | None = None,
):
    # Manager cookie auth (same HR cookie)
    try:
        u = get_current_manager_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    year, mon, month_key = _parse_month_or_default(month)
    month_label = f"{year:04d}-{mon:02d}"
    first, next_first = _month_range(year, mon)
    t_today = today_tz()
    upto = t_today if (year == t_today.year and mon == t_today.month) else (next_first - timedelta(days=1))

    late_limit = int(late_limit) if (late_limit is not None and str(late_limit).strip().isdigit()) else 120
    try:
        ot_budget = float(ot_budget) if ot_budget is not None else 0.0
    except Exception:
        ot_budget = 0.0

    employees = (
        db.query(Employee)
        .filter(Employee.is_active == True)
        .order_by(Employee.employee_code.asc())
        .all()
    )

    # Today buckets (present/late/early/absent)
    d = today_tz()
    settings_today = db.get(DailySettings, d)

    present = late_cnt = early_cnt = absent = 0
    for e in employees:
        r = compute_day(db, e, d, settings_today)
        st = r.get("status")
        raw_late = int(r.get("raw_late") or 0)
        raw_early = int(r.get("raw_early_leave") or 0)

        if st in ("PRESENT", "INCOMPLETE"):
            present += 1
            if raw_late > 0:
                late_cnt += 1
            if raw_early > 0:
                early_cnt += 1
        elif st in ("ABSENT", "ABSENT_PENDING", "EXCUSED") or r.get("raw_status") == "ABSENT":
            absent += 1

    # Month totals via payroll summary (prefer approved batch if exists)
    default_settings = db.get(DailySettings, today_tz())
    batch = db.query(PayrollBatch).filter(PayrollBatch.month == month_key).first()

    rec_map = {}
    if batch and batch.status in ("APPROVED", "CLOSED"):
        recs = db.query(PayrollRecord).filter(PayrollRecord.batch_id == batch.id).all()
        rec_map = {r.employee_id: r for r in recs}

    rows_month = []
    tot_present = tot_absent = tot_late_min = tot_ot_min = 0
    payroll_total = ot_amount_total = 0.0

    for e in employees:
        if e.id in rec_map:
            rec = rec_map[e.id]
            days_present = int(rec.days_present or 0)
            days_absent = int(rec.days_absent or 0)
            late_minutes = int(rec.late_minutes or 0)
            overtime_minutes = int(rec.overtime_minutes or 0)
            overtime_add = float(rec.overtime_add or 0.0)
            total = float(rec.total or 0.0)
            salary_monthly = float(rec.salary_monthly or 0.0)
            total_deductions = float(rec.total_deductions or 0.0)
        else:
            summary, _ = compute_month(db, e, year, mon, default_settings, upto=upto)
            days_present = int(summary.get("days_present") or 0)
            days_absent = int(summary.get("days_absent") or 0)
            late_minutes = int(summary.get("late_minutes") or 0)
            overtime_minutes = int(summary.get("overtime_minutes") or 0)
            overtime_add = float(summary.get("overtime_add") or 0.0)
            total = float(summary.get("total") or 0.0)
            salary_monthly = float(summary.get("salary_monthly") or float(e.salary_monthly or 0.0))
            total_deductions = float(summary.get("total_deductions") or 0.0)

        tot_present += days_present
        tot_absent += days_absent
        tot_late_min += late_minutes
        tot_ot_min += overtime_minutes
        payroll_total += total
        ot_amount_total += overtime_add

        rows_month.append({
            "emp": e,
            "absent_days": days_absent,
            "late_minutes": late_minutes,
            "overtime_minutes": overtime_minutes,
            "overtime_add": overtime_add,
            "total": total,
        })

    compliance_this = _safe_pct(tot_present, (tot_present + tot_absent))
    absence_pct_this = _safe_pct(tot_absent, (tot_present + tot_absent))
    ot_hours = round(tot_ot_min / 60.0, 2)
    late_hours = round(tot_late_min / 60.0, 2)

    # Previous month compliance for comparison
    prev_year, prev_mon = year, mon - 1
    if prev_mon == 0:
        prev_mon = 12
        prev_year -= 1
    prev_first, prev_next = _month_range(prev_year, prev_mon)
    prev_upto = (prev_next - timedelta(days=1))
    prev_key = f"{prev_year:04d}-{prev_mon:02d}"

    prev_batch = db.query(PayrollBatch).filter(PayrollBatch.month == prev_key).first()
    prev_rec_map = {}
    if prev_batch and prev_batch.status in ("APPROVED", "CLOSED"):
        recs = db.query(PayrollRecord).filter(PayrollRecord.batch_id == prev_batch.id).all()
        prev_rec_map = {r.employee_id: r for r in recs}

    prev_present = prev_absent = 0
    for e in employees:
        if e.id in prev_rec_map:
            rec = prev_rec_map[e.id]
            prev_present += int(rec.days_present or 0)
            prev_absent += int(rec.days_absent or 0)
        else:
            summary, _ = compute_month(db, e, prev_year, prev_mon, default_settings, upto=prev_upto)
            prev_present += int(summary.get("days_present") or 0)
            prev_absent += int(summary.get("days_absent") or 0)

    compliance_prev = _safe_pct(prev_present, (prev_present + prev_absent))
    compliance_delta = compliance_this - compliance_prev

    # Heatmap: attendance rate by weekday (Mon..Sun)
    weekday_names = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    wd_present = [0]*7
    wd_total = [0]*7

    cur = first
    while cur <= upto:
        s = get_or_none_daily_settings(db, cur)
        if s and (not s.is_holiday):
            wd = (cur.weekday() % 7)  # Mon=0
            wd_total[wd] += len(employees)
            # compute present count that day
            p_cnt = 0
            for e in employees:
                r = compute_day(db, e, cur, s)
                if r.get("status") in ("PRESENT", "INCOMPLETE"):
                    p_cnt += 1
            wd_present[wd] += p_cnt
        cur = cur + timedelta(days=1)

    heatmap = []
    for i in range(7):
        pct = _safe_pct(wd_present[i], wd_total[i]) if wd_total[i] else 0
        heatmap.append({"day": weekday_names[i], "pct": pct})

    # Top lists
    top_absent = sorted(rows_month, key=lambda x: x["absent_days"], reverse=True)[:5]
    top_late = sorted(rows_month, key=lambda x: x["late_minutes"], reverse=True)[:5]
    top_ot = sorted(rows_month, key=lambda x: x["overtime_add"], reverse=True)[:5]

    def _money(x: float) -> str:
        return f"{round(float(x or 0.0), 3)}"

    top_absent_ui = [{"name": r["emp"].full_name, "days": r["absent_days"]} for r in top_absent if (r["absent_days"] or 0) > 0]
    top_late_ui = [{"name": r["emp"].full_name, "minutes": r["late_minutes"]} for r in top_late if (r["late_minutes"] or 0) > 0]
    top_ot_ui = [{"name": r["emp"].full_name, "cost": _money(r["overtime_add"])} for r in top_ot if (r["overtime_add"] or 0) > 0]

    # Pending leave requests: not implemented in current DB schema -> show 0
    pending_leaves = 0

    # Estimated cost of delay (very rough): late hours * avg hourly (monthly/26/8)
    avg_salary = 0.0
    for e in employees:
        avg_salary += float(e.salary_monthly or 0.0)
    avg_salary = avg_salary / max(len(employees), 1)
    avg_hourly = (avg_salary / 26.0 / 8.0) if avg_salary else 0.0
    delay_cost = round(late_hours * avg_hourly, 3)

    # Alerts
    alerts = []

    # Late limit
    viol = [r for r in rows_month if int(r["late_minutes"] or 0) > late_limit]
    viol_sorted = sorted(viol, key=lambda x: x["late_minutes"], reverse=True)[:3]
    if viol_sorted:
        names = ", ".join([v["emp"].full_name for v in viol_sorted])
        alerts.append({
            "title": "تجاوز حد التأخير المسموح",
            "desc": f"أعلى الحالات هذا الشهر: {names} (الحد: {late_limit} دقيقة)",
            "badge": f"{len(viol)} موظف",
        })

    # OT budget (if provided >0)
    if ot_budget and ot_budget > 0 and ot_amount_total > ot_budget:
        alerts.append({
            "title": "تجاوز ميزانية الأوفر تايم",
            "desc": f"إجمالي OT لهذا الشهر = {round(ot_amount_total, 3)} وتجاوز الميزانية المحددة = {round(ot_budget, 3)}",
            "badge": "OT",
        })

    # Absence spike vs previous month
    prev_absence_pct = _safe_pct(prev_absent, (prev_present + prev_absent))
    if (absence_pct_this - prev_absence_pct) >= 30:
        alerts.append({
            "title": "ارتفاع مفاجئ في الغياب",
            "desc": f"نسبة الغياب ارتفعت {absence_pct_this - prev_absence_pct}% مقارنة بالشهر السابق.",
            "badge": "Absence",
        })

    # Warnings: count employee_notes containing 'إنذار' within month
    try:
        start_dt = datetime(first.year, first.month, first.day, 0, 0, 0)
        end_dt = datetime(next_first.year, next_first.month, next_first.day, 0, 0, 0)
        warn_counts = (
            db.query(EmployeeNote.employee_id, func.count(EmployeeNote.id))
            .filter(EmployeeNote.created_at >= start_dt, EmployeeNote.created_at < end_dt, EmployeeNote.body.like("%إنذار%"))
            .group_by(EmployeeNote.employee_id)
            .all()
        )
        warn_map = {int(emp_id): int(cnt) for emp_id, cnt in warn_counts}
        flagged = []
        for e in employees:
            if warn_map.get(e.id, 0) >= 3:
                flagged.append(e.full_name)
        if flagged:
            alerts.append({
                "title": "موظف عنده 3 إنذارات خلال شهر",
                "desc": ", ".join(flagged[:5]),
                "badge": f"{len(flagged)} موظف",
            })
    except Exception:
        pass

    kpis = [
        {"label": "عدد الموظفين", "value": len(employees), "icon": "bi-people"},
        {"label": "حضور اليوم", "value": present, "icon": "bi-person-check"},
        {"label": "غياب اليوم", "value": absent, "icon": "bi-person-x"},
        {"label": "مغادرات مبكرة", "value": early_cnt, "icon": "bi-box-arrow-right"},
        {"label": "تأخيرات اليوم", "value": late_cnt, "icon": "bi-alarm"},
        {"label": "نسبة الالتزام (شهر)", "value": f"{compliance_this}%", "sub": month_label, "icon": "bi-graph-up"},
        {"label": "إجمالي OT (ساعة)", "value": ot_hours, "sub": f"{round(ot_amount_total,3)} مبلغ", "icon": "bi-clock-history"},
        {"label": "تكلفة الرواتب الحالية", "value": round(payroll_total, 3), "sub": month_label, "icon": "bi-cash-stack"},
    ]

    return templates.TemplateResponse(
        "manager_dashboard.html",
        {
            "request": request,
            "user": u,
            "month": month_key,
            "month_label": month_label,
            "late_limit": late_limit,
            "ot_budget": ot_budget,
            "kpis": kpis,
            "compliance_this": compliance_this,
            "compliance_prev": compliance_prev,
            "compliance_delta": compliance_delta,
            "month_label": month_label,
            "heatmap": heatmap,
            "top_absent": top_absent_ui,
            "top_late": top_late_ui,
            "top_ot_cost": top_ot_ui,
            "alerts": alerts,
            "pending_leaves": pending_leaves,
            "delay_cost": delay_cost,
        },
    )


@app.get("/manager/reports", response_class=HTMLResponse)
def manager_reports(request: Request, db: Session = Depends(get_db), month: str | None = None):
    try:
        u = get_current_manager_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    year, mon, month_key = _parse_month_or_default(month)
    first, next_first = _month_range(year, mon)
    t_today = today_tz()
    upto = t_today if (year == t_today.year and mon == t_today.month) else (next_first - timedelta(days=1))

    employees = (
        db.query(Employee)
        .filter(Employee.is_active == True)
        .order_by(Employee.employee_code.asc())
        .all()
    )

    default_settings = db.get(DailySettings, today_tz())

    # daily attendance chart (present count per day)
    labels = []
    values = []
    cur = first
    tot_present = tot_absent = tot_late = tot_ot = 0
    rows = []

    # monthly per-employee quick stats
    for e in employees:
        summary, _ = compute_month(db, e, year, mon, default_settings, upto=upto)
        dp = int(summary.get("days_present") or 0)
        da = int(summary.get("days_absent") or 0)
        lm = int(summary.get("late_minutes") or 0)
        om = int(summary.get("overtime_minutes") or 0)
        comp = _safe_pct(dp, (dp + da))
        rows.append({
            "emp": e,
            "present_days": dp,
            "absent_days": da,
            "late_minutes": lm,
            "overtime_minutes": om,
            "compliance": comp,
        })
        tot_present += dp
        tot_absent += da
        tot_late += lm
        tot_ot += om

    while cur <= upto:
        s = get_or_none_daily_settings(db, cur)
        if s and (not s.is_holiday):
            p_cnt = 0
            for e in employees:
                r = compute_day(db, e, cur, s)
                if r.get("status") in ("PRESENT", "INCOMPLETE"):
                    p_cnt += 1
            labels.append(cur.isoformat())
            values.append(p_cnt)
        cur = cur + timedelta(days=1)

    compliance = _safe_pct(tot_present, (tot_present + tot_absent))
    absence_pct = _safe_pct(tot_absent, (tot_present + tot_absent))
    ot_hours = round(tot_ot / 60.0, 2)

    # sort rows by biggest impact
    rows = sorted(rows, key=lambda x: (x["compliance"], -x["late_minutes"]), reverse=False)

    return templates.TemplateResponse(
        "manager_reports.html",
        {
            "request": request,
            "user": u,
            "month": month_key,
            "chart": {"labels": labels, "values": values},
            "rows": rows,
            "compliance": compliance,
            "late_minutes": tot_late,
            "ot_hours": ot_hours,
            "absence_pct": absence_pct,
        },
    )


@app.get("/manager/payroll", response_class=HTMLResponse)
def manager_payroll(request: Request, db: Session = Depends(get_db), month: str | None = None):
    try:
        u = get_current_manager_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    year, mon, month_key = _parse_month_or_default(month)
    first, next_first = _month_range(year, mon)
    t_today = today_tz()
    upto = t_today if (year == t_today.year and mon == t_today.month) else (next_first - timedelta(days=1))

    employees = (
        db.query(Employee)
        .filter(Employee.is_active == True)
        .order_by(Employee.employee_code.asc())
        .all()
    )

    default_settings = db.get(DailySettings, today_tz())
    batch = db.query(PayrollBatch).filter(PayrollBatch.month == month_key).first()
    rec_map = {}
    if batch and batch.status in ("APPROVED", "CLOSED"):
        recs = db.query(PayrollRecord).filter(PayrollRecord.batch_id == batch.id).all()
        rec_map = {r.employee_id: r for r in recs}

    rows = []
    gross = deductions = ot_amount = net = 0.0
    paid = unpaid = 0

    for e in employees:
        if e.id in rec_map:
            rec = rec_map[e.id]
            salary_monthly = float(rec.salary_monthly or 0.0)
            total_deductions = float(rec.total_deductions or 0.0)
            overtime_add = float(rec.overtime_add or 0.0)
            total = float(rec.total or 0.0)
            status = batch.status
        else:
            summary, _ = compute_month(db, e, year, mon, default_settings, upto=upto)
            salary_monthly = float(summary.get("salary_monthly") or float(e.salary_monthly or 0.0))
            total_deductions = float(summary.get("total_deductions") or 0.0)
            overtime_add = float(summary.get("overtime_add") or 0.0)
            total = float(summary.get("total") or 0.0)
            status = "DRAFT"

        gross += salary_monthly
        deductions += total_deductions
        ot_amount += overtime_add
        net += total

        if status in ("APPROVED", "CLOSED"):
            paid += 1
        else:
            unpaid += 1

        rows.append({
            "emp": e,
            "salary_monthly": round(salary_monthly, 3),
            "total_deductions": round(total_deductions, 3),
            "overtime_add": round(overtime_add, 3),
            "total": round(total, 3),
            "status": status,
            "status_color": ("success" if status in ("APPROVED","CLOSED") else ("warning" if status=="DRAFT" else "secondary")),
        })

    rows_sorted = sorted(rows, key=lambda r: float(r["total"]), reverse=True)

    # pie: top 6 totals
    top = rows_sorted[:6]
    pie_labels = [t["emp"].full_name for t in top]
    pie_values = [float(t["total"]) for t in top]

    cards = [
        {"label": "إجمالي الرواتب (أساسي)", "value": round(gross, 3), "icon": "bi-cash"},
        {"label": "إجمالي الخصومات", "value": round(deductions, 3), "icon": "bi-dash-circle"},
        {"label": "إجمالي OT", "value": round(ot_amount, 3), "icon": "bi-plus-circle"},
        {"label": "صافي الدفع", "value": round(net, 3), "icon": "bi-cash-stack"},
        {"label": "مدفوع لهم", "value": paid, "icon": "bi-check2-circle"},
        {"label": "غير مدفوع", "value": unpaid, "icon": "bi-exclamation-circle"},
        {"label": "حالة الدفعة", "value": (batch.status if batch else "DRAFT"), "icon": "bi-journal-check"},
        {"label": "الشهر", "value": month_key, "icon": "bi-calendar3"},
    ]

    return templates.TemplateResponse(
        "manager_payroll.html",
        {
            "request": request,
            "user": u,
            "month": month_key,
            "cards": cards,
            "rows": rows_sorted,
            "pie": {"labels": pie_labels, "values": pie_values},
        },
    )


@app.get("/manager/employees", response_class=HTMLResponse)
def manager_employees(request: Request, db: Session = Depends(get_db), q: str | None = None, month: str | None = None):
    try:
        u = get_current_manager_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    year, mon, month_key = _parse_month_or_default(month)
    first, next_first = _month_range(year, mon)
    t_today = today_tz()
    upto = t_today if (year == t_today.year and mon == t_today.month) else (next_first - timedelta(days=1))

    query = db.query(Employee).filter(Employee.is_active == True)
    if q:
        qs = (q or "").strip()
        if qs:
            query = query.filter((Employee.full_name.like(f"%{qs}%")) | (Employee.employee_code.like(f"%{qs}%")))
    employees = query.order_by(Employee.employee_code.asc()).all()

    default_settings = db.get(DailySettings, today_tz())

    rows = []
    for e in employees:
        summary, _ = compute_month(db, e, year, mon, default_settings, upto=upto)
        dp = int(summary.get("days_present") or 0)
        da = int(summary.get("days_absent") or 0)
        lm = int(summary.get("late_minutes") or 0)
        om = int(summary.get("overtime_minutes") or 0)
        comp = _safe_pct(dp, (dp + da))
        rows.append({
            "emp": e,
            "salary_monthly": round(float(summary.get("salary_monthly") or float(e.salary_monthly or 0.0)), 3),
            "compliance": comp,
            "absent_days": da,
            "late_minutes": lm,
            "overtime_minutes": om,
        })

    return templates.TemplateResponse(
        "manager_employees.html",
        {
            "request": request,
            "user": u,
            "q": q or "",
            "month": month_key,
            "rows": rows,
        },
    )


@app.get("/manager/employees/{emp_id}", response_class=HTMLResponse)
def manager_employee_detail(request: Request, emp_id: int, db: Session = Depends(get_db), month: str | None = None):
    try:
        u = get_current_manager_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Not found")

    year, mon, month_key = _parse_month_or_default(month)
    first, next_first = _month_range(year, mon)
    t_today = today_tz()
    upto = t_today if (year == t_today.year and mon == t_today.month) else (next_first - timedelta(days=1))

    default_settings = db.get(DailySettings, today_tz())
    summary, _ = compute_month(db, emp, year, mon, default_settings, upto=upto)

    dp = int(summary.get("days_present") or 0)
    da = int(summary.get("days_absent") or 0)
    lm = int(summary.get("late_minutes") or 0)
    em = int(summary.get("early_leave_minutes") or 0)
    om = int(summary.get("overtime_minutes") or 0)
    comp = _safe_pct(dp, (dp + da))

    cards = [
        {"label": "التزام %", "value": f"{comp}%"},
        {"label": "حضور", "value": dp},
        {"label": "غياب", "value": da},
        {"label": "تأخير (دقيقة)", "value": lm},
        {"label": "مغادرة مبكرة (دقيقة)", "value": em},
        {"label": "OT (ساعة)", "value": round(om/60.0, 2)},
        {"label": "صافي راتب (تقديري)", "value": round(float(summary.get("total") or 0.0), 3)},
        {"label": "OT مبلغ", "value": round(float(summary.get("overtime_add") or 0.0), 3)},
    ]

    # daily rows
    days = []
    labels = []
    values = []
    cur = first
    while cur <= upto:
        s = get_or_none_daily_settings(db, cur)
        if s and (not s.is_holiday):
            r = compute_day(db, emp, cur, s)
            st = r.get("status") or "—"
            st_color = "secondary"
            if st in ("PRESENT", "INCOMPLETE"):
                st_color = "success"
            elif st in ("ABSENT", "ABSENT_PENDING"):
                st_color = "danger"
            elif st == "EXCUSED":
                st_color = "info"

            fi = r.get("first_in")
            lo = r.get("last_out")
            days.append({
                "date": cur.isoformat(),
                "status": st,
                "status_color": st_color,
                "first_in": (fi.strftime("%H:%M") if fi else None),
                "last_out": (lo.strftime("%H:%M") if lo else None),
                "late": int(r.get("late") or 0),
                "early": int(r.get("early_leave") or 0),
                "ot": int(r.get("overtime") or 0),
            })
            labels.append(cur.day)
            values.append(1 if st in ("PRESENT", "INCOMPLETE") else 0)
        cur = cur + timedelta(days=1)

    return templates.TemplateResponse(
        "manager_employee_detail.html",
        {
            "request": request,
            "user": u,
            "emp": emp,
            "month": month_key,
            "month_label": month_key,
            "cards": cards,
            "days": days,
            "spark": {"labels": labels, "values": values},
        },
    )


@app.get("/hr/settings", response_class=HTMLResponse)
def hr_settings_page(request: Request, db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    d = today_tz()
    settings = db.get(DailySettings, d)
    # defaults if not saved for today
    default_start = settings.work_start if settings else time(9, 0)
    default_end = settings.work_end if settings else time(17, 0)
    grace = (settings.grace_minutes if settings else 10)
    early_grace = (getattr(settings, "early_leave_grace_minutes", 5) if settings else 5)
    ot_grace = (getattr(settings, "overtime_grace_minutes", 5) if settings else 5)
    ot_min = (getattr(settings, "overtime_min_minutes", 30) if settings else 30)
    official_min = (getattr(settings, 'official_work_minutes', 480) if settings else 480)
    try:
        official_hours = float(official_min) / 60.0
    except Exception:
        official_hours = 8.0
    return templates.TemplateResponse(
        "hr_settings.html",
        {
            "request": request,
            "user": u,
            "today": d,
            "settings": settings,
            "work_start": default_start.strftime("%H:%M"),
            "work_end": default_end.strftime("%H:%M"),
            "grace_minutes": grace,
            "early_leave_grace_minutes": early_grace,
            "overtime_grace_minutes": ot_grace,
            "overtime_min_minutes": ot_min,
            "err": request.query_params.get("err"),
            "official_hours": official_hours,
        },
    )


@app.post("/hr/settings")
def hr_save_settings(
    request: Request,
    date_str: str = Form(...),
    work_start: str = Form(...),
    work_end: str = Form(...),
    grace_minutes: int = Form(0),
    early_leave_grace_minutes: int = Form(5),
    overtime_grace_minutes: int = Form(5),
    overtime_min_minutes: int = Form(30),
    official_hours: float = Form(8.0),
    is_holiday: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    try:
        d = date.fromisoformat(date_str)
        start_t = time.fromisoformat(work_start)
        end_t = time.fromisoformat(work_end)
    except Exception:
        return RedirectResponse(url="/hr/settings?err=parse", status_code=302)
    if end_t <= start_t:
        return RedirectResponse(url="/hr/settings?err=bad_time", status_code=302)
    holiday = bool(is_holiday)

    existing = db.get(DailySettings, d)
    if existing:
        existing.is_holiday = holiday
        existing.work_start = start_t
        existing.work_end = end_t
        existing.grace_minutes = int(grace_minutes or 0)
        existing.early_leave_grace_minutes = int(early_leave_grace_minutes or 0)
        existing.overtime_grace_minutes = int(overtime_grace_minutes or 0)
        existing.overtime_min_minutes = int(overtime_min_minutes or 0)
        try:
           existing.official_work_minutes = int(round(float(official_hours or 8.0) * 60))
        except Exception:
           existing.official_work_minutes = 480
        existing.created_by_user_id = u.id
    else:
      ds = DailySettings(
            date=d,
            is_holiday=holiday,
            work_start=start_t,
            work_end=end_t,
            grace_minutes=int(grace_minutes or 0),
            early_leave_grace_minutes=int(early_leave_grace_minutes or 0),
            overtime_grace_minutes=int(overtime_grace_minutes or 0),
            overtime_min_minutes=int(overtime_min_minutes or 0),
            official_work_minutes=int(round(float(official_hours or 8.0) * 60)),
            created_by_user_id=u.id,
        )
    if not existing:    
        db.add(ds)
    db.commit()
    return RedirectResponse(url="/hr/dashboard", status_code=302)




def _compute_payroll_for_month(
    db: Session,
    emp: Employee,
    year: int,
    month: int,
    settings: DailySettings | None,
    upto: date | None = None,
):
    """Payroll for a month.
    - For current month: pass upto=today to avoid generating future days.
    - Logic: monthly salary is the baseline; days create *adjustments*:
        * Absent day => - (salary/30)
        * Late penalty => negative adjustment
        * Overtime / bonuses => positive adjustment
    """

    salary_monthly = float(emp.salary_monthly or 0.0)
    base_daily = (salary_monthly / 30.0) if salary_monthly else 0.0

    # Default official shift hours for payroll minute rate (fallback only)
    default_official_minutes = int((getattr(settings, "official_work_minutes", 480) if settings else 480) or 480)
    if default_official_minutes <= 0:
      default_official_minutes = 480
    shift_hours = float(default_official_minutes) / 60.0

    hourly_rate = (base_daily / shift_hours) if base_daily and shift_hours else 0.0
    minute_rate = (hourly_rate / 60.0) if hourly_rate else 0.0

    # Overtime is 1.5x (fixed). Late is deducted by the exact minute rate.
    overtime_mul = float(getattr(settings, "overtime_multiplier", 1.5) if settings else 1.5)
    bonus_perfect = float(getattr(settings, "bonus_perfect_day", 0.0) if settings else 0.0)

    first = date(year, month, 1)
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)

    # end bound
    if upto:
        end_excl = min(nxt, upto + timedelta(days=1))
    else:
        end_excl = nxt

    cur = first

    # totals
    total_adjust = 0.0
    absent_deduction = 0.0
    late_deduction = 0.0
    early_leave_deduction = 0.0
    overtime_add = 0.0
    bonus_add = 0.0

    days_present = 0
    days_absent = 0
    total_late_min = 0
    total_ot_min = 0
    total_early_min = 0

    breakdown = []

    while cur < end_excl:
        day_settings = db.get(DailySettings, cur)
        ds = day_settings or settings

        row = compute_day(db, emp, cur, ds)
        status = row["status"]
        ss = row.get("sched_start")
        se = row.get("sched_end")
        explain = {
            "date": cur.isoformat(),
            "status": status,
            "sched_start": ss.isoformat() if ss else None,
            "sched_end": se.isoformat() if se else None,
            "late_minutes": int(row.get("late") or 0),
            "early_leave_minutes": int(row.get("early_leave") or 0),
            "overtime_minutes": int(row.get("overtime") or 0),
            "base_daily": round(base_daily, 3),
            "items": [],
        }

        day_adjust = 0.0

        # holiday: no change (keep salary as-is)
        if ds and getattr(ds, "is_holiday", False):
            explain["items"].append({"type": "holiday", "amount": 0.0, "note": "عطلة"})
        else:
            if status == "ABSENT":
                days_absent += 1
                if base_daily > 0:
                    day_adjust -= base_daily
                    absent_deduction += base_daily
                    explain["items"].append(
                        {"type": "absent_deduction", "amount": -round(base_daily, 3), "note": "خصم غياب يوم (الراتب/30)"}
                    )
            elif status == "ABSENT_PENDING":
                # pending review: لا خصم ولا بونص
                explain["items"].append({"type": "pending", "amount": 0.0, "note": "غياب قيد المراجعة"})
            else:
                days_present += 1
                late_min = int(row.get("late") or 0)
                early_min = int(row.get("early_leave") or 0)
                ot_min = int(row.get("overtime") or 0)
                total_late_min += late_min
                total_early_min += early_min
                total_ot_min += ot_min

                day_official_minutes = int((getattr(ds, "official_work_minutes", default_official_minutes) if ds else default_official_minutes) or default_official_minutes)
                if day_official_minutes <= 0:
                    day_official_minutes = default_official_minutes
                day_shift_hours = float(day_official_minutes) / 60.0
                day_hourly_rate = (base_daily / day_shift_hours) if base_daily and day_shift_hours else 0.0
                day_minute_rate = (day_hourly_rate / 60.0) if day_hourly_rate else 0.0
                explain["official_work_minutes"] = day_official_minutes
                explain["minute_rate"] = round(day_minute_rate, 5)

                # late deduction (per-minute based on employee salary)
                if late_min > 0 and day_minute_rate > 0:
                    penalty = day_minute_rate * late_min
                    day_adjust -= penalty
                    late_deduction += penalty
                    explain["items"].append(
                        {
                            "type": "late_deduction",
                            "amount": -round(penalty, 3),
                            "note": f"خصم تأخير: {late_min} دقيقة × أجر الدقيقة ({day_minute_rate:.3f})",
                        }
                    )

                # early leave deduction (treated same as lateness)
                if early_min > 0 and day_minute_rate > 0:
                    penalty = day_minute_rate * early_min
                    day_adjust -= penalty
                    early_leave_deduction += penalty
                    explain["items"].append(
                        {
                            "type": "early_leave_deduction",
                            "amount": -round(penalty, 3),
                            "note": f"خصم مغادرة: {early_min} دقيقة × أجر الدقيقة ({day_minute_rate:.3f})",
                        }
                    )
                # overtime pay (minutes beyond official work minutes, only when approved in daily row)
                if ot_min > 0 and day_minute_rate > 0:
                    day_ot_mul = float(getattr(ds, "overtime_multiplier", overtime_mul) if ds else overtime_mul)
                    add_ot = day_minute_rate * ot_min * day_ot_mul
                    day_adjust += add_ot
                    overtime_add += add_ot
                    explain["items"].append(
                        {
                            "type": "overtime_add",
                            "amount": round(add_ot, 3),
                            "note": f"إضافي: {ot_min} دقيقة × أجر الدقيقة ({day_minute_rate:.3f}) × معامل الإضافي ({day_ot_mul:.2f})",
                        }
                    )
                # perfect day bonus (present with no approved late/early minutes)
                if bonus_perfect and late_min == 0 and early_min == 0:
                    day_adjust += bonus_perfect
                    bonus_add += bonus_perfect
                    explain["items"].append(
                        {
                            "type": "perfect_day_bonus",
                            "amount": round(bonus_perfect, 3),
                            "note": f"بونص يوم مثالي (+{bonus_perfect:.3f})",
                        }
                    )

        day_adjust = round(day_adjust, 3)
        explain["day_adjust"] = day_adjust
        total_adjust += day_adjust
        breakdown.append(explain)

        cur = cur + timedelta(days=1)

        # Manual payroll adjustments (HR/Admin)
    
    # Manual payroll adjustments (HR/Admin) - affects payroll as "زيادات/خصومات" only.
    month_key = f"{year:04d}-{month:02d}"
    adj_rows = (
        db.query(PayrollAdjustment)
        .filter(PayrollAdjustment.employee_id == emp.id, PayrollAdjustment.month == month_key)
        .order_by(PayrollAdjustment.id.asc())
        .all()
    )
    manual_total = float(sum((a.amount or 0) for a in adj_rows))
    # Manual positive adjustments are treated as BONUS (not overtime).
    manual_add = float(sum((a.amount or 0) for a in adj_rows if (a.amount or 0) > 0))
    manual_ded = float(-sum((a.amount or 0) for a in adj_rows if (a.amount or 0) < 0))
    bonus_add_total = bonus_add + manual_add

    if manual_total != 0:
        total_adjust += manual_total
        breakdown.append(
            {
                "date": month_key,
                "status": "MANUAL_ADJ",
                "late_minutes": 0,
                "early_leave_minutes": 0,
                "overtime_minutes": 0,
                "base_daily": round(base_daily, 3),
                "items": [{"type": "manual_adjustment", "amount": round(manual_total, 3), "note": "زيادات/خصومات (يدوي)"}],
                "day_adjust": round(manual_total, 3),
            }
        )
    total_pay = round(salary_monthly + total_adjust, 3)

    summary = {
        "salary_monthly": round(salary_monthly, 3),
        "base_daily": round(base_daily, 3),
        "hourly_rate": round(hourly_rate, 3),
        "overtime_multiplier": overtime_mul,
        "minute_rate": round(minute_rate, 5),
        "bonus_perfect_day": bonus_perfect,
        "days_present": days_present,
        "days_absent": days_absent,
        "late_minutes": int(total_late_min),
        "early_leave_minutes": int(total_early_min),
        "overtime_minutes": int(total_ot_min),
        "absent_deduction": round(absent_deduction, 3),
        "late_deduction": round(late_deduction, 3),
        "early_leave_deduction": round(early_leave_deduction, 3),
        "manual_adjustments_total": round(manual_total, 3),
        "manual_additions": round(manual_add, 3),
        "manual_deductions": round(manual_ded, 3),
        "total_deductions": round(absent_deduction + late_deduction + early_leave_deduction + manual_ded, 3),
        "total_additions": round(overtime_add + bonus_add_total, 3),
        "overtime_add": round(overtime_add, 3),
        "bonus_add": round(bonus_add_total, 3),
        "adjustments_total": round(total_adjust, 3),
        "total": total_pay,
    }
    return summary, breakdown


# -------------------------
# Payroll Batches (Monthly approvals / closing)
# -------------------------


def _parse_month_key(month_key: str) -> tuple[int, int, str]:
    """Return (year, month, normalized_key)."""
    mk = (month_key or "").strip()
    y, m = mk.split("-")
    year, mon = int(y), int(m)
    return year, mon, f"{year:04d}-{mon:02d}"


def _upsert_payroll_record(
    db: Session,
    batch_id: int,
    emp: Employee,
    summary: dict,
    breakdown: list,
    locked: bool,
):
    rec = (
        db.query(PayrollRecord)
        .filter(PayrollRecord.batch_id == batch_id, PayrollRecord.employee_id == emp.id)
        .first()
    )
    if not rec:
        rec = PayrollRecord(batch_id=batch_id, employee_id=emp.id)
        db.add(rec)

    # snapshot fields
    rec.salary_monthly = float(summary.get("salary_monthly") or 0.0)
    rec.days_present = int(summary.get("days_present") or 0)
    rec.days_absent = int(summary.get("days_absent") or 0)
    rec.late_minutes = int(summary.get("late_minutes") or 0)
    rec.early_leave_minutes = int(summary.get("early_leave_minutes") or 0)
    rec.overtime_minutes = int(summary.get("overtime_minutes") or 0)

    rec.absent_deduction = float(summary.get("absent_deduction") or 0.0)
    rec.late_deduction = float(summary.get("late_deduction") or 0.0)
    rec.early_leave_deduction = float(summary.get("early_leave_deduction") or 0.0)
    rec.manual_adjustments_total = float(summary.get("manual_adjustments_total") or 0.0)
    rec.overtime_add = float(summary.get("overtime_add") or 0.0)
    rec.bonus_add = float(summary.get("bonus_add") or 0.0)
    rec.total_deductions = float(summary.get("total_deductions") or 0.0)
    rec.total_additions = float(summary.get("total_additions") or 0.0)
    rec.adjustments_total = float(summary.get("adjustments_total") or 0.0)
    rec.total = float(summary.get("total") or 0.0)

    try:
        rec.breakdown_json = json.dumps(breakdown, ensure_ascii=False, default=str)
    except Exception:
        rec.breakdown_json = None

    rec.locked = bool(locked)
    db.flush()
    return rec


def _sync_batch_records(db: Session, batch: PayrollBatch, year: int, mon: int):
    """Compute payroll for all active employees and store it as snapshot records."""
    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.employee_code.asc()).all()
    default_settings = db.get(DailySettings, today_tz())
    upto = today_tz() if (year == today_tz().year and mon == today_tz().month) else None

    for emp in employees:
        summary, breakdown = compute_month(db, emp, year, mon, default_settings, upto=upto)
        _upsert_payroll_record(
            db,
            batch_id=batch.id,
            emp=emp,
            summary=summary,
            breakdown=breakdown,
            locked=(batch.status == "CLOSED"),
        )
    db.commit()


@app.get("/hr/payroll-batches", response_class=HTMLResponse)
def hr_payroll_batches(request: Request, db: Session = Depends(get_db), month: str | None = None):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    # default month
    if not month:
        t = today_tz()
        month = f"{t.year:04d}-{t.month:02d}"

    batches = db.query(PayrollBatch).order_by(PayrollBatch.month.desc()).limit(60).all()

    return templates.TemplateResponse(
        "hr_payroll_batches.html",
        {
            "request": request,
            "nav": _hr_nav_counts(db),
            "user": u,
            "month": month,
            "batches": batches,
        },
    )


@app.post("/hr/payroll-batches/create")
def hr_payroll_batches_create(request: Request, db: Session = Depends(get_db), month: str = Form(...)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    try:
        _y, _m, mk = _parse_month_key(month)
    except Exception:
        return RedirectResponse(url="/hr/payroll-batches", status_code=302)

    batch = db.query(PayrollBatch).filter(PayrollBatch.month == mk).first()
    if not batch:
        batch = PayrollBatch(month=mk, status="DRAFT", created_by_user_id=u.id)
        db.add(batch)
        db.commit()
        db.refresh(batch)

    return RedirectResponse(url=f"/hr/payroll-batches/{batch.id}", status_code=302)


@app.get("/hr/payroll-batches/{batch_id}", response_class=HTMLResponse)
def hr_payroll_batch_detail(batch_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    batch = db.get(PayrollBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Not found")

    year, mon, mk = _parse_month_key(batch.month)

    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.employee_code.asc()).all()
    default_settings = db.get(DailySettings, today_tz())
    upto = today_tz() if (year == today_tz().year and mon == today_tz().month) else None

    rows = []
    totals = {
        "grand_total": 0.0,
        "salary_monthly": 0.0,
        "absent_deduction": 0.0,
        "late_deduction": 0.0,
        "early_leave_deduction": 0.0,
        "overtime_add": 0.0,
        "bonus_add": 0.0,
        "manual_adjustments_total": 0.0,
        "adjustments_total": 0.0,
        "total_deductions": 0.0,
        "total_additions": 0.0,
    }

    # If approved/closed and records exist -> use snapshot
    rec_map = {}
    if batch.status in ("APPROVED", "CLOSED"):
        recs = db.query(PayrollRecord).filter(PayrollRecord.batch_id == batch.id).all()
        rec_map = {r.employee_id: r for r in recs}

    for emp in employees:
        if emp.id in rec_map:
            rec = rec_map[emp.id]
            summary = {
                "salary_monthly": rec.salary_monthly,
                "days_present": rec.days_present,
                "days_absent": rec.days_absent,
                "late_minutes": rec.late_minutes,
                "early_leave_minutes": rec.early_leave_minutes,
                "overtime_minutes": rec.overtime_minutes,
                "absent_deduction": rec.absent_deduction,
                "late_deduction": rec.late_deduction,
                "early_leave_deduction": rec.early_leave_deduction,
                "manual_adjustments_total": rec.manual_adjustments_total,
                "overtime_add": rec.overtime_add,
                "bonus_add": rec.bonus_add,
                "total_deductions": rec.total_deductions,
                "total_additions": rec.total_additions,
                "adjustments_total": rec.adjustments_total,
                "total": rec.total,
            }
        else:
            summary, breakdown = compute_month(db, emp, year, mon, default_settings, upto=upto)
            # breakdown_json for modal
            try:
                bjson = json.dumps(breakdown, ensure_ascii=False, default=str)
            except Exception:
                bjson = "[]"
        # when snapshot exists, try read breakdown_json
        if emp.id in rec_map:
            bjson = rec_map[emp.id].breakdown_json or "[]"

        rows.append({"emp": emp, "summary": summary, "breakdown_json": bjson})

        totals["grand_total"] += float(summary.get("total") or 0.0)
        for k in (
            "salary_monthly",
            "absent_deduction",
            "late_deduction",
            "early_leave_deduction",
            "overtime_add",
            "bonus_add",
            "manual_adjustments_total",
            "adjustments_total",
            "total_deductions",
            "total_additions",
        ):
            totals[k] += float(summary.get(k) or 0.0)

    # rounding for display
    for k in list(totals.keys()):
        totals[k] = round(float(totals[k] or 0.0), 3)

    return templates.TemplateResponse(
        "hr_payroll_batch_detail.html",
        {
            "request": request,
            "nav": _hr_nav_counts(db),
            "user": u,
            "batch": batch,
            "month": mk,
            "rows": rows,
            "totals": totals,
        },
    )


@app.post("/hr/payroll-batches/{batch_id}/approve")
def hr_payroll_batch_approve(batch_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    batch = db.get(PayrollBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Not found")
    if batch.status == "CLOSED":
        return RedirectResponse(url=f"/hr/payroll-batches/{batch.id}", status_code=302)

    year, mon, _mk = _parse_month_key(batch.month)
    _sync_batch_records(db, batch, year, mon)

    batch.status = "APPROVED"
    batch.approved_by_user_id = u.id
    batch.approved_at = datetime.now()
    db.commit()

    return RedirectResponse(url=f"/hr/payroll-batches/{batch.id}", status_code=302)


@app.post("/hr/payroll-batches/{batch_id}/close")
def hr_payroll_batch_close(batch_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    batch = db.get(PayrollBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Not found")
    if batch.status == "CLOSED":
        return RedirectResponse(url=f"/hr/payroll-batches/{batch.id}", status_code=302)

    # compute snapshot then lock
    year, mon, _mk = _parse_month_key(batch.month)
    _sync_batch_records(db, batch, year, mon)

    batch.status = "CLOSED"
    batch.closed_by_user_id = u.id
    batch.closed_at = datetime.now()

    # lock all records
    db.query(PayrollRecord).filter(PayrollRecord.batch_id == batch.id).update({"locked": True})
    db.commit()

    return RedirectResponse(url=f"/hr/payroll-batches/{batch.id}", status_code=302)





@app.get("/hr/tickets", response_class=HTMLResponse)
def hr_tickets(request: Request, db: Session = Depends(get_db)):
    u = get_current_hr_user(request, db)
    tickets = (
        db.query(SupportTicket)
        .join(Employee, SupportTicket.employee_id == Employee.id)
        .filter(SupportTicket.status != "CLOSED")
        .order_by(SupportTicket.id.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse("hr_tickets.html", {"request": request,
            "nav": _hr_nav_counts(db), "user": u, "tickets": tickets})


@app.get("/hr/tickets/{ticket_id}", response_class=HTMLResponse)
def hr_ticket_thread(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Not found")

    replies = (
        db.query(SupportTicketReply)
        .filter(SupportTicketReply.ticket_id == t.id)
        .order_by(SupportTicketReply.created_at.asc())
        .all()
    )
    return templates.TemplateResponse(
        "hr_ticket_thread.html",
        {"request": request, "nav": _hr_nav_counts(db), "user": u, "ticket": t, "replies": replies},
    )


@app.post("/hr/tickets/{ticket_id}/reply")
def hr_ticket_reply(ticket_id: int, request: Request, body: str = Form(...), db: Session = Depends(get_db)):
    try:
        _u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Not found")

    if t.status == "CLOSED":
        return RedirectResponse(url=f"/hr/tickets/{t.id}", status_code=302)

    body_clean = (body or "").strip()
    if body_clean:
        r = SupportTicketReply(ticket_id=t.id, sender="HR", body=body_clean)
        db.add(r)
        # auto move OPEN -> IN_PROGRESS on first reply
        if t.status == "OPEN":
            t.status = "IN_PROGRESS"
            db.add(t)
        db.commit()

    return RedirectResponse(url=f"/hr/tickets/{t.id}", status_code=302)

@app.post("/hr/tickets/{ticket_id}/status")
def hr_ticket_status(ticket_id: int, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    u = get_current_hr_user(request, db)
    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    st = status.upper().strip()
    if st not in ("OPEN", "IN_PROGRESS", "CLOSED"):
        st = "OPEN"
    t.status = st
    db.add(t)
    db.commit()
    return RedirectResponse(url="/hr/tickets", status_code=302)

@app.get("/hr/payroll", response_class=HTMLResponse)
def hr_payroll(request: Request, db: Session = Depends(get_db), month: str | None = None):
    u = get_current_hr_user(request, db)
    # month format: YYYY-MM
    if month:
        y, m = month.split("-")
        year, mon = int(y), int(m)
    else:
        t = today_tz()
        year, mon = t.year, t.month
        month = f"{year:04d}-{mon:02d}"

    # default settings: use today's settings as defaults for multipliers
    default_settings = db.get(DailySettings, today_tz())

    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.employee_code.asc()).all()
    rows = []
    totals = {
        'salary_monthly': 0.0,
        'absent_deduction': 0.0,
        'late_deduction': 0.0,
        'early_leave_deduction': 0.0,
        'overtime_add': 0.0,
        'bonus_add': 0.0,
        'adjustments_total': 0.0,
        'grand_total': 0.0,
    }
    for e in employees:
        upto = today_tz() if (year == today_tz().year and mon == today_tz().month) else None
        summary, breakdown = compute_month(db, e, year, mon, default_settings, upto=upto)
        rows.append({"emp": e, "summary": summary, "breakdown_json": json.dumps(breakdown, ensure_ascii=False, default=str)})        # accumulate totals
        try:
            totals['grand_total'] += float(summary.get('total') or 0)
        except Exception:
            pass
        for k in ('salary_monthly','absent_deduction','late_deduction','early_leave_deduction','overtime_add','bonus_add','adjustments_total'):
            try:
                totals[k] += float(summary.get(k) or 0)
            except Exception:
                pass

    return templates.TemplateResponse(
        "hr_payroll.html",
        {"request": request, "user": u, "month": month, "rows": rows, "totals": totals},
    )



@app.post("/hr/payroll/adjust")
def hr_payroll_adjust(
    request: Request,
    db: Session = Depends(get_db),
    month: str = Form(...),
    emp_id: int = Form(...),
    amount: str = Form(...),
    reason: str | None = Form(None),
    next_url: str | None = Form(None),
):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    try:
        amt = float(amount)
    except Exception:
        amt = 0.0

    pa = PayrollAdjustment(
        employee_id=emp_id,
        month=month.strip(),
        amount=amt,
        reason=reason.strip() if reason else None,
        created_by_user_id=u.id,
    )
    db.add(pa)
    db.commit()

    # redirect back (defaults to payroll page)
    if next_url and str(next_url).strip():
        return RedirectResponse(url=str(next_url).strip(), status_code=302)
    return RedirectResponse(url=f"/hr/payroll?month={month.strip()}", status_code=302)
@app.get("/hr/today.csv")
def hr_today_csv(request: Request, db: Session = Depends(get_db)):
    try:
        _u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    d = today_tz()
    settings = get_or_none_daily_settings(db, d)
    if not settings:
        raise HTTPException(status_code=400, detail="لا توجد إعدادات لليوم")

    rows, _counts = compute_today_sheet(db, d, settings)

    def gen():
        yield "employee_code,full_name,status,late_minutes,first_in,last_out\n"
        for r in rows:
            fi = r["first_in"].isoformat(sep=" ") if r["first_in"] else ""
            lo = r["last_out"].isoformat(sep=" ") if r["last_out"] else ""
            yield f"{r['employee_code']},{r['full_name']},{r['status']},{r['late_minutes']},{fi},{lo}\n"

    return StreamingResponse(gen(), media_type="text/csv")


# -------------------------
# HR: Employees management & Reports
# -------------------------

@app.get("/hr/employees", response_class=HTMLResponse)
def hr_employees(request: Request, db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    employees = db.query(Employee).order_by(Employee.employee_code.asc()).all()
    return templates.TemplateResponse(
        "hr_employees.html",
        {"request": request, "user": u, "employees": employees},
    )

@app.get("/hr/employees/new", response_class=HTMLResponse)
def hr_new_employee_page(request: Request, db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)
    return templates.TemplateResponse("hr_employee_new.html", {"request": request, "user": u})

@app.post("/hr/employees/new")
def hr_new_employee(
    request: Request,
    employee_code: str = Form(...),
    full_name: str = Form(...),
    national_id: str | None = Form(None),
    phone: str | None = Form(None),
    salary_monthly: float | None = Form(None),
    pin: str = Form(...),
    allowed_ip: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        _u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    exists = db.query(Employee).filter(Employee.employee_code == employee_code).first()
    if exists:
        return templates.TemplateResponse(
            "hr_employee_new.html",
            {"request": request, "error": "الكود موجود مسبقاً."},
            status_code=400,
        )

    emp = Employee(
        employee_code=employee_code.strip(),
        full_name=full_name.strip(),
        national_id=national_id.strip() if national_id else None,
        phone=phone.strip() if phone else None,
        salary_monthly=float(salary_monthly) if salary_monthly not in (None, "") else None,
        allowed_ip=allowed_ip.strip() if allowed_ip else None,
        pin_hash=hash_pin(pin.strip()),
        is_active=True,
    )
    db.add(emp)
    db.commit()
    return RedirectResponse(url="/hr/employees", status_code=302)

@app.get("/hr/employees/{emp_id}", response_class=HTMLResponse)
def hr_employee_detail(request: Request, emp_id: int, db: Session = Depends(get_db)):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Not found")
    notes = (
        db.query(EmployeeNote)
        .filter(EmployeeNote.employee_id == emp.id)
        .order_by(EmployeeNote.created_at.desc())
        .limit(50)
        .all()
    )
    return templates.TemplateResponse(
        "hr_employee_detail.html",
        {"request": request, "nav": _hr_nav_counts(db), "user": u, "emp": emp, "notes": notes},
    )


@app.post("/hr/employees/{emp_id}/note")
def hr_employee_add_note(
    emp_id: int,
    request: Request,
    body: str = Form(...),
    visible_to_employee: int = Form(1),
    db: Session = Depends(get_db),
):
    """إضافة ملاحظة للموظف (اختياري: تظهر للموظف في ملفه)."""
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Not found")

    body_clean = (body or "").strip()
    if body_clean:
        n = EmployeeNote(
            employee_id=emp.id,
            body=body_clean,
            visible_to_employee=bool(int(visible_to_employee)),
            created_by_user_id=u.id,
        )
        db.add(n)
        db.commit()

    return RedirectResponse(url=f"/hr/employees/{emp.id}", status_code=302)

@app.post("/hr/employees/{emp_id}/update")
def hr_employee_update(
    request: Request,
    emp_id: int,
    full_name: str = Form(...),
    national_id: str | None = Form(None),
    phone: str | None = Form(None),
    salary_monthly: float | None = Form(None),
    is_active: int = Form(1),
    allowed_ip: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        _u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Not found")

    emp.full_name = full_name.strip()
    emp.national_id = national_id.strip() if national_id else None
    emp.phone = phone.strip() if phone else None
    emp.allowed_ip = allowed_ip.strip() if allowed_ip else None
    emp.salary_monthly = float(salary_monthly) if salary_monthly not in (None, "") else None
    emp.is_active = bool(is_active)
    db.add(emp)
    db.commit()
    return RedirectResponse(url=f"/hr/employees/{emp_id}", status_code=302)

def _compute_day_row_for_employee(db: Session, emp: Employee, d: date, settings: DailySettings | None, *, write_db: bool = False):
    logs = (
        db.query(AttendanceLog)
        .filter(
            AttendanceLog.employee_id == emp.id,
            AttendanceLog.is_valid == True,
            AttendanceLog.day_date == d,
        )
        .order_by(AttendanceLog.server_timestamp.asc())
        .all()
    )

    first_in = next((l for l in logs if l.action == "IN"), None)
    last_out = next((l for l in reversed(logs) if l.action == "OUT"), None)
    

    in_logs = [l for l in logs if l.action == "IN"]
    out_logs = [l for l in logs if l.action == "OUT"]
    in_count = len(in_logs)
    out_count = len(out_logs)

    # Build simple sessions list by pairing each IN with the next OUT after it.
    # NOTE: we add duration_sec/duration_min for UI warnings (does NOT change payroll logic).
    sessions = []
    j = 0
    for i_log in in_logs:
        out_log = None
        while j < len(out_logs) and _as_naive(out_logs[j].server_timestamp) and _as_naive(out_logs[j].server_timestamp) < _as_naive(i_log.server_timestamp):
            j += 1
        if j < len(out_logs):
            out_log = out_logs[j]
            j += 1

        duration_sec = None
        duration_min = None
        try:
            if out_log and _as_naive(out_log.server_timestamp) and _as_naive(i_log.server_timestamp):
                duration_sec = int((_as_naive(out_log.server_timestamp) - _as_naive(i_log.server_timestamp)).total_seconds())
                duration_min = max(0, int(round(duration_sec / 60)))
        except Exception:
            duration_sec = None
            duration_min = None

        sessions.append({"in": i_log, "out": out_log, "duration_sec": duration_sec, "duration_min": duration_min})
    

    if settings and settings.is_holiday:
        return {
            "emp": emp,
            "status": "HOLIDAY",
            "first_in": None,
            "first_in_log": None,
            "last_out": None,
            "last_out_log": None,
            "late": 0,
            "overtime": 0,
            "early_leave": 0,
            "early_leave_seconds": 0,
            "early_leave_hms": None,
            "in_count": 0,
            "out_count": 0,
            "sessions": [],
            "area": None,
            "region": None,
            "map_url": None,
            "raw_late": 0,
            "raw_early_leave": 0,
            "raw_status": "HOLIDAY",
            "decision_late": None,
            "decision_early_leave": None,
            "decision_absence": None,
            "adj": None,
        }

    # settings precedence: employee overrides daily settings
    work_start = emp.work_start or (settings.work_start if settings else None)
    work_end = emp.work_end or (settings.work_end if settings else None)
    grace = emp.grace_minutes
    if grace is None:
        grace = (settings.grace_minutes if settings else 0)
    grace = int(grace or 0)
    grace = max(grace, 0)
    
    early_leave_grace = int((getattr(settings, "early_leave_grace_minutes", 5) if settings else 5) or 0)
    early_leave_grace = max(early_leave_grace, 0)
    overtime_grace = int((getattr(settings, "overtime_grace_minutes", 5) if settings else 5) or 0)
    overtime_grace = max(overtime_grace, 0)
    overtime_min = int((getattr(settings, "overtime_min_minutes", 30) if settings else 30) or 0)
    overtime_min = max(overtime_min, 0)

    late_minutes = 0
    if first_in and work_start:
      start_time_dt = datetime.combine(d, work_start)
      first_in_ts = _as_naive(first_in.server_timestamp)
      if first_in_ts and first_in_ts > start_time_dt:
          late_from_start = _ceil_minutes(int((first_in_ts - start_time_dt).total_seconds()))
          # إذا ضمن السماحية => لا يوجد تأخير
          if late_from_start > grace:
              # إذا تجاوز السماحية => يتحسب من بداية الدوام الرسمي
              late_minutes = int(late_from_start)

   

    work_minutes = None
    try:
        total = 0
        has_any = False
        for s in sessions:
            i_log = s.get("in")
            o_log = s.get("out")
            if not i_log or not o_log:
                continue
            i_ts = _as_naive(i_log.server_timestamp)
            o_ts = _as_naive(o_log.server_timestamp)
            if i_ts and o_ts and o_ts >= i_ts:
                total += int((o_ts - i_ts).total_seconds() // 60)
                has_any = True
        if has_any:
            work_minutes = total
    except Exception:
        work_minutes = work_minutes  # keep whatever it was
    # Official duration (minutes) comes from settings (default 8 hours)
    official_minutes = int(getattr(settings, "official_work_minutes", 480) if settings else 480)
    if official_minutes <= 0:
        official_minutes = 480

    # Minutes worked after scheduled end (used as a visible event for HR review)
    post_shift_extra_minutes = 0
    try:
        if work_end:
            sched_end_ts = datetime.combine(d, work_end)
            for s in sessions:
                i_log = s.get("in")
                o_log = s.get("out")
                i_ts = _as_naive(i_log.server_timestamp) if i_log else None
                o_ts = _as_naive(o_log.server_timestamp) if o_log else None
                if i_ts and o_ts and o_ts > sched_end_ts:
                    extra_start = max(i_ts, sched_end_ts)
                    post_shift_extra_minutes += max(0, int((o_ts - extra_start).total_seconds() // 60))
    except Exception:
        post_shift_extra_minutes = 0

    raw_work_minutes = int(work_minutes or 0)
    raw_overtime_minutes = max(0, raw_work_minutes - official_minutes)

    # Review overtime pool:
    # - normal overtime from total work over official hours
    # - OR time worked after scheduled end (for cases like 08:15 -> 16:15)
    review_overtime_minutes = int(raw_overtime_minutes or 0)
    has_overtime_review = review_overtime_minutes > 0 or int(post_shift_extra_minutes or 0) > 0

    deficit_raw_minutes = 0
    if work_minutes is not None:
        deficit_raw_minutes = max(0, official_minutes - raw_work_minutes)
        
    # Minimum threshold applies to normal overtime,
    # but post-shift extra can still be reviewed even if below threshold.
    payable_overtime_raw = int(review_overtime_minutes)
    if payable_overtime_raw < overtime_min and int(post_shift_extra_minutes or 0) <= 0:
        payable_overtime_raw = 0
    # NOTE: we no longer compute early leave as segments. Any shortfall from official_minutes is "deficit".
    early_leave_total_minutes = int(deficit_raw_minutes)
    early_leave_approved_minutes = 0
    early_leave_seconds = int(early_leave_total_minutes * 60) if early_leave_total_minutes > 0 else 0
    early_leave_hms = None
    if early_leave_seconds > 0:
       h = early_leave_seconds // 3600
       rem = early_leave_seconds % 3600
       mm = rem // 60
       ss = rem % 60
       early_leave_hms = f"{h:02d}:{mm:02d}:{ss:02d}"
    
    overtime_minutes = 0
    status = "ABSENT"
    if first_in and last_out:
        status = "PRESENT"
    elif first_in and not last_out:
        status = "INCOMPLETE"

    area = None
    region = None
    if first_in:
        area = first_in.area_name
        region = first_in.region_name
    elif last_out:
        area = last_out.area_name
        region = last_out.region_name

    # Build map url from whichever log has coordinates (prefer IN)
    map_url = None
    lat = None
    lng = None
    src = first_in or last_out
    if src:
        try:
            lat = float(src.lat) if src.lat is not None else None
            lng = float(src.lng) if src.lng is not None else None
        except Exception:
            lat = None
            lng = None
    if lat is not None and lng is not None:
        map_url = f"https://www.google.com/maps?q={lat:.7f},{lng:.7f}"

    # HR/Admin review (approve/reject) + excuses
    raw_late_minutes = int(late_minutes or 0)
    raw_early_leave_minutes = int(early_leave_total_minutes or 0)
    early_leave_minutes = int(early_leave_approved_minutes or 0)
    raw_status = status


    # Auto-create a pending adjustment record whenever there is something to review.
    # IMPORTANT: only when HR explicitly commits/rebuilds. Reports must be read-only.
    if write_db:
        if not (
            db.query(AttendanceAdjustment)
            .filter(AttendanceAdjustment.employee_id == emp.id, AttendanceAdjustment.day_date == d)
            .first()
        ):
            if raw_late_minutes > 0 or raw_early_leave_minutes > 0 or has_overtime_review or raw_status == "ABSENT":
                new_adj = AttendanceAdjustment(employee_id=emp.id, day_date=d)
                db.add(new_adj)
                db.commit()

    adj = (
        db.query(AttendanceAdjustment)
        .filter(AttendanceAdjustment.employee_id == emp.id, AttendanceAdjustment.day_date == d)
        .first()
    )
    
    decision_late = getattr(adj, "decision_late", None) if adj else None
    decision_early = getattr(adj, "decision_early_leave", None) if adj else None
    decision_absence = getattr(adj, "decision_absence", None) if adj else None
    decision_overtime = getattr(adj, "decision_overtime", None) if adj else None
        # Manual overrides from HR report page
    manual_late = getattr(adj, "manual_late_minutes", None) if adj else None
    manual_early = getattr(adj, "manual_early_leave_minutes", None) if adj else None
    manual_ot = getattr(adj, "manual_overtime_minutes", None) if adj else None
    manual_abs = (getattr(adj, "manual_absence_status", None) or "").strip().upper() if adj else ""
    manual_late_override = manual_late is not None
    manual_early_override = manual_early is not None
    manual_ot_override = manual_ot is not None
    manual_abs_override = manual_abs in ("PRESENT", "ABSENT", "EXCUSED")
    if manual_late is not None:
        raw_late_minutes = max(0, int(manual_late or 0))

    if manual_early is not None:
        raw_early_leave_minutes = max(0, int(manual_early or 0))
        early_leave_seconds = int(raw_early_leave_minutes * 60)
        if early_leave_seconds > 0:
            h = early_leave_seconds // 3600
            rem = early_leave_seconds % 3600
            mm = rem // 60
            ss = rem % 60
            early_leave_hms = f"{h:02d}:{mm:02d}:{ss:02d}"
        else:
            early_leave_hms = None

    if manual_ot is not None:
        review_overtime_minutes = max(0, int(manual_ot or 0))
        has_overtime_review = review_overtime_minutes > 0

    if manual_abs == "PRESENT":
        raw_status = "PRESENT"
        status = "PRESENT"
    elif manual_abs == "ABSENT":
        raw_status = "ABSENT"
        status = "ABSENT"
    elif manual_abs == "EXCUSED":
        raw_status = "ABSENT"
        status = "EXCUSED"
    # Compensation flow:
    # use overtime minutes first to offset late / deficit, then the remainder can be payable overtime
    late_after_comp = int(raw_late_minutes or 0)
    deficit_after_comp = int(raw_early_leave_minutes or 0)
    remaining_ot = int(review_overtime_minutes or 0)

    if adj and getattr(adj, "compensate_late", False) and remaining_ot > 0 and late_after_comp > 0:
        used = min(remaining_ot, late_after_comp)
        late_after_comp -= used
        remaining_ot -= used
    
    if adj and getattr(adj, "compensate_early_leave", False):

       if remaining_ot >= deficit_after_comp:
           remaining_ot -= deficit_after_comp
           deficit_after_comp = 0

       else:
           deficit_after_comp -= remaining_ot
           remaining_ot = 0
    # Defaults: nothing is deducted unless explicitly APPROVED.
    # Late (deduct only if APPROVED, after compensation)
    approved_late = int(raw_late_minutes or 0)
    
    
    if raw_late_minutes > 0:
        if manual_late_override:
            late_minutes = int(late_after_comp)
        elif decision_late == "APPROVED":
            late_minutes = int(min(approved_late, late_after_comp))
        else:
            late_minutes = 0
    else:
        late_minutes = 0

    # Deficit/Early leave (deduct only if APPROVED, after compensation)
    if raw_early_leave_minutes > 0:
        if manual_early_override:
            early_leave_minutes = int(deficit_after_comp)
        elif decision_early == "APPROVED":
            early_leave_minutes = int(deficit_after_comp)
        else:
            early_leave_minutes = 0

        early_leave_seconds = int(early_leave_minutes * 60)
        if early_leave_seconds > 0:
            h = early_leave_seconds // 3600
            rem = early_leave_seconds % 3600
            mm = rem // 60
            ss = rem % 60
            early_leave_hms = f"{h:02d}:{mm:02d}:{ss:02d}"
        else:
            early_leave_hms = None

    # Payable overtime: remaining minutes after compensation + threshold + HR approval
    overtime_minutes = 0
    payable_remaining = int(remaining_ot)
    if payable_remaining < overtime_min and int(post_shift_extra_minutes or 0) <= 0:
        payable_remaining = 0
    
    if has_overtime_review:
        if manual_ot_override:
            overtime_minutes = int(payable_remaining)
        elif decision_overtime == "APPROVED" and not (adj and getattr(adj, "excuse_overtime", False)):
            overtime_minutes = int(payable_remaining)
        else:
            overtime_minutes = 0
    if raw_status == "ABSENT" and not manual_abs_override:
        if decision_absence == "APPROVED":
            status = "ABSENT"  # will be deducted
        elif decision_absence == "REJECTED" or (adj and getattr(adj, "excuse_absence", False)):
            status = "EXCUSED"
        else:
            status = "ABSENT_PENDING"

    # Explicit excuses always win
    early_leave_segments = []
    if adj:
        if adj.excuse_late:
            late_minutes = 0
        if getattr(adj, "excuse_early_leave", False):
            early_leave_minutes = 0
            early_leave_seconds = 0
            early_leave_hms = None
        if adj.excuse_absence and raw_status == "ABSENT":
            status = "EXCUSED"
    work_docs = (
    db.query(WorkDocumentation)
    .filter(WorkDocumentation.employee_id == emp.id, WorkDocumentation.day_date == d)
    .order_by(WorkDocumentation.server_timestamp.asc())
    .all()
    )  
    return {
        "date": d,
        "emp": emp,
        "status": status,
        "sched_start": datetime.combine(d, work_start) if work_start else None,
        "sched_end": datetime.combine(d, work_end) if work_end else None,
        "first_in": _as_naive(first_in.server_timestamp) if first_in else None,
        "first_in_log": first_in,
        "last_out": _as_naive(last_out.server_timestamp) if last_out else None,
        "last_out_log": last_out,
        "late": late_minutes,
        "raw_late": raw_late_minutes,
        "raw_early_leave": raw_early_leave_minutes,
        "raw_status": raw_status,
        "decision_late": decision_late,
        "decision_early_leave": decision_early,
        "decision_absence": decision_absence,
        "decision_overtime": decision_overtime,
        "raw_overtime": int(review_overtime_minutes or 0),
        "raw_overtime_from_total_work": int(raw_overtime_minutes or 0),
        "post_shift_extra_minutes": int(post_shift_extra_minutes or 0),
        "overtime_after_comp": int(remaining_ot or 0),
        "early_leave": early_leave_minutes,
        "early_leave_seconds": early_leave_seconds,
        "early_leave_hms": early_leave_hms,
        "in_count": in_count,
        "out_count": out_count,
        "sessions": sessions,
        "early_leave_segments": early_leave_segments,
        "overtime": overtime_minutes,
        "work_minutes": work_minutes,
        "work_duration": (f"{(work_minutes or 0)//60:02d}:{(work_minutes or 0)%60:02d}" if work_minutes is not None else None),
        "area": area,
        "region": region,
        "map_url": map_url,
        "adj": adj,
        "work_docs": work_docs,
        "work_docs_count": len(work_docs),
         }
    

# ──────────────────────────────────────────────────────────────────────────────
# Single source of truth for calculations
# Any page (employee/HR/admin/payroll) must use these helpers.
# ──────────────────────────────────────────────────────────────────────────────

def compute_day(db: Session, emp: Employee, d: date, settings: DailySettings, *, write_db: bool = False):
    """Unified day result (raw + approved + decisions).

    This is a thin, stable wrapper around `_compute_day_row_for_employee` to avoid
    duplicated logic across pages.
    """
    row = _compute_day_row_for_employee(db, emp, d, settings, write_db=write_db)

    # Normalize / enrich keys used by newer UI code.
    row["late_raw_min"] = int(row.get("raw_late") or 0)
    row["late_approved_min"] = int(row.get("late") or 0)

    row["early_leave_raw_min"] = int(row.get("raw_early_leave") or 0)
    row["early_leave_approved_min"] = int(row.get("early_leave") or 0)
    row["overtime_raw_min"] = int(row.get("raw_overtime") or 0)
    row["overtime_approved_min"] = int(row.get("overtime") or 0)
    row["overtime_after_comp_min"] = int(row.get("overtime_after_comp") or 0)
    row["absence_raw_status"] = row.get("raw_status")

    if row.get("raw_status") == "ABSENT":
        # status values: ABSENT (approved for deduction) / EXCUSED / ABSENT_PENDING
        row["absence_approved_status"] = row.get("status")
    else:
        row["absence_approved_status"] = None
    
    # مغادرات أثناء الدوام:
    # = الدوام الرسمي - مدة العمل الفعلية - التأخير
    # ولا يجوز أن تتجاوز ما تبقى من الشفت
    ext_count = 0
    ext_min = 0
    try:
        official_minutes = int(getattr(settings, "official_work_minutes", 480) if settings else 480)
        if official_minutes <= 0:
            official_minutes = 480

        worked = int(row.get("work_minutes") or 0)
        late_raw = int(row.get("late_raw_min") or 0)

        ext_min = max(0, official_minutes - worked - late_raw)

        # إذا أكمل أو تجاوز الدوام الرسمي، لا توجد مغادرات أثناء الدوام
        if worked >= official_minutes:
            ext_min = 0

        # عدد المغادرات الفعلي يبقى من الجلسات نفسها
        sess = row.get("sessions") or []
        for i in range(len(sess) - 1):
            out_log = sess[i].get("out")
            next_in = sess[i + 1].get("in")
            if out_log and next_in:
                out_ts = _as_naive(out_log.server_timestamp)
                in_ts = _as_naive(next_in.server_timestamp)
                if out_ts and in_ts and in_ts > out_ts:
                    ext_count += 1
    except Exception:
        ext_min = 0
        ext_count = 0
    row["external_break_min"] = ext_min
    row["external_break_count"] = ext_count
    row["post_shift_extra_min"] = int(row.get("post_shift_extra_minutes") or 0)
    row["overtime_raw_min"] = int(row.get("overtime_raw_min") or row.get("raw_overtime") or 0)
    row["overtime_approved_min"] = int(row.get("overtime_approved_min") or row.get("overtime") or 0)
    row["early_leave_raw_min"] = int(row.get("early_leave_raw_min") or row.get("raw_early_leave") or 0)
    row["early_leave_approved_min"] = int(row.get("early_leave_approved_min") or row.get("early_leave") or 0)
    return row


def compute_month(
    db: Session,
    emp: Employee,
    year: int,
    month: int,
    settings: DailySettings,
    *,
    upto: date | None = None,
    ):
    """Return (summary, breakdown) for payroll month using the unified day result."""
    return _compute_payroll_for_month(db, emp, year, month, settings, upto=upto)



@app.post("/hr/employees/{emp_id}/deactivate")
def hr_employee_deactivate(
    request: Request,
    emp_id: int,
    db: Session = Depends(get_db),
):
    try:
        _u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Not found")

    emp.is_active = False
    db.add(emp)
    db.commit()
    return RedirectResponse(url=f"/hr/employees/{emp_id}", status_code=302)

@app.post("/hr/employees/{emp_id}/adjust")
def hr_employee_adjust(
    request: Request,
    emp_id: int,
    date_str: str = Form(...),
    excuse_late: int | None = Form(None),
    excuse_early_leave: int | None = Form(None),
    excuse_absence: int | None = Form(None),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Excuse lateness/absence for a specific employee day (admin override)."""
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        d = date.fromisoformat(date_str.strip())
    except Exception:
        return RedirectResponse(url=f"/hr/employees/{emp_id}?err=bad_date", status_code=302)

    ex_late = bool(excuse_late)
    ex_early = bool(excuse_early_leave)
    ex_abs = bool(excuse_absence)
    note_clean = (note or "").strip() or None

    adj = (
        db.query(AttendanceAdjustment)
        .filter(AttendanceAdjustment.employee_id == emp_id, AttendanceAdjustment.day_date == d)
        .first()
    )

    # if nothing selected and no note -> delete adjustment (reset)
    if (not ex_late) and (not ex_early) and (not ex_abs) and (note_clean is None):
        if adj:
            db.delete(adj)
            db.commit()
        return RedirectResponse(url=f"/hr/employees/{emp_id}", status_code=302)

    if not adj:
        adj = AttendanceAdjustment(employee_id=emp_id, day_date=d)
        db.add(adj)

    adj.excuse_late = ex_late
    adj.excuse_early_leave = ex_early
    adj.excuse_absence = ex_abs
    adj.note = note_clean
    adj.updated_by_user_id = getattr(u, "id", None)

    if note_clean:
        adj.note = note_clean

    db.add(adj)
    db.commit()
    return RedirectResponse(url=f"/hr/employees/{emp_id}", status_code=302)



@app.post("/hr/employees/{emp_id}/reset_pin")
def hr_employee_reset_pin(
    request: Request,
    emp_id: int,
    new_pin: str = Form(...),
    confirm_pin: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        _u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Not found")

    p1 = (new_pin or "").strip()
    p2 = (confirm_pin or "").strip()
    if not p1 or p1 != p2:
        return RedirectResponse(url=f"/hr/employees/{emp_id}?err=pin_mismatch", status_code=302)

    emp.pin_hash = hash_pin(p1)
    db.add(emp)
    db.commit()
    return RedirectResponse(url=f"/hr/employees/{emp_id}?ok=pin_updated", status_code=302)


@app.post("/hr/attendance/decision")
def hr_attendance_decision(
    request: Request,
    emp_id: int = Form(...),
    date_str: str = Form(...),
    kind: str = Form(...),
    decision: str = Form(...),
    note: str | None = Form(None),
    next_url: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """HR سريع: OK يعني تُحسب (لا إعفاء), رفض يعني إعفاء.
    kind: late | early | absent
    """
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    try:
        d = date.fromisoformat(date_str.strip())
    except Exception:
        return RedirectResponse(url="/hr/dashboard", status_code=302)

    kind = (kind or "").lower().strip()
    decision = (decision or "").lower().strip()
    if kind not in ("late", "early", "absent") or decision not in ("ok", "reject"):
        return RedirectResponse(url="/hr/dashboard", status_code=302)

    adj = (
        db.query(AttendanceAdjustment)
        .filter(AttendanceAdjustment.employee_id == emp_id, AttendanceAdjustment.day_date == d)
        .first()
    )
    if not adj:
        adj = AttendanceAdjustment(employee_id=emp_id, day_date=d)
        db.add(adj)

    excused = (decision == "reject")
    if kind == "late":
        adj.excuse_late = excused
    elif kind == "early":
        adj.excuse_early_leave = excused
    elif kind == "absent":
        adj.excuse_absence = excused

    adj.updated_by_user_id = getattr(u, "id", None)
    if note is not None:
        adj.note = (note or '').strip()[:255] or None
    db.add(adj)
    db.commit()
    # keep old behavior if next_url not provided
    if next_url and next_url.startswith('/'):
        return RedirectResponse(url=next_url, status_code=302)
    return RedirectResponse(url="/hr/dashboard", status_code=302)


def hr_employee_deactivate(emp_id: int, request: Request, db: Session = Depends(get_db)):
    u = get_current_hr_user(request, db)
    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Not found")
    emp.is_active = False
    db.add(emp)
    db.commit()
    return RedirectResponse(url=f"/hr/employees/{emp_id}", status_code=302)

@app.post("/hr/employees/{emp_id}/delete")
def hr_employee_delete(emp_id: int, request: Request, db: Session = Depends(get_db)):
    u = get_current_hr_user(request, db)

    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Not found")

    # Delete employee using raw SQL so ORM won't try to set employee_id = NULL
    db.execute(text("DELETE FROM employees WHERE id = :eid"), {"eid": emp_id})
    db.commit()

    return RedirectResponse(url="/hr/employees", status_code=302)


@app.get("/hr/log/{log_id}", response_class=HTMLResponse)
def hr_log_detail(request: Request, log_id: int, db: Session = Depends(get_db)):
    u = get_current_hr_user(request, db)
    log = db.get(AttendanceLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Not found")
    emp = db.get(Employee, log.employee_id)
    return templates.TemplateResponse(
        "hr_log_detail.html",
        {
            "request": request,
            "user": u,
            "log": log,
            "emp": emp,
        },
    )

@app.get("/hr/report", response_class=HTMLResponse)
def hr_report(request: Request, db: Session = Depends(get_db), date_str: str | None = None, month: str | None = None, emp_id: str | None = None):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    employees_all = db.query(Employee).order_by(Employee.employee_code.asc()).all()

    # Defaults
    if not date_str and not month:
        t = today_tz()
        month = f"{t.year:04d}-{t.month:02d}"

    # If emp_id is provided -> employee report (daily or monthly)
    emp_id_int: int | None = None
    if emp_id is not None:
        s = str(emp_id).strip()
        if s.isdigit():
            try:
                emp_id_int = int(s)
            except Exception:
                emp_id_int = None

    if emp_id_int:
        # daily takes precedence
        if date_str:
            try:
                d = date.fromisoformat(date_str.strip())
            except Exception:
                d = today_tz()
            settings = get_or_none_daily_settings(db, d)
            emp = db.get(Employee, emp_id_int)
            rows = []
            if emp:
                rows = [compute_day(db, emp, d, settings)]
            return templates.TemplateResponse(
                "hr_report.html",
                {
                    "request": request,
                    "today": today_tz().isoformat(),
                    "user": u,
                    "mode": "employee_daily",
                    "date": d,
                    "date_str": (date_str or d.isoformat()),
                    "month": "",
                    "emp_id": emp_id_int,
                    "employees": employees_all,
                    "rows": rows,
                    "totals": None,
                },
            )

        # monthly for employee
        try:
            y, m = (month or "").split("-")
            year, mon = int(y), int(m)
        except Exception:
            t = today_tz()
            year, mon = t.year, t.month
            month = f"{year:04d}-{mon:02d}"

        # iterate days of month
        first = date(year, mon, 1)
        if mon == 12:
            next_first = date(year + 1, 1, 1)
        else:
            next_first = date(year, mon + 1, 1)
        days = (next_first - first).days

        emp = db.get(Employee, emp_id_int)
        daily_rows = []
        t_today = today_tz()
        month_upto = t_today if (year == t_today.year and mon == t_today.month) else None
        if emp:
            for i in range(days):
                d = first + timedelta(days=i)
                if month_upto and d > month_upto:
                    break
                settings = get_or_none_daily_settings(db, d)
                daily_rows.append(compute_day(db, emp, d, settings))

        # payroll summary
        default_settings = db.get(DailySettings, today_tz())
        upto = today_tz() if (year == today_tz().year and mon == today_tz().month) else None
        summary = None
        if emp:
            summary, _breakdown = compute_month(db, emp, year, mon, default_settings, upto=upto)

        return templates.TemplateResponse(
            "hr_report.html",
            {
                "request": request,
                    "today": today_tz().isoformat(),
                "user": u,
                "mode": "employee_monthly",
                "date": None,
                "date_str": (date_str or ""),
                "month": f"{year:04d}-{mon:02d}",
                "emp_id": emp_id_int,
                "employees": employees_all,
                "rows": daily_rows,
                "summary": summary,
                "totals": None,
            },
        )

    # No emp_id -> monthly summary for ALL employees
    try:
        y, m = (month or "").split("-")
        year, mon = int(y), int(m)
    except Exception:
        t = today_tz()
        year, mon = t.year, t.month
        month = f"{year:04d}-{mon:02d}"

    first = date(year, mon, 1)
    if mon == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, mon + 1, 1)
    days_in_month = (next_first - first).days

    default_settings = db.get(DailySettings, today_tz())
    upto = today_tz() if (year == today_tz().year and mon == today_tz().month) else None

    rows = []
    totals = {
        "grand_total": 0.0,
        "salary_monthly": 0.0,
        "absent_deduction": 0.0,
        "late_deduction": 0.0,
        "early_leave_deduction": 0.0,
        "overtime_add": 0.0,
        "bonus_add": 0.0,
        "manual_adjustments_total": 0.0,
        "total_deductions": 0.0,
        "total_additions": 0.0,
        "adjustments_total": 0.0,
    }

    month_key = f"{year:04d}-{mon:02d}"
    batch = db.query(PayrollBatch).filter(PayrollBatch.month == month_key).first()
    rec_map = {}
    if batch and batch.status in ("APPROVED", "CLOSED"):
        recs = db.query(PayrollRecord).filter(PayrollRecord.batch_id == batch.id).all()
        rec_map = {r.employee_id: r for r in recs}

    for e in employees_all:
        present_days = 0
        absent_days = 0
        total_late = 0
        total_overtime = 0
        total_early_leave = 0
        late_days = 0
        total_overtime_raw = 0
        total_early_leave_raw = 0 
        for i in range(days_in_month):
            d = first + timedelta(days=i)
            if upto and d > upto:
                break
            settings = get_or_none_daily_settings(db, d)
            r = compute_day(db, e, d, settings)
            if r["status"] in ("PRESENT", "INCOMPLETE"):
                present_days += 1
            elif r["status"] == "ABSENT":
                absent_days += 1
            
            late_now = int(r.get("late") or 0)
            if late_now > 0:
                late_days += 1
            total_late += late_now
            total_early_leave += int(r.get("early_leave") or 0)
            total_early_leave_raw += int(r.get("raw_early_leave") or 0)
            total_overtime += int(r.get("overtime") or 0)
            total_overtime_raw += int(r.get("raw_overtime") or 0)
        
        summary, _breakdown = compute_month(db, e, year, mon, default_settings, upto=upto)

        row = {
            "emp": e,
            "present_days": present_days,
            "absent_days": absent_days,
            "late_minutes": total_late,
            "early_leave_minutes": total_early_leave,
            "overtime_minutes": total_overtime,
            "summary": summary,
            "late_days": late_days,
            "early_leave_raw_minutes": total_early_leave_raw,
            "overtime_raw_minutes": total_overtime_raw,
        }
        rows.append(row)

        # accumulate totals
        try:
            totals["grand_total"] += float(summary.get("total") or 0)
        except Exception:
            pass
        for k in (
            "salary_monthly",
            "absent_deduction",
            "late_deduction",
            "early_leave_deduction",
            "overtime_add",
            "bonus_add",
            "manual_adjustments_total",
            "total_deductions",
            "total_additions",
            "adjustments_total",
        ):
            try:
                totals[k] += float(summary.get(k) or 0)
            except Exception:
                pass

    # rounding for display
    for k in list(totals.keys()):
        totals[k] = round(float(totals[k] or 0.0), 3)

    return templates.TemplateResponse(
        "hr_report.html",
        {
            "request": request,
                    "today": today_tz().isoformat(),
            "user": u,
            "mode": "monthly_all",
            "date": None,
            "date_str": (date_str or ""),
            "month": f"{year:04d}-{mon:02d}",
            "emp_id": 0,
            "employees": employees_all,
            "rows": rows,
            "totals": totals,
            "batch": batch,
        },
    )




# -------------------------
# HR: Commit / Rebuild review items (Write-mode)
# -------------------------

@app.post("/hr/commit/month")
def hr_commit_month(
    request: Request,
    month: str = Form(...),
    emp_id: int | None = Form(None),
    next_url: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Generate/refresh DB-backed review items (AttendanceAdjustment + early leave segments) for a month.

    Reports are read-only; HR must explicitly commit to create/update pending items.
    """
    try:
        _u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    m = (month or "").strip()
    try:
        y, mo = m.split("-")
        year, mon = int(y), int(mo)
        first = date(year, mon, 1)
    except Exception:
        return RedirectResponse(url=(next_url or "/hr/report"), status_code=302)

    if mon == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, mon + 1, 1)

    t_today = today_tz()
    upto = t_today if (year == t_today.year and mon == t_today.month) else (next_first - timedelta(days=1))

    employees = []
    if emp_id:
        emp = db.get(Employee, int(emp_id))
        if emp:
            employees = [emp]
    else:
        employees = db.query(Employee).order_by(Employee.employee_code.asc()).all()

    d = first
    while d <= upto:
        settings = get_or_none_daily_settings(db, d)
        # if the day isn't configured, skip (treat as not-working day)
        if settings and (not settings.is_holiday):
            for emp in employees:
                compute_day(db, emp, d, settings, write_db=True)
        d = d + timedelta(days=1)

    return RedirectResponse(url=(next_url or f"/hr/report?month={m}" + (f"&emp_id={emp_id}" if emp_id else "")), status_code=302)


@app.post("/hr/commit/day")
def hr_commit_day(
    request: Request,
    emp_id: int = Form(...),
    date_str: str = Form(...),
    next_url: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Generate/refresh DB-backed review items for a specific employee day."""
    try:
        _u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    try:
        d = date.fromisoformat((date_str or "").strip())
    except Exception:
        return RedirectResponse(url=(next_url or "/hr/report"), status_code=302)

    emp = db.get(Employee, int(emp_id))
    if not emp:
        return RedirectResponse(url=(next_url or "/hr/report"), status_code=302)

    settings = get_or_none_daily_settings(db, d)
    if settings and (not settings.is_holiday):
        compute_day(db, emp, d, settings, write_db=True)

    return RedirectResponse(url=(next_url or f"/hr/report?emp_id={emp.id}&date_str={d.isoformat()}"), status_code=302)



# -------------------------
# HR: Review (Late / Early Leave / Absence) approvals
# -------------------------

def _get_or_create_adj(db: Session, emp_id: int, d: date, user_id: int | None):
    adj = (
        db.query(AttendanceAdjustment)
        .filter(AttendanceAdjustment.employee_id == emp_id, AttendanceAdjustment.day_date == d)
        .first()
    )
    if not adj:
        adj = AttendanceAdjustment(employee_id=emp_id, day_date=d, updated_by_user_id=user_id)
        db.add(adj)
        db.commit()
        db.refresh(adj)
    return adj


def _parse_optional_minutes(v: str | None):
    s = (v or "").strip()
    if s == "":
        return None
    try:
        return max(0, int(float(s)))
    except Exception:
        return None


def _validate_day_logs_sequence(logs):
    valid_logs = [x for x in logs if getattr(x, "is_valid", True)]
    valid_logs = sorted(valid_logs, key=lambda x: (x.server_timestamp or datetime.min, x.id or 0))

    last_action = None
    for lg in valid_logs:
        action = (lg.action or "").upper()
        if action not in ("IN", "OUT"):
            return False, "نوع الحركة غير صالح"
        if last_action == action:
            return False, "لا يجوز وجود حركتين متتاليتين من نفس النوع"
        last_action = action
    return True, None

@app.post("/hr/log/save")
def hr_log_save(
    request: Request,
    db: Session = Depends(get_db),
    emp_id: int = Form(...),
    date_str: str = Form(...),
    log_id: str | None = Form(None),
    action: str = Form(...),
    time_str: str = Form(...),
    is_valid: str | None = Form(None),
    note: str | None = Form(None),
    next_url: str | None = Form(None),
):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    try:
        d = date.fromisoformat((date_str or "").strip())
    except Exception:
        raise HTTPException(status_code=400, detail="تاريخ غير صالح")

    action = (action or "").strip().upper()
    if action not in ("IN", "OUT"):
        raise HTTPException(status_code=400, detail="نوع الحركة غير صالح")

    try:
        hh, mm = [int(x) for x in (time_str or "").split(":")[:2]]
        new_ts = datetime.combine(d, time(hour=hh, minute=mm))
    except Exception:
        raise HTTPException(status_code=400, detail="وقت غير صالح")

    log = None
    if (log_id or "").strip():
        log = db.get(AttendanceLog, int(log_id))
        if not log:
            raise HTTPException(status_code=404, detail="السجل غير موجود")
        if int(log.employee_id) != int(emp_id):
            raise HTTPException(status_code=400, detail="السجل لا يخص الموظف المحدد")
    else:
        log = AttendanceLog(
            employee_id=emp_id,
            day_date=d,
            action=action,
            server_timestamp=new_ts,
            is_valid=True,
        )
        db.add(log)
        db.flush()

    old_action = log.action
    old_ts = log.server_timestamp
    old_valid = log.is_valid

    log.action = action
    log.server_timestamp = new_ts
    log.day_date = d
    log.is_valid = bool(is_valid)

    db.flush()

    day_logs = (
        db.query(AttendanceLog)
        .filter(
            AttendanceLog.employee_id == emp_id,
            AttendanceLog.day_date == d,
        )
        .all()
    )

    ok, err = _validate_day_logs_sequence(day_logs)
    if not ok:
        log.action = old_action
        log.server_timestamp = old_ts
        log.is_valid = old_valid
        db.rollback()
        raise HTTPException(status_code=400, detail=err)

    adj = (
        db.query(AttendanceAdjustment)
        .filter(
            AttendanceAdjustment.employee_id == emp_id,
            AttendanceAdjustment.day_date == d,
        )
        .first()
    )
    if not adj:
        adj = AttendanceAdjustment(
            employee_id=emp_id,
            day_date=d,
            updated_by_user_id=getattr(u, "id", None),
        )
        db.add(adj)

    old_note = (adj.note or "").strip()
    action_txt = "تعديل سجل" if (log_id or "").strip() else "إضافة سجل"
    extra = f"{action_txt}: {action} {new_ts.strftime('%H:%M')}"
    note_clean = (note or "").strip()
    if note_clean:
        extra += f" | {note_clean[:120]}"

    adj.note = (old_note + " | " + extra).strip(" |")[:255]
    adj.updated_by_user_id = getattr(u, "id", None)

    db.commit()

    return RedirectResponse(
        url=(next_url or f"/hr/report?emp_id={emp_id}&date_str={d.isoformat()}"),
        status_code=302,
    )
@app.post("/hr/report/manual-save")
def hr_report_manual_save(
    request: Request,
    db: Session = Depends(get_db),
    emp_id: int = Form(...),
    date_str: str = Form(...),
    late_minutes: str | None = Form(None),
    early_leave_minutes: str | None = Form(None),
    overtime_minutes: str | None = Form(None),
    absence_status: str | None = Form(None),
    note: str | None = Form(None),
    clear_manual: str | None = Form(None),
    next_url: str | None = Form(None),
):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    try:
        d = date.fromisoformat((date_str or "").strip())
    except Exception:
        return RedirectResponse(url=(next_url or "/hr/report"), status_code=302)

    adj = _get_or_create_adj(db, emp_id, d, getattr(u, "id", None))
    if clear_manual:
        adj.manual_late_minutes = None
        adj.manual_early_leave_minutes = None
        adj.manual_overtime_minutes = None
        adj.manual_absence_status = None
    else:
        abs_clean = (absence_status or "").strip().upper()

        parsed_late = _parse_optional_minutes(late_minutes)
        parsed_early = _parse_optional_minutes(early_leave_minutes)
        parsed_ot = _parse_optional_minutes(overtime_minutes)

        # Convenience mode from HR report page:
        # "دوام إلى نهاية الدوام" = employee is present and has no early leave,
        # while still allowing HR to set late/overtime manually.
        if abs_clean == "PRESENT_TO_END":
            adj.manual_absence_status = "PRESENT"
            adj.manual_early_leave_minutes = 0
        else:
            adj.manual_early_leave_minutes = parsed_early
            if abs_clean in ("PRESENT", "ABSENT", "EXCUSED"):
                adj.manual_absence_status = abs_clean
            else:
                adj.manual_absence_status = None

        adj.manual_late_minutes = parsed_late
        adj.manual_overtime_minutes = parsed_ot

    note_clean = (note or "").strip()
    if note_clean:
        old_note = (adj.note or "").strip()
        extra = f"تعديل يدوي من التقرير: {note_clean}"
        adj.note = (old_note + " | " + extra).strip(" |")[:255]

    adj.updated_by_user_id = getattr(u, "id", None)
    db.add(adj)
    db.commit()

    return RedirectResponse(url=(next_url or f"/hr/report?emp_id={emp_id}&date_str={d.isoformat()}"), status_code=302)
@app.get("/hr/review", response_class=HTMLResponse)
def hr_review_page(
    request: Request,
    db: Session = Depends(get_db),
    date_str: str | None = None,
    kind: str | None = None,
):
    """
    Reviews page: show ALL pending items (late / early leave / absence) across dates.
    If date_str is provided, filter to that day only.

    IMPORTANT:
    - Payroll/report pages can show "pending" even if there is NO AttendanceAdjustment row yet
      (decision_* == None). The review page should still list these items.
    - We do NOT create/write anything here (read-only). Writing happens via /hr/commit/* or /hr/review/decide.
    """
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    d_filter: date | None = None
    if date_str:
        try:
            d_filter = date.fromisoformat(date_str.strip())
        except Exception:
            d_filter = None

    kind_clean = (kind or "").strip().lower()
    if kind_clean not in ("late", "early_leave", "absence", "overtime", ""):
        kind_clean = ""

    # Default window: current month start -> today (unless a specific day is requested)
    t = today_tz()
    month_start = date(t.year, t.month, 1)
    if d_filter:
        days = [d_filter]
    else:
        days = [month_start + timedelta(days=i) for i in range((t - month_start).days + 1)]

    employees = (
        db.query(Employee)
        .filter(Employee.is_active == True)
        .order_by(Employee.employee_code.asc())
        .all()
    )
    
    late_rows: list[dict] = []
    absence_rows: list[dict] = []
    early_rows: list[dict] = []
    overtime_rows: list[dict] = []
    # Late + Absence are decided per-day (AttendanceAdjustment). If no adjustment row exists yet,
    # treat it as PENDING so HR can see it here (matches payroll "pending" behavior).
    for emp in employees:
        for d in days:
            settings = get_or_none_daily_settings(db, d)
            r = compute_day(db, emp, d, settings, write_db=False)
            # ✅ Skip days with no schedule configured (prevents fake ABSENT on non-working days)
            if not r.get("sched_start") and not r.get("sched_end"):
                  continue
            adj = r.get("adj")
            review_note_parts = [
                f"الدوام الفعلي: {r.get('work_duration') or '00:00'}",
                f"المغادرات: {int(r.get('external_break_count') or 0)} مرة / {int(r.get('external_break_min') or 0)} د",
                f"بعد نهاية الدوام: {int(r.get('post_shift_extra_min') or 0)} د",
            ]
            if int(r.get("post_shift_extra_min") or 0) > 0 or int(r.get("raw_overtime") or 0) > 0:
                review_note_parts.append("يوجد وقت زائد قابل للتسوية من صفحة الإضافي")
            if adj and getattr(adj, "note", None):
                review_note_parts.append(f"ملاحظة HR: {adj.note}")
            review_note = " | ".join(review_note_parts)
            # EARLY LEAVE (pending) - show from computed raw minutes (no DB segments needed)
            raw_early = int(r.get("raw_early_leave") or 0)
            early_decision = (r.get("decision_early_leave") or "PENDING").upper()
            early_excused = bool(getattr(adj, "excuse_early_leave", False)) if adj else False
            
            if raw_early > 0 and early_decision == "PENDING" and (not early_excused):
               early_rows.append(
               {
                  "emp": emp,
                  "date": d.isoformat(),
                  "work_duration": r.get("work_duration"),
                  "work_minutes": int(r.get("work_minutes") or 0),
                  "official_minutes": int((getattr(settings, "official_work_minutes", 480) if settings else 480) or 480),
                  "minutes": raw_early,
                  "note": review_note,
                  "in_log": r.get("first_in_log"),
                  "out_log": r.get("last_out_log"),
               }
               )
            # LATE (pending)
            raw_late = int(r.get("raw_late") or 0)
            late_decision = (r.get("decision_late") or "PENDING").upper()
            late_excused = bool(getattr(adj, "excuse_late", False)) if adj else False
            if raw_late > 0 and late_decision == "PENDING" and (not late_excused):
                late_rows.append(
                    {
                    "emp": emp,
                    "date": d.isoformat(),
                    "sched_start": r.get("sched_start"),
                    "first_in": r.get("first_in"),
                    "minutes": raw_late,
                    "note": review_note,
                    "in_log": r.get("first_in_log"),
                    "out_log": r.get("last_out_log"),
            }
            )
            
            # ABSENCE (pending)
            raw_status = (r.get("raw_status") or "").upper()
            absence_decision = (r.get("decision_absence") or "PENDING").upper()
            absence_excused = bool(getattr(adj, "excuse_absence", False)) if adj else False
            if raw_status == "ABSENT" and absence_decision == "PENDING" and (not absence_excused):
               absence_rows.append(
                {
                 "emp": emp,
                 "date": d.isoformat(),
                 "sched_start": r.get("sched_start"),
                 "sched_end": r.get("sched_end"),
                 "note": review_note,
                 "in_log": r.get("first_in_log"),
                 "out_log": r.get("last_out_log"),
                 }
                   )
            # OVERTIME (pending)
            raw_ot = int(r.get("overtime_raw_min") or r.get("raw_overtime") or 0)
            ot_decision = (r.get("decision_overtime") or "PENDING").upper()
            ot_excused = bool(getattr(adj, "excuse_overtime", False)) if adj else False
            if raw_ot > 0 and ot_decision == "PENDING" and (not ot_excused):
                overtime_rows.append(
                    {
                        "emp": emp,
                        "date": d.isoformat(),
                        "work_duration": r.get("work_duration"),
                        "work_minutes": int(r.get("work_minutes") or 0),
                        "official_minutes": int((getattr(settings, "official_work_minutes", 480) if settings else 480) or 480),
                        "minutes": raw_ot,
                        "note": review_note,
                        "in_log": r.get("first_in_log"),
                        "out_log": r.get("last_out_log"),
                        }
    )
    # Sort: newest day first, then employee_code
    try:
        late_rows.sort(
            key=lambda x: (x.get("date") or "", getattr(x["emp"], "employee_code", "")),
            reverse=True,
        )
        absence_rows.sort(
            key=lambda x: (x.get("date") or "", getattr(x["emp"], "employee_code", "")),
            reverse=True,
        )
    except Exception:
        pass

    
    title = "مراجعة المخالفات"
    if kind_clean == "late":
        title = "مراجعة التأخير"
    elif kind_clean == "early_leave":
        title = "مراجعة المغادرة"
    elif kind_clean == "absence":
        title = "مراجعة الغياب"
    elif kind_clean == "overtime":
        title = "مراجعة الإضافي"
    if kind_clean == "late":
        early_rows = []
        absence_rows = []
    elif kind_clean == "early_leave":
        late_rows = []
        absence_rows = []
    elif kind_clean == "absence":
        late_rows = []
        early_rows = []
    elif kind_clean == "overtime":
        late_rows = []
        early_rows = []
        absence_rows = []
    overtime_rows.sort(
    key=lambda x: (x.get("date") or "", getattr(x["emp"], "employee_code", "")),
    reverse=True,
)
   
    return templates.TemplateResponse(
        "hr_review.html",
        {
            "request": request,
            "nav": _hr_nav_counts(db),
            "user": u,
            "date": (d_filter.isoformat() if d_filter else ""),
            "date_str": (d_filter.isoformat() if d_filter else ""),
            "kind": kind_clean,
            "title": title,
            "late_rows": late_rows,
            "early_rows": early_rows,
            "absence_rows": absence_rows,
            "month": f"{today_tz().year:04d}-{today_tz().month:02d}",
            "overtime_rows": overtime_rows,
        },
    )
@app.post("/hr/review/decide")
def hr_review_decide(
    request: Request,
    db: Session = Depends(get_db),
    kind: str = Form(...),
    date_str: str = Form(...),
    emp_id: int = Form(...),
    segment_id: str = Form(None),
    decision: str = Form(...),
    note: str = Form(None),
    compensate: str | None = Form(None),
    compensate_target: str | None = Form(None),
    back: str = Form(None),
):
    try:
        u = get_current_hr_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/hr/login", status_code=302)

    try:
        d = date.fromisoformat(date_str.strip())
    except Exception:
        d = today_tz()

    kind = (kind or "").strip().lower()
    decision = (decision or "").strip().upper()
    if decision not in ("APPROVED", "REJECTED", "EXCUSED"):
        decision = "REJECTED"

    stored_decision = "REJECTED" if decision == "EXCUSED" else decision
    # Early leave is decided per-segment (OUT->IN or OUT->End)
    segment_id_clean = (segment_id or "").strip()
    if kind == "early_leave" and segment_id_clean:
        seg = db.query(AttendanceEarlyLeaveSegment).filter(
            AttendanceEarlyLeaveSegment.id == int(segment_id_clean)
        ).first()
        if seg:
            seg.decision = "APPROVED" if decision == "APPROVED" else "REJECTED"
            seg.note = (note or None)
            seg.updated_by_user_id = u.id
            db.commit()

        if back and str(back).startswith("/"):
            return RedirectResponse(url=str(back), status_code=302)

        return RedirectResponse(url=f"/hr/review?date_str={d.isoformat()}&kind=early_leave", status_code=302)

    adj = _get_or_create_adj(db, emp_id, d, u.id)

    note_clean = (note or "").strip()[:255]

    if kind == "late":
       adj.decision_late = stored_decision
       adj.excuse_late = (decision == "EXCUSED")
       if decision == "EXCUSED":
           adj.compensate_late = False
    
    elif kind == "early_leave":
       adj.decision_early_leave = stored_decision
       adj.excuse_early_leave = (decision == "EXCUSED")
       if decision == "EXCUSED":
           adj.compensate_early_leave = False

    elif kind == "absence":
       adj.decision_absence = stored_decision
       adj.excuse_absence = (decision == "EXCUSED")

    elif kind == "overtime":
       adj.decision_overtime = stored_decision
       adj.excuse_overtime = (decision == "EXCUSED")

       # compensation source lives here, not in late/early review
       adj.compensate_late = False
       adj.compensate_early_leave = False

       target = (compensate_target or "").strip().lower()
       if stored_decision == "APPROVED":
           if target == "late":
               adj.compensate_late = True
           elif target == "early_leave":
               adj.compensate_early_leave = True
    db.add(adj)
    db.commit()

    if back and str(back).startswith("/"):
        return RedirectResponse(url=str(back), status_code=302)

    return RedirectResponse(url=f"/hr/review?kind={kind}&date_str={d.isoformat()}", status_code=302)

from sqlalchemy import (
    Text,
    String,
    Integer,
    Boolean,
    DateTime,
    Date,
    Time,
    Enum,
    Float,
    ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Column, Integer, Date, DateTime, Enum, DECIMAL, Float, String, Text, UniqueConstraint
from datetime import datetime
from db import Base


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    national_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    salary_monthly: Mapped[float | None] = mapped_column(Float, nullable=True)
    work_start: Mapped[Time | None] = mapped_column(Time, nullable=True)
    work_end: Mapped[Time | None] = mapped_column(Time, nullable=True)
    grace_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    profile_photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allowed_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    social_security_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    logs = relationship("AttendanceLog", back_populates="employee")




class AttendanceLog(Base):
    __tablename__ = "attendance_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)

    employee = relationship("Employee", back_populates="logs")

    day_date = Column(Date, nullable=False)  # ✅ لازم تكون موجودة

    action = Column(Enum("IN", "OUT", name="attendance_action_enum"), nullable=False)

    server_timestamp = Column(DateTime, nullable=False, default=datetime.now)  # ✅

    lat = Column(DECIMAL(10, 7), nullable=True)
    lng = Column(DECIMAL(10, 7), nullable=True)
    accuracy_m = Column(Float, nullable=True)

    video_path = Column(String(255), nullable=True)

    area_name = Column(String(100), nullable=True)
    region_name = Column(String(100), nullable=True)

    user_agent = Column(String(255), nullable=True)
    ip = Column(String(45), nullable=True)

    # If an employee retries the same action because the client didn't receive a success response,
    # we mark the older record as invalid and ignore it in reports/calculations.
    is_valid = Column(Boolean, nullable=False, default=True)
    invalid_reason = Column(String(120), nullable=True)
    client_request_id = Column(String(60), nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(Enum("HR", "MANAGER", "ADMIN", name="user_role_enum"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    profile_photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    daily_settings = relationship("DailySettings", back_populates="creator")


class DailySettings(Base):
    __tablename__ = "daily_settings"

    date: Mapped[Date] = mapped_column(Date, primary_key=True)
    is_holiday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    work_start: Mapped[Time] = mapped_column(Time, nullable=False)
    work_end: Mapped[Time] = mapped_column(Time, nullable=False)
    grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Official work duration for the day (minutes). Default 8 hours = 480
    official_work_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=480)
    # Extra windows for payroll rules
    early_leave_grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    overtime_grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    overtime_min_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    late_penalty_percent_per_hour: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    overtime_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.5)
    bonus_perfect_day: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    profile_photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    creator = relationship("User", back_populates="daily_settings")


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("employees.id"), nullable=False)
    category: Mapped[str] = mapped_column(Enum("ISSUE", "SUGGESTION", "INQUIRY", name="ticket_category_enum"), nullable=False, default="ISSUE")
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(Enum("OPEN", "IN_PROGRESS", "CLOSED", name="ticket_status_enum"), nullable=False, default="OPEN")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    employee = relationship("Employee")



class AttendanceAdjustment(Base):
    __tablename__ = "attendance_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    day_date: Mapped[Date] = mapped_column(Date, nullable=False, index=True)

    excuse_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excuse_absence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # HR can choose to compensate late/early_leave using available overtime minutes in the same day
    compensate_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    compensate_early_leave: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Overtime review
    excuse_overtime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decision_overtime: Mapped[str] = mapped_column(Enum('PENDING','APPROVED','REJECTED', name='overtime_decision_enum'), nullable=False, default='PENDING')
    decision_late: Mapped[str] = mapped_column(Enum('PENDING','APPROVED','REJECTED', name="late_decision_enum"), nullable=False, default='PENDING')
    decision_early_leave: Mapped[str] = mapped_column(Enum('PENDING','APPROVED','REJECTED', name="early_leave_decision_enum"), nullable=False, default='PENDING')
    decision_absence: Mapped[str] = mapped_column(Enum('PENDING','APPROVED','REJECTED', name="absence_decision_enum"), nullable=False, default='PENDING')
    excuse_early_leave: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manual_late_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_early_leave_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_overtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_absence_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # PRESENT / ABSENT / EXCUSED
    manual_day_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)  # AUTO / PRESENT / PRESENT_TO_END / ABSENT / EXCUSED
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    employee = relationship("Employee")
    updated_by = relationship("User")


class PayrollAdjustment(Base):
    __tablename__ = "payroll_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    # Store month as 'YYYY-MM' to keep it simple and fast for payroll summaries
    month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # negative = deduction
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    employee = relationship("Employee")
    created_by = relationship("User")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("employees.id"), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    direction: Mapped[str] = mapped_column(
        Enum(
            "EMP_TO_HR",
            "HR_TO_EMP",
            "MANAGER_TO_HR",
            "HR_TO_MANAGER",
            "MANAGER_TO_EMP",
            name="message_direction_enum",
        ),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    employee = relationship("Employee")
    manager = relationship("User")

class EmployeeNote(Base):
    """ملاحظات من HR/ADMIN للموظف (اختياري: تظهر للموظف)."""

    __tablename__ = "employee_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    visible_to_employee: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    employee = relationship("Employee")
    created_by = relationship("User")


class SupportTicketReply(Base):
    """ردود على تذاكر الدعم (EMP <-> HR)."""

    __tablename__ = "support_ticket_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("support_tickets.id"), nullable=False, index=True)
    sender: Mapped[str] = mapped_column(Enum("EMP", "HR", name="sender_type_enum"), nullable=False)
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    ticket = relationship("SupportTicket")


# -------------------------
# Payroll Batches / Records (Monthly closing)
# -------------------------


class PayrollBatch(Base):
    """دفعة رواتب شهرية (Batch) لتثبيت الحسابات ثم اعتمادها وإغلاقها."""

    __tablename__ = "payroll_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 'YYYY-MM'
    month: Mapped[str] = mapped_column(String(7), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(Enum("DRAFT", "APPROVED", "CLOSED", name="request_status_enum"), nullable=False, default="DRAFT")

    created_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    closed_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    approved_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    records = relationship("PayrollRecord", back_populates="batch", cascade="all, delete-orphan")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    approved_by = relationship("User", foreign_keys=[approved_by_user_id])
    closed_by = relationship("User", foreign_keys=[closed_by_user_id])


class PayrollRecord(Base):
    """سجل راتب موظف داخل دفعة شهرية (Snapshot)."""

    __tablename__ = "payroll_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("payroll_batches.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("employees.id"), nullable=False, index=True)

    # Snapshot fields (denormalized for stable yearly reporting)
    salary_monthly: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    days_present: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    days_absent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    late_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    early_leave_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overtime_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    absent_deduction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    late_deduction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    early_leave_deduction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    manual_adjustments_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    overtime_add: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    bonus_add: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    total_deductions: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_additions: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    adjustments_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    batch = relationship("PayrollBatch", back_populates="records")
    employee = relationship("Employee")

class WorkDocumentation(Base):
    __tablename__ = "work_documentations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    day_date = Column(Date, nullable=False, index=True)
    server_timestamp = Column(DateTime, nullable=False, default=datetime.now)

    lat = Column(DECIMAL(10, 7), nullable=True)
    lng = Column(DECIMAL(10, 7), nullable=True)
    accuracy_m = Column(Float, nullable=True)

    video_path = Column(String(255), nullable=True)

    user_agent = Column(String(255), nullable=True)
    ip = Column(String(45), nullable=True)

    client_request_id = Column(String(60), nullable=True)

    employee = relationship("Employee")
class AttendanceEarlyLeaveSegment(Base):
    __tablename__ = "attendance_early_leave_segments"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    day_date = Column(Date, nullable=False, index=True)

    out_ts = Column(DateTime, nullable=False)
    in_ts = Column(DateTime, nullable=True)
    end_ts = Column(DateTime, nullable=False)  # effective end used for minutes (clamped to sched_end)

    minutes = Column(Integer, nullable=False, default=0)

    decision = Column(String(20), nullable=False, default="PENDING")  # PENDING/APPROVED/REJECTED
    note = Column(String(255), nullable=True)

    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = relationship("Employee", backref="early_leave_segments")

    __table_args__ = (
        UniqueConstraint("employee_id", "day_date", "out_ts", "end_ts", name="uq_els_emp_day_out_end"),
    )
class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("employees.id"), nullable=False, index=True)

    workshop_name: Mapped[str] = mapped_column(String(150), nullable=False)
    location: Mapped[str | None] = mapped_column(String(150), nullable=True)
    invoice_date: Mapped[Date] = mapped_column(Date, nullable=False)

    total_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    image_total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(
        Enum("DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", name="invoice_status_enum"),
        nullable=False,
        default="DRAFT",
    )

    hr_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    submitted_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    employee = relationship("Employee")
    reviewed_by = relationship("User")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    images = relationship("InvoiceImage", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)

    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    invoice = relationship("Invoice", back_populates="items")


class InvoiceImage(Base):
    __tablename__ = "invoice_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)

    image_path: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    invoice = relationship("Invoice", back_populates="images")

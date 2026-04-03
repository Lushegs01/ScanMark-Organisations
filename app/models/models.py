from datetime import datetime, timezone
import uuid
from app import db
from flask_login import UserMixin
import bcrypt


def generate_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ─── User & Organisation ──────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    account_type = db.Column(db.String(20), nullable=False)  # 'corporate' | 'events'
    onboarding_complete = db.Column(db.Boolean, default=False)
    email_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_login = db.Column(db.DateTime)

    # Relationships
    organisation = db.relationship('Organisation', back_populates='owner', uselist=False, foreign_keys='Organisation.owner_id')
    team_memberships = db.relationship('TeamMember', back_populates='user', foreign_keys='TeamMember.user_id')
    password_resets = db.relationship('PasswordReset', back_populates='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def __repr__(self):
        return f'<User {self.email}>'


class Organisation(db.Model):
    __tablename__ = 'organisations'

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    owner_id = db.Column(db.String(36), db.ForeignKey('users.id'), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    account_type = db.Column(db.String(20), nullable=False)  # 'corporate' | 'events'

    # Corporate-specific
    industry = db.Column(db.String(100))
    team_size = db.Column(db.String(20))
    use_case = db.Column(db.String(50))  # 'shifts' | 'training' | 'both'

    # Events-specific
    event_type = db.Column(db.String(100))
    typical_attendees = db.Column(db.String(20))

    # Billing
    plan = db.Column(db.String(20), default='free')  # 'free' | 'pro' | 'team'
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))
    subscription_status = db.Column(db.String(50), default='inactive')
    plan_expires_at = db.Column(db.DateTime)

    # SMTP settings
    smtp_host = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer, default=587)
    smtp_user = db.Column(db.String(255))
    smtp_password_enc = db.Column(db.String(512))
    smtp_use_tls = db.Column(db.Boolean, default=True)
    smtp_from_name = db.Column(db.String(255))
    smtp_from_email = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    owner = db.relationship('User', back_populates='organisation', foreign_keys=[owner_id])
    team_members = db.relationship('TeamMember', back_populates='organisation', lazy='dynamic')
    sessions = db.relationship('Session', back_populates='organisation', lazy='dynamic')
    events = db.relationship('Event', back_populates='organisation', lazy='dynamic')

    def sessions_this_month(self):
        now = utcnow()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.sessions.filter(Session.created_at >= start).count()

    def events_this_month(self):
        now = utcnow()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.events.filter(Event.created_at >= start).count()

    def can_create_session(self):
        if self.plan in ('pro', 'team'):
            return True, None
        count = self.sessions_this_month()
        if count >= 3:
            return False, 'session_limit'
        return True, None

    def can_create_event(self):
        if self.plan in ('pro', 'team'):
            return True, None
        count = self.events_this_month()
        if count >= 3:
            return False, 'event_limit'
        return True, None

    def can_export_pdf(self):
        if self.plan in ('pro', 'team'):
            return True, None
        return False, 'pdf_export'

    def can_send_emails(self):
        if self.plan in ('pro', 'team'):
            return True, None
        return False, 'email_dispatch'

    def max_attendees(self):
        if self.plan in ('pro', 'team'):
            return None  # unlimited
        return 50

    def __repr__(self):
        return f'<Organisation {self.name}>'


class TeamMember(db.Model):
    __tablename__ = 'team_members'

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    organisation_id = db.Column(db.String(36), db.ForeignKey('organisations.id'), nullable=False)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)
    email = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='member')  # 'owner' | 'admin' | 'member'
    invite_token = db.Column(db.String(255), unique=True)
    invite_accepted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    organisation = db.relationship('Organisation', back_populates='team_members')
    user = db.relationship('User', back_populates='team_memberships', foreign_keys=[user_id])


# ─── Authentication ───────────────────────────────────────────────────────────

class PasswordReset(db.Model):
    __tablename__ = 'password_resets'

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    user = db.relationship('User', back_populates='password_resets')

    def is_valid(self):
        return not self.used and self.expires_at > utcnow()


# ─── Corporate: Sessions ──────────────────────────────────────────────────────

class Session(db.Model):
    __tablename__ = 'sessions'

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    organisation_id = db.Column(db.String(36), db.ForeignKey('organisations.id'), nullable=False)
    session_type = db.Column(db.String(20), nullable=False)  # 'shift' | 'training'
    name = db.Column(db.String(255), nullable=False)
    department = db.Column(db.String(255))      # shifts
    facilitator = db.Column(db.String(255))     # training
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time)               # shifts
    duration_minutes = db.Column(db.Integer)    # training
    is_mandatory = db.Column(db.Boolean, default=False)
    late_threshold_minutes = db.Column(db.Integer, default=5)
    open_attendance = db.Column(db.Boolean, default=True)
    qr_token = db.Column(db.String(255), unique=True, default=generate_uuid)
    status = db.Column(db.String(20), default='upcoming')  # 'upcoming'|'active'|'completed'
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    organisation = db.relationship('Organisation', back_populates='sessions')
    expected_attendees = db.relationship('ExpectedAttendee', back_populates='session', lazy='dynamic', cascade='all, delete-orphan')
    checkins = db.relationship('CheckIn', back_populates='session', lazy='dynamic', cascade='all, delete-orphan')

    def get_status(self):
        from datetime import date, time
        today = date.today()
        now = datetime.now().time()
        if self.date > today:
            return 'upcoming'
        elif self.date < today:
            return 'completed'
        else:
            if self.start_time and now < self.start_time:
                return 'upcoming'
            if self.end_time and now > self.end_time:
                return 'completed'
            return 'active'

    def attendance_rate(self):
        expected = self.expected_attendees.count()
        if expected == 0:
            return None
        checked = self.checkins.count()
        return round((checked / expected) * 100)


class ExpectedAttendee(db.Model):
    __tablename__ = 'expected_attendees'

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    session_id = db.Column(db.String(36), db.ForeignKey('sessions.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    employee_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=utcnow)

    session = db.relationship('Session', back_populates='expected_attendees')


class CheckIn(db.Model):
    __tablename__ = 'checkins'

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    session_id = db.Column(db.String(36), db.ForeignKey('sessions.id'), nullable=True)
    event_id = db.Column(db.String(36), db.ForeignKey('events.id'), nullable=True)
    attendee_id = db.Column(db.String(36), db.ForeignKey('event_attendees.id'), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    employee_id = db.Column(db.String(100))
    email = db.Column(db.String(255))
    checkin_time = db.Column(db.DateTime, default=utcnow)
    is_late = db.Column(db.Boolean, default=False)
    is_manual = db.Column(db.Boolean, default=False)
    is_walkin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    session = db.relationship('Session', back_populates='checkins')
    event = db.relationship('Event', back_populates='checkins')
    attendee = db.relationship('EventAttendee', back_populates='checkin')


# ─── Events ───────────────────────────────────────────────────────────────────

class Event(db.Model):
    __tablename__ = 'events'

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    organisation_id = db.Column(db.String(36), db.ForeignKey('organisations.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=False)
    venue = db.Column(db.String(255))
    start_time = db.Column(db.Time, nullable=False)
    max_capacity = db.Column(db.Integer)
    capacity_enforcement = db.Column(db.Boolean, default=True)
    qr_token = db.Column(db.String(255), unique=True, default=generate_uuid)
    status = db.Column(db.String(20), default='upcoming')
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    organisation = db.relationship('Organisation', back_populates='events')
    attendees = db.relationship('EventAttendee', back_populates='event', lazy='dynamic', cascade='all, delete-orphan')
    checkins = db.relationship('CheckIn', back_populates='event', lazy='dynamic', cascade='all, delete-orphan')

    def checked_in_count(self):
        return self.checkins.count()

    def registered_count(self):
        return self.attendees.count()

    def attendance_rate(self):
        total = self.registered_count()
        if total == 0:
            return 0
        return round((self.checked_in_count() / total) * 100)

    def capacity_percent(self):
        if not self.max_capacity:
            return 0
        return round((self.checked_in_count() / self.max_capacity) * 100)

    def get_status(self):
        from datetime import date
        today = date.today()
        now = datetime.now().time()
        if self.date > today:
            return 'upcoming'
        elif self.date < today:
            return 'completed'
        else:
            if self.start_time and now < self.start_time:
                return 'upcoming'
            return 'active'


class EventAttendee(db.Model):
    __tablename__ = 'event_attendees'

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    event_id = db.Column(db.String(36), db.ForeignKey('events.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255))
    ticket_ref = db.Column(db.String(100))
    qr_token = db.Column(db.String(255), unique=True, default=generate_uuid)
    qr_sent = db.Column(db.Boolean, default=False)
    is_walkin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    event = db.relationship('Event', back_populates='attendees')
    checkin = db.relationship('CheckIn', back_populates='attendee', uselist=False)

    def is_checked_in(self):
        return self.checkin is not None

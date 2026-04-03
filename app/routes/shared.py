from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.models import Organisation, Session, Event, CheckIn, utcnow
from datetime import datetime, timedelta, date
from sqlalchemy import func

shared_bp = Blueprint('shared', __name__)


def org_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.organisation:
            return redirect(url_for('onboarding.step1'))
        return f(*args, **kwargs)
    return decorated


@shared_bp.route('/')
def index():
    if current_user.is_authenticated:
        if not current_user.onboarding_complete:
            return redirect(url_for('onboarding.step1'))
        return redirect(url_for('shared.dashboard'))
    return redirect(url_for('auth.login'))


@shared_bp.route('/dashboard')
@login_required
@org_required
def dashboard():
    org = current_user.organisation
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today = date.today()

    if current_user.account_type == 'corporate':
        sessions_this_month = org.sessions.filter(Session.created_at >= month_start).count()
        total_sessions = org.sessions.count()
        active_sessions = [s for s in org.sessions.all() if s.get_status() == 'active']
        upcoming_sessions = org.sessions.filter(Session.date >= today).order_by(Session.date.asc()).limit(5).all()

        # Attendance rate (last 30 days)
        thirty_ago = now - timedelta(days=30)
        recent_sessions = org.sessions.filter(Session.date >= thirty_ago.date()).all()
        total_expected = sum(s.expected_attendees.count() for s in recent_sessions if not s.open_attendance)
        total_checked = sum(s.checkins.count() for s in recent_sessions)
        attendance_rate = round((total_checked / total_expected * 100)) if total_expected > 0 else None

        # Sessions flagged for incomplete mandatory attendance
        flagged = 0
        for s in org.sessions.filter(Session.is_mandatory == True, Session.date < today).all():
            expected = s.expected_attendees.count()
            checked = s.checkins.count()
            if expected > 0 and checked < expected:
                flagged += 1

        # Sparkline data (last 14 days)
        sparkline = []
        for i in range(13, -1, -1):
            d = today - timedelta(days=i)
            count = CheckIn.query.join(Session).filter(
                Session.organisation_id == org.id,
                func.date(CheckIn.checkin_time) == d
            ).count()
            sparkline.append(count)

        return render_template('corporate/dashboard.html',
            org=org,
            sessions_this_month=sessions_this_month,
            total_sessions=total_sessions,
            active_sessions=active_sessions,
            upcoming_sessions=upcoming_sessions,
            attendance_rate=attendance_rate,
            flagged=flagged,
            sparkline=sparkline,
            now=now
        )
    else:
        events_this_month = org.events.filter(Event.created_at >= month_start).count()
        total_events = org.events.count()
        active_events = [e for e in org.events.all() if e.get_status() == 'active']
        upcoming_events = org.events.filter(Event.date >= today).order_by(Event.date.asc()).limit(5).all()

        total_checkins = CheckIn.query.join(Event).filter(Event.organisation_id == org.id).count()

        sparkline = []
        for i in range(13, -1, -1):
            d = today - timedelta(days=i)
            count = CheckIn.query.join(Event).filter(
                Event.organisation_id == org.id,
                func.date(CheckIn.checkin_time) == d
            ).count()
            sparkline.append(count)

        return render_template('events/dashboard.html',
            org=org,
            events_this_month=events_this_month,
            total_events=total_events,
            active_events=active_events,
            upcoming_events=upcoming_events,
            total_checkins=total_checkins,
            sparkline=sparkline
        )


@shared_bp.route('/analytics')
@login_required
@org_required
def analytics():
    org = current_user.organisation
    today = date.today()
    now = utcnow()

    # Last 30 days daily checkins
    daily_data = []
    daily_labels = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        daily_labels.append(d.strftime('%b %d'))
        if current_user.account_type == 'corporate':
            count = CheckIn.query.join(Session).filter(
                Session.organisation_id == org.id,
                func.date(CheckIn.checkin_time) == d
            ).count()
        else:
            count = CheckIn.query.join(Event).filter(
                Event.organisation_id == org.id,
                func.date(CheckIn.checkin_time) == d
            ).count()
        daily_data.append(count)

    return render_template('shared/analytics.html',
        org=org,
        daily_labels=daily_labels,
        daily_data=daily_data
    )


@shared_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@org_required
def settings():
    org = current_user.organisation

    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'profile':
                org_name = request.form.get('org_name', '').strip()
                if not org_name:
                    flash('Organisation name cannot be empty.', 'error')
                else:
                    org.name = org_name
                    db.session.commit()
                    flash('Organisation name updated.', 'success')

            elif action == 'email':
                new_email = request.form.get('email', '').strip().lower()
                from app.models.models import User
                if User.query.filter_by(email=new_email).filter(User.id != current_user.id).first():
                    flash('That email is already in use.', 'error')
                else:
                    current_user.email = new_email
                    db.session.commit()
                    flash('Email address updated.', 'success')

            elif action == 'password':
                current_pw = request.form.get('current_password', '')
                new_pw = request.form.get('new_password', '')
                if not current_user.check_password(current_pw):
                    flash('Current password is incorrect.', 'error')
                elif len(new_pw) < 8:
                    flash('New password must be at least 8 characters.', 'error')
                else:
                    current_user.set_password(new_pw)
                    db.session.commit()
                    flash('Password updated successfully.', 'success')

            elif action == 'smtp':
                org.smtp_host = request.form.get('smtp_host', '').strip()
                org.smtp_port = int(request.form.get('smtp_port', 587))
                org.smtp_user = request.form.get('smtp_user', '').strip()
                smtp_pw = request.form.get('smtp_password', '').strip()
                if smtp_pw:
                    org.smtp_password_enc = smtp_pw  # In prod: encrypt with app secret
                org.smtp_from_name = request.form.get('smtp_from_name', '').strip()
                org.smtp_from_email = request.form.get('smtp_from_email', '').strip()
                org.smtp_use_tls = request.form.get('smtp_use_tls') == 'on'
                db.session.commit()
                flash('SMTP settings saved.', 'success')

        except Exception as e:
            db.session.rollback()
            flash('Something went wrong. Please try again.', 'error')

    team_members = org.team_members.all() if org.plan == 'team' else []
    return render_template('shared/settings.html', org=org, team_members=team_members)

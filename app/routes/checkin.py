from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from app import db
from app.models.models import Session, Event, EventAttendee, CheckIn, utcnow
from datetime import datetime

checkin_bp = Blueprint('checkin', __name__, url_prefix='/checkin')


@checkin_bp.route('/s/<token>', methods=['GET', 'POST'])
def session_checkin(token):
    """Employee-facing check-in page for a corporate session."""
    s = Session.query.filter_by(qr_token=token).first_or_404()
    status = s.get_status()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        employee_id = request.form.get('employee_id', '').strip()

        if not name:
            return render_template('checkin/session_checkin.html', session=s, status=status, error='Please enter your name.')

        try:
            now = utcnow()
            session_start = datetime.combine(s.date, s.start_time)
            is_late = (now - session_start).total_seconds() > (s.late_threshold_minutes * 60)

            c = CheckIn(
                session_id=s.id,
                name=name,
                employee_id=employee_id or None,
                checkin_time=now,
                is_late=is_late
            )
            db.session.add(c)
            db.session.commit()

            # Broadcast to SSE listeners
            from app.routes.corporate import broadcast_checkin
            broadcast_checkin(s.id, {
                'type': 'checkin',
                'id': c.id,
                'name': c.name,
                'employee_id': c.employee_id or '',
                'time': c.checkin_time.strftime('%H:%M:%S'),
                'is_late': c.is_late,
                'is_manual': False,
                'count': s.checkins.count()
            })

            return render_template('checkin/session_success.html',
                session=s, checkin=c, is_late=is_late)

        except Exception:
            db.session.rollback()
            return render_template('checkin/session_checkin.html',
                session=s, status=status, error='Something went wrong. Please try again.')

    return render_template('checkin/session_checkin.html', session=s, status=status)


@checkin_bp.route('/e/<token>', methods=['GET', 'POST'])
def event_checkin(token):
    """Personal attendee QR code check-in."""
    attendee = EventAttendee.query.filter_by(qr_token=token).first_or_404()
    event = attendee.event

    if attendee.is_checked_in():
        return render_template('checkin/already_checked_in.html', attendee=attendee, event=event)

    try:
        c = CheckIn(
            event_id=event.id,
            attendee_id=attendee.id,
            name=attendee.name,
            email=attendee.email,
            checkin_time=utcnow()
        )
        db.session.add(c)
        db.session.commit()

        # Broadcast to event SSE
        from app.routes.events import broadcast_event_checkin
        broadcast_event_checkin(event.id, {
            'type': 'checkin',
            'id': c.id,
            'name': c.name,
            'time': c.checkin_time.strftime('%H:%M'),
            'count': event.checked_in_count(),
            'total': event.registered_count()
        })

        return render_template('checkin/event_success.html', attendee=attendee, event=event, checkin=c)

    except Exception:
        db.session.rollback()
        return render_template('checkin/event_checkin_error.html', event=event)


@checkin_bp.route('/ev/<event_id>/walkin', methods=['GET', 'POST'])
def event_walkin(event_id):
    """Walk-in check-in for events — no pre-registration needed."""
    event = Event.query.get_or_404(event_id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()

        if not name:
            return render_template('checkin/event_walkin.html', event=event, error='Please enter your name.')

        try:
            attendee = EventAttendee(
                event_id=event.id,
                name=name,
                email=email or None,
                is_walkin=True
            )
            db.session.add(attendee)
            db.session.flush()

            c = CheckIn(
                event_id=event.id,
                attendee_id=attendee.id,
                name=name,
                email=email or None,
                checkin_time=utcnow(),
                is_walkin=True
            )
            db.session.add(c)
            db.session.commit()

            from app.routes.events import broadcast_event_checkin
            broadcast_event_checkin(event.id, {
                'type': 'checkin',
                'id': c.id,
                'name': c.name,
                'time': c.checkin_time.strftime('%H:%M'),
                'count': event.checked_in_count(),
                'total': event.registered_count()
            })

            return render_template('checkin/event_success.html', attendee=attendee, event=event, checkin=c)

        except Exception:
            db.session.rollback()
            return render_template('checkin/event_walkin.html', event=event, error='Something went wrong. Please try again.')

    return render_template('checkin/event_walkin.html', event=event)

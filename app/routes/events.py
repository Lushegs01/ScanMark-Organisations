from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, Response, stream_with_context, jsonify)
from flask_login import login_required, current_user
from app import db
from app.models.models import Event, EventAttendee, CheckIn, utcnow
from app.utils.qr_utils import generate_qr_png_b64
from app.utils.export_utils import generate_event_csv
from datetime import datetime
import csv
import io
import json
import queue
import threading

events_bp = Blueprint('events', __name__, url_prefix='/events')

_sse_event_listeners = {}
_sse_event_lock = threading.Lock()


def org_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.organisation:
            return redirect(url_for('onboarding.step1'))
        if current_user.account_type != 'events':
            return redirect(url_for('shared.dashboard'))
        return f(*args, **kwargs)
    return decorated


def get_org_event(event_id):
    e = Event.query.get_or_404(event_id)
    if e.organisation_id != current_user.organisation.id:
        from flask import abort
        abort(403)
    return e


@events_bp.route('/')
@login_required
@org_required
def events_list():
    org = current_user.organisation
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    query = org.events.order_by(Event.date.desc())
    if q:
        query = query.filter(Event.name.ilike(f'%{q}%'))

    all_events = query.all()
    per_page = 20
    total = len(all_events)
    start = (page - 1) * per_page
    events_page = all_events[start:start + per_page]

    return render_template('events/events_list.html',
        events=events_page, total=total, page=page, per_page=per_page, q=q)


@events_bp.route('/new', methods=['GET', 'POST'])
@login_required
@org_required
def new_event():
    org = current_user.organisation
    can, reason = org.can_create_event()
    if not can:
        return render_template('shared/upgrade_gate.html',
            title='Event limit reached',
            message='Free accounts can create up to 3 events per month. Upgrade to Pro for unlimited events.',
            plan='Pro',
            action='Create more events'
        )

    if request.method == 'POST':
        try:
            date_str = request.form.get('date')
            start_str = request.form.get('start_time')
            capacity = request.form.get('max_capacity', '').strip()

            e = Event(
                organisation_id=org.id,
                name=request.form.get('name', '').strip(),
                date=datetime.strptime(date_str, '%Y-%m-%d').date(),
                venue=request.form.get('venue', '').strip() or None,
                start_time=datetime.strptime(start_str, '%H:%M').time(),
                max_capacity=int(capacity) if capacity else None,
                capacity_enforcement=request.form.get('capacity_enforcement') != 'off'
            )
            db.session.add(e)
            db.session.commit()
            flash(f'Event "{e.name}" created.', 'success')
            return redirect(url_for('events.event_detail', event_id=e.id))

        except Exception:
            db.session.rollback()
            flash('Could not create event. Please check your inputs.', 'error')

    return render_template('events/new_event.html')


@events_bp.route('/<event_id>')
@login_required
@org_required
def event_detail(event_id):
    e = get_org_event(event_id)
    attendees = e.attendees.order_by(EventAttendee.created_at.desc()).all()
    checkins = e.checkins.order_by(CheckIn.checkin_time.desc()).limit(20).all()
    qr_url = url_for('checkin.event_walkin', event_id=e.id, _external=True)
    qr_b64 = generate_qr_png_b64(qr_url)
    status = e.get_status()
    capacity_pct = e.capacity_percent()

    return render_template('events/event_detail.html',
        event=e,
        attendees=attendees,
        checkins=checkins,
        qr_b64=qr_b64,
        qr_url=qr_url,
        status=status,
        capacity_pct=capacity_pct
    )


@events_bp.route('/<event_id>/display')
def event_display(event_id):
    e = Event.query.get_or_404(event_id)
    qr_url = url_for('checkin.event_walkin', event_id=e.id, _external=True)
    qr_b64 = generate_qr_png_b64(qr_url, box_size=14, border=2)
    return render_template('events/event_display.html',
        event=e, qr_b64=qr_b64,
        checkin_count=e.checked_in_count(),
        total=e.registered_count()
    )


@events_bp.route('/<event_id>/stream')
def event_stream(event_id):
    def event_gen():
        q = queue.Queue()
        with _sse_event_lock:
            if event_id not in _sse_event_listeners:
                _sse_event_listeners[event_id] = []
            _sse_event_listeners[event_id].append(q)
        try:
            e = Event.query.get(event_id)
            if e:
                yield f"data: {json.dumps({'type': 'init', 'count': e.checked_in_count(), 'total': e.registered_count(), 'capacity': e.max_capacity})}\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _sse_event_lock:
                if event_id in _sse_event_listeners:
                    try:
                        _sse_event_listeners[event_id].remove(q)
                    except ValueError:
                        pass

    return Response(stream_with_context(event_gen()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def broadcast_event_checkin(event_id, data):
    with _sse_event_lock:
        for q in _sse_event_listeners.get(str(event_id), []):
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


@events_bp.route('/<event_id>/import', methods=['POST'])
@login_required
@org_required
def import_attendees(event_id):
    e = get_org_event(event_id)
    org = current_user.organisation

    csv_file = request.files.get('attendee_csv')
    if not csv_file or not csv_file.filename:
        flash('Please select a CSV file to upload.', 'error')
        return redirect(url_for('events.event_detail', event_id=event_id))

    try:
        stream = io.StringIO(csv_file.stream.read().decode('utf-8'))
        reader = csv.DictReader(stream)
        imported = 0
        skipped = 0
        max_att = org.max_attendees()

        for row in reader:
            name = row.get('name', '').strip()
            email = row.get('email', '').strip()
            if not name:
                skipped += 1
                continue

            # Free tier limit
            if max_att and (e.registered_count() + imported) >= max_att:
                flash(f'Attendee limit of {max_att} reached on the Free plan. Upgrade to Pro for unlimited attendees.', 'error')
                break

            attendee = EventAttendee(
                event_id=e.id,
                name=name,
                email=email or None,
                ticket_ref=row.get('ticket_ref', '').strip() or None
            )
            db.session.add(attendee)
            imported += 1

        db.session.commit()
        flash(f'Imported {imported} attendee{"s" if imported != 1 else ""}. {f"{skipped} rows skipped (missing name)." if skipped else ""}', 'success')

    except Exception as ex:
        db.session.rollback()
        flash('Could not parse the CSV file. Ensure it has name, email, and ticket_ref columns.', 'error')

    return redirect(url_for('events.event_detail', event_id=event_id))


@events_bp.route('/<event_id>/manual-checkin', methods=['POST'])
@login_required
@org_required
def manual_checkin(event_id):
    e = get_org_event(event_id)
    try:
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        if not name:
            flash('Name is required.', 'error')
            return redirect(url_for('events.event_detail', event_id=event_id))

        attendee = EventAttendee(
            event_id=e.id,
            name=name,
            email=email or None,
            is_walkin=True
        )
        db.session.add(attendee)
        db.session.flush()

        c = CheckIn(
            event_id=e.id,
            attendee_id=attendee.id,
            name=name,
            email=email or None,
            checkin_time=utcnow(),
            is_manual=True,
            is_walkin=True
        )
        db.session.add(c)
        db.session.commit()

        broadcast_event_checkin(event_id, {
            'type': 'checkin',
            'id': c.id,
            'name': name,
            'time': c.checkin_time.strftime('%H:%M'),
            'count': e.checked_in_count(),
            'total': e.registered_count()
        })

        flash(f'{name} manually checked in.', 'success')
    except Exception:
        db.session.rollback()
        flash('Could not complete manual check-in.', 'error')

    return redirect(url_for('events.event_detail', event_id=event_id))


@events_bp.route('/<event_id>/export/csv')
@login_required
@org_required
def export_csv(event_id):
    e = get_org_event(event_id)
    attendees = e.attendees.all()
    checkins = e.checkins.all()
    csv_data = generate_event_csv(e, checkins, attendees)
    return Response(csv_data, mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=event_{e.id[:8]}_report.csv'})


@events_bp.route('/<event_id>/export/pdf')
@login_required
@org_required
def export_pdf(event_id):
    can, _ = current_user.organisation.can_export_pdf()
    if not can:
        flash('PDF export is available on Pro and Team plans.', 'error')
        return redirect(url_for('events.event_detail', event_id=event_id))

    e = get_org_event(event_id)
    attendees = e.attendees.order_by(EventAttendee.created_at).all()
    checkins = e.checkins.order_by(CheckIn.checkin_time).all()

    # Build 15-min interval chart data
    from collections import defaultdict
    intervals = defaultdict(int)
    for c in checkins:
        if c.checkin_time:
            slot = c.checkin_time.replace(minute=(c.checkin_time.minute // 15) * 15, second=0, microsecond=0)
            intervals[slot.strftime('%H:%M')] += 1

    html = render_template('events/report_pdf.html',
        event=e, attendees=attendees, checkins=checkins,
        intervals=dict(sorted(intervals.items())),
        generated_at=utcnow()
    )
    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html).write_pdf()
        return Response(pdf_bytes, mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename=event_{e.id[:8]}_report.pdf'})
    except Exception:
        flash('PDF generation failed. Try CSV export instead.', 'error')
        return redirect(url_for('events.event_detail', event_id=event_id))


@events_bp.route('/<event_id>/delete', methods=['POST'])
@login_required
@org_required
def delete_event(event_id):
    e = get_org_event(event_id)
    try:
        db.session.delete(e)
        db.session.commit()
        flash('Event deleted.', 'success')
    except Exception:
        db.session.rollback()
        flash('Could not delete event.', 'error')
    return redirect(url_for('events.events_list'))

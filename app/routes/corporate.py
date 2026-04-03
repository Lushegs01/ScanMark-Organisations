from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, jsonify, Response, stream_with_context, send_file)
from flask_login import login_required, current_user
from app import db
from app.models.models import Session, ExpectedAttendee, CheckIn, utcnow
from app.utils.qr_utils import generate_qr_png_b64
from app.utils.export_utils import generate_session_csv
from datetime import datetime, date, time as dtime
import json
import csv
import io
import queue
import threading

corporate_bp = Blueprint('corporate', __name__, url_prefix='/corporate')

# SSE subscribers per session
_sse_listeners = {}
_sse_lock = threading.Lock()


def org_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.organisation:
            return redirect(url_for('onboarding.step1'))
        if current_user.account_type != 'corporate':
            return redirect(url_for('shared.dashboard'))
        return f(*args, **kwargs)
    return decorated


def get_org_session(session_id):
    s = Session.query.get_or_404(session_id)
    if s.organisation_id != current_user.organisation.id:
        from flask import abort
        abort(403)
    return s


@corporate_bp.route('/sessions')
@login_required
@org_required
def sessions():
    org = current_user.organisation
    q = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)

    query = org.sessions.order_by(Session.date.desc(), Session.start_time.desc())
    if q:
        query = query.filter(Session.name.ilike(f'%{q}%'))

    all_sessions = query.all()
    # Apply status filter after computing live status
    if status_filter:
        all_sessions = [s for s in all_sessions if s.get_status() == status_filter]

    per_page = 20
    total = len(all_sessions)
    start = (page - 1) * per_page
    sessions_page = all_sessions[start:start + per_page]

    return render_template('corporate/sessions.html',
        sessions=sessions_page,
        total=total,
        page=page,
        per_page=per_page,
        q=q,
        status_filter=status_filter
    )


@corporate_bp.route('/sessions/new', methods=['GET', 'POST'])
@login_required
@org_required
def new_session():
    org = current_user.organisation
    can, reason = org.can_create_session()
    if not can:
        return render_template('shared/upgrade_gate.html',
            title='Session limit reached',
            message='Free accounts can create up to 3 sessions per month. Upgrade to Pro for unlimited sessions.',
            plan='Pro',
            action='Create more sessions'
        )

    if request.method == 'POST':
        try:
            session_type = request.form.get('session_type')
            date_str = request.form.get('date')
            start_str = request.form.get('start_time')

            s = Session(
                organisation_id=org.id,
                session_type=session_type,
                name=request.form.get('name', '').strip(),
                date=datetime.strptime(date_str, '%Y-%m-%d').date(),
                start_time=datetime.strptime(start_str, '%H:%M').time(),
                open_attendance=request.form.get('open_attendance') == 'on',
                is_mandatory=request.form.get('is_mandatory') == 'on',
                late_threshold_minutes=int(request.form.get('late_threshold', 5))
            )

            if session_type == 'shift':
                s.department = request.form.get('department', '').strip()
                end_str = request.form.get('end_time')
                if end_str:
                    s.end_time = datetime.strptime(end_str, '%H:%M').time()
            else:
                s.facilitator = request.form.get('facilitator', '').strip()
                s.duration_minutes = int(request.form.get('duration', 60))

            db.session.add(s)
            db.session.flush()  # get ID before CSV processing

            # CSV upload for expected attendees
            csv_file = request.files.get('attendee_csv')
            if csv_file and csv_file.filename:
                stream = io.StringIO(csv_file.stream.read().decode('utf-8'))
                reader = csv.DictReader(stream)
                for row in reader:
                    name = row.get('name', '').strip()
                    if name:
                        ea = ExpectedAttendee(
                            session_id=s.id,
                            name=name,
                            employee_id=row.get('employee_id', '').strip() or None
                        )
                        db.session.add(ea)
                s.open_attendance = False

            db.session.commit()
            flash(f'Session "{s.name}" created successfully.', 'success')
            return redirect(url_for('corporate.session_detail', session_id=s.id))

        except Exception as e:
            db.session.rollback()
            flash('Could not create session. Please check your inputs and try again.', 'error')

    return render_template('corporate/new_session.html')


@corporate_bp.route('/sessions/<session_id>')
@login_required
@org_required
def session_detail(session_id):
    s = get_org_session(session_id)
    checkins = s.checkins.order_by(CheckIn.checkin_time.asc()).all()
    expected = s.expected_attendees.all()
    qr_url = url_for('checkin.session_checkin', token=s.qr_token, _external=True)
    qr_b64 = generate_qr_png_b64(qr_url)
    status = s.get_status()

    # Missing attendees for mandatory sessions
    missing = []
    if not s.open_attendance and s.is_mandatory:
        checked_ids = {c.employee_id for c in checkins if c.employee_id}
        checked_names = {c.name.lower() for c in checkins}
        missing = [e for e in expected if e.employee_id not in checked_ids and e.name.lower() not in checked_names]

    return render_template('corporate/session_detail.html',
        session=s,
        checkins=checkins,
        expected=expected,
        missing=missing,
        qr_b64=qr_b64,
        qr_url=qr_url,
        status=status
    )


@corporate_bp.route('/sessions/<session_id>/display')
def session_display(session_id):
    """Full-screen QR display for projecting — no auth needed for display."""
    s = Session.query.filter_by(id=session_id).first_or_404()
    qr_url = url_for('checkin.session_checkin', token=s.qr_token, _external=True)
    qr_b64 = generate_qr_png_b64(qr_url, box_size=14, border=2)
    checkin_count = s.checkins.count()
    return render_template('corporate/session_display.html',
        session=s,
        qr_b64=qr_b64,
        checkin_count=checkin_count
    )


@corporate_bp.route('/sessions/<session_id>/stream')
def session_stream(session_id):
    """SSE stream for live check-in updates."""
    def event_stream():
        q = queue.Queue()
        with _sse_lock:
            if session_id not in _sse_listeners:
                _sse_listeners[session_id] = []
            _sse_listeners[session_id].append(q)
        try:
            # Send current count immediately
            s = Session.query.get(session_id)
            if s:
                count = s.checkins.count()
                yield f"data: {json.dumps({'type': 'count', 'count': count})}\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _sse_lock:
                if session_id in _sse_listeners:
                    try:
                        _sse_listeners[session_id].remove(q)
                    except ValueError:
                        pass

    return Response(stream_with_context(event_stream()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def broadcast_checkin(session_id, checkin_data):
    """Broadcast a new check-in to all SSE listeners."""
    with _sse_lock:
        listeners = _sse_listeners.get(session_id, [])
        for q in listeners:
            try:
                q.put_nowait(checkin_data)
            except queue.Full:
                pass


@corporate_bp.route('/sessions/<session_id>/manual-checkin', methods=['POST'])
@login_required
@org_required
def manual_checkin(session_id):
    s = get_org_session(session_id)
    try:
        name = request.form.get('name', '').strip()
        employee_id = request.form.get('employee_id', '').strip()
        if not name:
            flash('Name is required for manual check-in.', 'error')
            return redirect(url_for('corporate.session_detail', session_id=session_id))

        now = utcnow()
        session_start = datetime.combine(s.date, s.start_time)
        is_late = (now - session_start).total_seconds() > (s.late_threshold_minutes * 60)

        c = CheckIn(
            session_id=s.id,
            name=name,
            employee_id=employee_id or None,
            checkin_time=now,
            is_late=is_late,
            is_manual=True
        )
        db.session.add(c)
        db.session.commit()

        broadcast_checkin(session_id, {
            'type': 'checkin',
            'id': c.id,
            'name': c.name,
            'employee_id': c.employee_id or '',
            'time': c.checkin_time.strftime('%H:%M:%S'),
            'is_late': c.is_late,
            'is_manual': True,
            'count': s.checkins.count()
        })

        flash(f'Manual check-in recorded for {name}.', 'success')
    except Exception:
        db.session.rollback()
        flash('Could not record manual check-in.', 'error')

    return redirect(url_for('corporate.session_detail', session_id=session_id))


@corporate_bp.route('/sessions/<session_id>/export/csv')
@login_required
@org_required
def export_csv(session_id):
    s = get_org_session(session_id)
    checkins = s.checkins.order_by(CheckIn.checkin_time).all()
    csv_data = generate_session_csv(s, checkins)
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=session_{s.id[:8]}_report.csv'}
    )


@corporate_bp.route('/sessions/<session_id>/export/pdf')
@login_required
@org_required
def export_pdf(session_id):
    can, reason = current_user.organisation.can_export_pdf()
    if not can:
        flash('PDF export is available on Pro and Team plans.', 'error')
        return redirect(url_for('corporate.session_detail', session_id=session_id))

    s = get_org_session(session_id)
    checkins = s.checkins.order_by(CheckIn.checkin_time).all()
    expected = s.expected_attendees.all()

    missing = []
    if not s.open_attendance:
        checked_ids = {c.employee_id for c in checkins if c.employee_id}
        checked_names = {c.name.lower() for c in checkins}
        missing = [e for e in expected if e.employee_id not in checked_ids and e.name.lower() not in checked_names]

    html = render_template('corporate/report_pdf.html',
        session=s, checkins=checkins, expected=expected, missing=missing,
        generated_at=utcnow()
    )
    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html).write_pdf()
        return Response(pdf_bytes, mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename=session_{s.id[:8]}_report.pdf'})
    except Exception:
        flash('PDF generation failed. Please try CSV export instead.', 'error')
        return redirect(url_for('corporate.session_detail', session_id=session_id))


@corporate_bp.route('/sessions/<session_id>/delete', methods=['POST'])
@login_required
@org_required
def delete_session(session_id):
    s = get_org_session(session_id)
    try:
        db.session.delete(s)
        db.session.commit()
        flash('Session deleted.', 'success')
    except Exception:
        db.session.rollback()
        flash('Could not delete session.', 'error')
    return redirect(url_for('corporate.sessions'))

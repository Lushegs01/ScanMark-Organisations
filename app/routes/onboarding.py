from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models.models import Organisation, TeamMember, utcnow
import secrets

onboarding_bp = Blueprint('onboarding', __name__, url_prefix='/onboarding')


def onboarding_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.onboarding_complete:
            return redirect(url_for('shared.dashboard'))
        return f(*args, **kwargs)
    return decorated


@onboarding_bp.route('/step1', methods=['GET', 'POST'])
@login_required
def step1():
    if current_user.onboarding_complete:
        return redirect(url_for('shared.dashboard'))

    if request.method == 'POST':
        org_name = request.form.get('org_name', '').strip()
        if not org_name:
            flash('Organisation name is required.', 'error')
            return redirect(url_for('onboarding.step1'))

        try:
            # Create or update organisation
            org = current_user.organisation
            if not org:
                org = Organisation(owner_id=current_user.id, account_type=current_user.account_type)
                db.session.add(org)

            org.name = org_name

            if current_user.account_type == 'corporate':
                org.industry = request.form.get('industry')
                org.team_size = request.form.get('team_size')
            else:
                org.event_type = request.form.get('event_type')
                org.typical_attendees = request.form.get('typical_attendees')

            db.session.commit()
            return redirect(url_for('onboarding.step2'))
        except Exception:
            db.session.rollback()
            flash('Something went wrong. Please try again.', 'error')

    return render_template('onboarding/step1.html')


@onboarding_bp.route('/step2', methods=['GET', 'POST'])
@login_required
def step2():
    if current_user.onboarding_complete:
        return redirect(url_for('shared.dashboard'))

    org = current_user.organisation
    if not org:
        return redirect(url_for('onboarding.step1'))

    if request.method == 'POST':
        try:
            if current_user.account_type == 'corporate':
                org.use_case = request.form.get('use_case', 'both')
                invite_email = request.form.get('invite_email', '').strip()
                if invite_email:
                    token = secrets.token_urlsafe(32)
                    member = TeamMember(
                        organisation_id=org.id,
                        email=invite_email,
                        role='member',
                        invite_token=token
                    )
                    db.session.add(member)

            current_user.onboarding_complete = True
            db.session.commit()
            return redirect(url_for('shared.dashboard'))
        except Exception:
            db.session.rollback()
            flash('Something went wrong. Please try again.', 'error')

    return render_template('onboarding/step2.html', org=org)

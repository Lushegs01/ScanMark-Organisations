from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.models import User, Organisation, PasswordReset, utcnow
from app.forms.auth_forms import RegistrationForm, LoginForm, RequestPasswordResetForm, ResetPasswordForm
from app.utils.email_utils import send_password_reset_email
import secrets
from datetime import timedelta

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('shared.dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            user = User(
                full_name=form.full_name.data.strip(),
                email=form.email.data.lower().strip(),
                account_type=form.account_type.data
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for('onboarding.step1'))
        except Exception as e:
            db.session.rollback()
            flash('Something went wrong. Please try again.', 'error')

    return render_template('auth/register.html', form=form)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('shared.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            user.last_login = utcnow()
            db.session.commit()
            if not user.onboarding_complete:
                return redirect(url_for('onboarding.step1'))
            next_page = request.args.get('next')
            return redirect(next_page or url_for('shared.dashboard'))
        flash('Incorrect email or password. Please try again.', 'error')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    form = RequestPasswordResetForm()
    sent = False
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user:
            try:
                token = secrets.token_urlsafe(48)
                reset = PasswordReset(
                    user_id=user.id,
                    token=token,
                    expires_at=utcnow() + timedelta(hours=2)
                )
                db.session.add(reset)
                db.session.commit()
                send_password_reset_email(user, token)
            except Exception:
                db.session.rollback()
        # Always show success to prevent enumeration
        sent = True

    return render_template('auth/forgot_password.html', form=form, sent=sent)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    reset = PasswordReset.query.filter_by(token=token).first()
    if not reset or not reset.is_valid():
        return render_template('auth/reset_invalid.html')

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            reset.user.set_password(form.password.data)
            reset.used = True
            db.session.commit()
            flash('Your password has been updated. Please log in.', 'success')
            return redirect(url_for('auth.login'))
        except Exception:
            db.session.rollback()
            flash('Something went wrong. Please try again.', 'error')

    return render_template('auth/reset_password.html', form=form, token=token)

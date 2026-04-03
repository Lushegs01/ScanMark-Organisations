from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.models import utcnow
import stripe

billing_bp = Blueprint('billing', __name__, url_prefix='/billing')


@billing_bp.route('/pricing')
def pricing():
    return render_template('shared/pricing.html',
        stripe_public_key=current_app.config.get('STRIPE_PUBLIC_KEY', ''))


@billing_bp.route('/checkout/<plan>')
@login_required
def checkout(plan):
    if plan not in ('pro', 'team'):
        return redirect(url_for('billing.pricing'))

    org = current_user.organisation
    if not org:
        return redirect(url_for('onboarding.step1'))

    price_id = current_app.config.get(f'STRIPE_{plan.upper()}_PRICE_ID')
    if not price_id:
        flash('Stripe is not configured. Please contact support.', 'error')
        return redirect(url_for('billing.pricing'))

    try:
        # Create/retrieve Stripe customer
        if not org.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                name=org.name,
                metadata={'org_id': org.id}
            )
            org.stripe_customer_id = customer.id
            db.session.commit()

        session = stripe.checkout.Session.create(
            customer=org.stripe_customer_id,
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription',
            success_url=url_for('billing.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('billing.pricing', _external=True),
            metadata={'org_id': org.id, 'plan': plan}
        )
        return redirect(session.url)

    except stripe.error.StripeError as e:
        flash('Could not initiate checkout. Please try again.', 'error')
        return redirect(url_for('billing.pricing'))


@billing_bp.route('/success')
@login_required
def success():
    flash('🎉 Subscription activated! Your account has been upgraded.', 'success')
    return redirect(url_for('shared.dashboard'))


@billing_bp.route('/portal')
@login_required
def portal():
    org = current_user.organisation
    if not org or not org.stripe_customer_id:
        return redirect(url_for('billing.pricing'))
    try:
        session = stripe.billing_portal.Session.create(
            customer=org.stripe_customer_id,
            return_url=url_for('shared.settings', _external=True)
        )
        return redirect(session.url)
    except Exception:
        flash('Could not open billing portal. Please try again.', 'error')
        return redirect(url_for('shared.settings'))


@billing_bp.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data()
    sig = request.headers.get('Stripe-Signature')
    secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')

    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return jsonify({'error': 'Invalid signature'}), 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        org_id = session.get('metadata', {}).get('org_id')
        plan = session.get('metadata', {}).get('plan', 'pro')
        if org_id:
            from app.models.models import Organisation
            org = Organisation.query.get(org_id)
            if org:
                org.plan = plan
                org.stripe_subscription_id = session.get('subscription')
                org.subscription_status = 'active'
                db.session.commit()

    elif event['type'] == 'customer.subscription.deleted':
        sub = event['data']['object']
        from app.models.models import Organisation
        org = Organisation.query.filter_by(stripe_subscription_id=sub['id']).first()
        if org:
            org.plan = 'free'
            org.subscription_status = 'cancelled'
            db.session.commit()

    elif event['type'] == 'customer.subscription.updated':
        sub = event['data']['object']
        from app.models.models import Organisation
        org = Organisation.query.filter_by(stripe_subscription_id=sub['id']).first()
        if org:
            org.subscription_status = sub['status']
            db.session.commit()

    return jsonify({'status': 'ok'})

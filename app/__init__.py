from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
import stripe
import os

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
mail = Mail()
csrf = CSRFProtect()


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__, template_folder='templates', static_folder='static')

    from config import config
    app.config.from_object(config.get(config_name, config['default']))

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    csrf.init_app(app)

    # Stripe
    stripe.api_key = app.config.get('STRIPE_SECRET_KEY')

    # Login config
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.models import User
        return User.query.get(user_id)

    # Jinja2 globals and filters
    from datetime import datetime as _dt
    app.jinja_env.globals['now'] = _dt.utcnow
    app.jinja_env.filters['min'] = min
    app.jinja_env.filters['max'] = max

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.onboarding import onboarding_bp
    from app.routes.corporate import corporate_bp
    from app.routes.events import events_bp
    from app.routes.shared import shared_bp
    from app.routes.checkin import checkin_bp
    from app.routes.billing import billing_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(corporate_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(shared_bp)
    app.register_blueprint(checkin_bp)
    app.register_blueprint(billing_bp)

    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template('shared/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        from flask import render_template
        return render_template('shared/500.html'), 500

    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template('shared/403.html'), 403

    # Create tables for SQLite dev
    with app.app_context():
        db.create_all()

    return app

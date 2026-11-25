import os

from flask import Flask, g, request, session, Response, flash, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from werkzeug.utils import safe_join
from sqlalchemy.orm import undefer


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config_object=None):
    app = Flask(__name__)
    database_url = os.getenv("DATABASE_URL", "sqlite:///electronics_store.db").strip()
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        WTF_CSRF_ENABLED=True,
        WTF_CSRF_TIME_LIMIT=86400,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "true").lower() == "true",
        UPLOAD_FOLDER=os.getenv("UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads")),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    )
    if config_object:
        app.config.from_object(config_object)
    if not app.testing:
        secret_key = app.config.get("SECRET_KEY")
        if not isinstance(secret_key, str) or len(secret_key) < 32:
            raise RuntimeError("Configure a SECRET_KEY with at least 32 characters outside testing.")
        if os.getenv("APP_ENV", "").strip().lower() == "production" and app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:"):
            raise RuntimeError("Configure DATABASE_URL with a persistent PostgreSQL database for production.")

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = "auth.login"

    from . import models

    @app.cli.command("bootstrap-store")
    def bootstrap_store():
        """Create one independent client store from STORE_* environment variables."""
        from sqlalchemy.exc import IntegrityError
        from .utils import slugify

        store_name = os.getenv("STORE_NAME", "").strip()
        store_slug = slugify(os.getenv("STORE_SLUG", "") or store_name)
        owner_name = os.getenv("STORE_OWNER_NAME", "").strip()
        owner_email = os.getenv("STORE_OWNER_EMAIL", "").strip().lower()
        owner_password = os.getenv("STORE_OWNER_PASSWORD", "")
        contact_email = os.getenv("STORE_CONTACT_EMAIL", "").strip().lower() or owner_email
        whatsapp_number = os.getenv("STORE_WHATSAPP_NUMBER", "").strip() or None

        if not store_name or not store_slug or len(store_slug) > 160 or not owner_name or not owner_email:
            raise RuntimeError(
                "Set STORE_NAME, STORE_OWNER_NAME and STORE_OWNER_EMAIL; "
                "STORE_SLUG is optional and defaults to a slug of STORE_NAME. "
                "The store slug must be no longer than 160 characters."
            )
        if len(owner_name) > 160 or len(owner_email) > 255:
            raise RuntimeError("STORE_OWNER_NAME or STORE_OWNER_EMAIL exceeds the supported length.")

        business = models.Business.query.filter_by(slug=store_slug).first()
        existing_owner = models.User.query.filter_by(email=owner_email).first()
        if existing_owner and (not business or existing_owner.business_id != business.id):
            raise RuntimeError("STORE_OWNER_EMAIL is already assigned to another account.")
        if business and business.status != "ACTIVE":
            raise RuntimeError("The existing store is not active; refusing to change its status.")
        if business:
            another_owner = models.User.query.filter(
                models.User.business_id == business.id,
                models.User.role == "OWNER",
                models.User.email != owner_email,
            ).first()
            if another_owner:
                raise RuntimeError("This store already has a different owner account; refusing to add or replace an owner.")
        if not existing_owner and (not owner_password or len(owner_password) < 12):
            raise RuntimeError("Set STORE_OWNER_PASSWORD to a unique password of at least 12 characters.")

        try:
            if business is None:
                business = models.Business(
                    name=store_name,
                    slug=store_slug,
                    description=os.getenv("STORE_DESCRIPTION", "").strip() or None,
                    contact_email=contact_email,
                    whatsapp_number=whatsapp_number,
                    status="ACTIVE",
                )
                db.session.add(business)
                db.session.flush()

            if existing_owner is None:
                owner = models.User(
                    business_id=business.id,
                    name=owner_name,
                    email=owner_email,
                    role="OWNER",
                    active=True,
                )
                owner.set_password(owner_password)
                db.session.add(owner)

            if not models.StoreSettings.query.filter_by(business_id=business.id).first():
                db.session.add(models.StoreSettings(business_id=business.id))

            if not models.Category.query.filter_by(business_id=business.id).first():
                defaults = [
                    "Smartphones", "Laptops", "Desktop Computers", "Tablets",
                    "Smartwatches", "Headphones", "Speakers", "Cameras",
                    "Gaming Consoles", "Gaming Accessories", "Televisions",
                    "Monitors", "Keyboards and Mice", "Power Banks",
                    "Chargers and Cables", "Storage Devices", "Home Appliances", "Accessories",
                ]
                for category_name in defaults:
                        category_slug = slugify(category_name)
                        db.session.add(models.Category(
                            business_id=business.id,
                            name=category_name,
                            slug=category_slug,
                            gender="All",
                        ))
            db.session.commit()
            print(f"Store {store_name} and owner account created successfully.")
        except IntegrityError:
            db.session.rollback()
            raise RuntimeError("Store bootstrap encountered an existing database record; no partial setup was saved.")

    @app.cli.command("seed-electronics")
    def seed_electronics():
        """Add a one-time electronics preview catalogue to an empty store."""
        from .utils import slugify

        business = models.Business.query.filter_by(status="ACTIVE").order_by(models.Business.id.asc()).first()
        if business is None:
            raise RuntimeError("Create a store and owner first with bootstrap-store.")
        if models.Product.query.filter_by(business_id=business.id).first():
            print("Electronics preview catalogue already exists.")
            return

        category_names = [
            "Smartphones", "Laptops", "Tablets", "Smartwatches",
            "Headphones", "Speakers", "Cameras", "Gaming Accessories",
            "Televisions", "Power Banks", "Chargers and Cables", "Storage Devices",
        ]
        categories = {}
        for name in category_names:
            category = models.Category.query.filter_by(business_id=business.id, name=name).first()
            if category is None:
                category = models.Category(
                    business_id=business.id,
                    name=name,
                    slug=slugify(name),
                    gender="All",
                )
                db.session.add(category)
                db.session.flush()
            categories[name] = category

        catalogue = [
            ("Nova Pro 15", "Smartphones", 420000, "6.7-inch OLED, 256GB storage, 12GB RAM", "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=1200&q=85", "256 GB"),
            ("AeroBook 14", "Laptops", 760000, "Intel Core i7, 16GB RAM, 512GB SSD", "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=1200&q=85", "512 GB"),
            ("Slate Pad 11", "Tablets", 330000, "11-inch display, 8GB RAM, 128GB storage", "https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?auto=format&fit=crop&w=1200&q=85", "128 GB"),
            ("Pulse Watch S", "Smartwatches", 185000, "AMOLED display, heart-rate and GPS", "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=1200&q=85", "42 mm"),
            ("Studio Quiet Pro", "Headphones", 145000, "Active noise cancellation, 40-hour battery", "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=1200&q=85", "Wireless"),
            ("Room Audio Mini", "Speakers", 98000, "Compact wireless speaker with rich stereo sound", "https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?auto=format&fit=crop&w=1200&q=85", "Bluetooth"),
            ("FrameMirror X", "Cameras", 520000, "Full-frame sensor, 4K video, fast autofocus", "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=1200&q=85", "Mirrorless"),
            ("Arc Controller", "Gaming Accessories", 85000, "Wireless precision controller for PC and console", "https://images.unsplash.com/photo-1592840496694-26d035b52b48?auto=format&fit=crop&w=1200&q=85", "Wireless"),
            ("Vista 55 OLED", "Televisions", 890000, "55-inch 4K OLED, smart streaming and HDR", "https://images.unsplash.com/photo-1593359677879-a4bb92f829d1?auto=format&fit=crop&w=1200&q=85", "55 inch"),
            ("Volt Pocket 20", "Power Banks", 35000, "20,000mAh high-speed portable battery", "https://images.unsplash.com/photo-1609091839311-d5365f9ff1c5?auto=format&fit=crop&w=1200&q=85", "20,000 mAh"),
            ("Charge Trio 65", "Chargers and Cables", 42000, "65W USB-C fast charger with braided cable", "https://images.unsplash.com/photo-1583863788434-e58a36330cf0?auto=format&fit=crop&w=1200&q=85", "65W"),
            ("SwiftDrive 1TB", "Storage Devices", 115000, "Portable 1TB NVMe SSD, USB-C 10Gbps", "https://images.unsplash.com/photo-1597872200969-2b65d56bd16b?auto=format&fit=crop&w=1200&q=85", "1 TB"),
        ]

        for index, (name, category_name, price, description, image_url, configuration) in enumerate(catalogue):
            slug = slugify(name)
            product = models.Product(
                business_id=business.id,
                category_id=categories[category_name].id,
                name=name,
                slug=slug,
                description=description,
                regular_price=price,
                discounted_price=price if index % 4 else int(price * 0.9),
                gender="Unisex",
                fashion_type="Device",
                featured=index < 6,
                new_arrival=True,
                is_published=True,
                sku=f"EL-{index + 1:03d}",
            )
            db.session.add(product)
            db.session.flush()
            db.session.add(models.ProductImage(
                business_id=business.id,
                product_id=product.id,
                url=image_url,
                alt_text=name,
                sort_order=0,
            ))
            db.session.add(models.ProductVariant(
                business_id=business.id,
                product_id=product.id,
                size=configuration,
                colour="Black",
                sku=f"EL-{index + 1:03d}-BK",
                stock_quantity=12,
                is_available=True,
            ))

        settings = models.StoreSettings.query.filter_by(business_id=business.id).first()
        if settings:
            settings.announcement = None
            settings.hero_title = "Technology for better living."
            settings.about_text = "Discover premium smartphones, computing, audio, gaming and smart devices selected for performance and everyday reliability."
            settings.catalogue_eyebrow = "Featured devices"
            settings.catalogue_title = "Essential technology, beautifully selected."
            settings.seo_title = f"{business.name} | Premium Electronics"
            settings.seo_description = "Shop premium smartphones, laptops, audio, gaming and smart devices."

        db.session.commit()
        print(f"Added {len(catalogue)} electronics preview products.")

    @app.cli.command("bootstrap-sulex")
    def bootstrap_sulex():
        """Create the original Sulex store and owner from private environment variables."""
        from sqlalchemy.exc import IntegrityError
        from .utils import slugify

        owner_email = os.getenv("SULEX_OWNER_EMAIL", "").strip().lower()
        owner_password = os.getenv("SULEX_OWNER_PASSWORD", "")
        existing_business = models.Business.query.filter_by(slug="sulex").first()
        existing_owner = models.User.query.filter_by(email=owner_email).first() if owner_email else None

        # Safe on every restart after successful setup; never resets an existing password.
        if existing_business and existing_owner and existing_owner.business_id == existing_business.id:
            print("Sulex bootstrap already completed.")
            return
        if not owner_email or not owner_password:
            raise RuntimeError("Set SULEX_OWNER_EMAIL and SULEX_OWNER_PASSWORD in the service environment.")
        if existing_owner:
            raise RuntimeError("SULEX_OWNER_EMAIL is already assigned to a different account.")
        if existing_business and existing_business.status != "ACTIVE":
            raise RuntimeError("The existing Sulex store is not active; refusing to change its status.")

        try:
            business = existing_business or models.Business(
                name="Sulex",
                slug="sulex",
                description="Sulex clothing store",
                contact_email=owner_email,
                status="ACTIVE",
            )
            if not existing_business:
                db.session.add(business)
                db.session.flush()

            owner = models.User(
                business_id=business.id,
                name="Sulex Owner",
                email=owner_email,
                role="OWNER",
                active=True,
            )
            owner.set_password(owner_password)
            db.session.add(owner)

            if not models.StoreSettings.query.filter_by(business_id=business.id).first():
                db.session.add(models.StoreSettings(business_id=business.id))

            if not models.Category.query.filter_by(business_id=business.id).first():
                defaults = [
                    "Smartphones", "Laptops", "Desktop Computers", "Tablets",
                    "Smartwatches", "Headphones", "Speakers", "Cameras",
                    "Gaming Consoles", "Gaming Accessories", "Televisions",
                    "Monitors", "Keyboards and Mice", "Power Banks",
                    "Chargers and Cables", "Storage Devices", "Home Appliances",
                    "Accessories",
                ]
                for category_name in defaults:
                    slug = slugify(category_name)
                    db.session.add(models.Category(
                        business_id=business.id,
                        name=category_name,
                        slug=slug,
                        gender="All",
                    ))
            db.session.commit()
            print("Sulex store and owner account created successfully.")
        except IntegrityError:
            db.session.rollback()
            raise RuntimeError("Sulex bootstrap encountered an existing database record; no partial setup was saved.")

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return None
        user = models.User.query.filter_by(id=user_id, active=True).first()
        if not user or not user.active:
            return None
        if user.role == "OWNER" and not models.Business.query.filter_by(
            id=user.business_id,
            status="ACTIVE",
        ).first():
            return None
        if user.role not in {"OWNER", "SUPER_ADMIN"}:
            return None
        return user

    @app.before_request
    def resolve_store():
        """Resolve the one configured shop; a connected custom domain may override it."""
        host = (request.host or "").split(":")[0].rstrip(".").lower()
        domain = models.Domain.query.filter(
            db.func.lower(models.Domain.host) == host
        ).first()

        if domain:
            business = domain.business if domain.status == "CONNECTED" else None
            if business and business.status == "ACTIVE":
                g.business = business
                g.domain_status = "CONNECTED"
            else:
                g.business = None
                g.domain_status = domain.status
            return None

        # This app is configured as a single-business catalogue. Use the
        # first active business automatically; no store slug setting is needed.
        business = models.Business.query.filter_by(
            status="ACTIVE"
        ).order_by(models.Business.id.asc()).first()
        g.business = business
        g.domain_status = "default" if business else "NOT_CONFIGURED"

    from .routes.auth import bp as auth_bp
    from .routes.admin import bp as admin_bp
    from .routes.owner import bp as owner_bp
    from .routes.storefront import bp as storefront_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(owner_bp)
    app.register_blueprint(storefront_bp)

    @app.get("/media/products/<int:image_id>")
    def product_image(image_id):
        image = models.ProductImage.query.options(undefer(models.ProductImage.image_data)).filter_by(id=image_id).first_or_404()
        if not image.image_data or not image.mime_type:
            # Preserve old filesystem-backed catalogue image URLs.
            from flask import abort
            abort(404)
        response = Response(image.image_data, mimetype=image.mime_type)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "public, max-age=86400, immutable"
        return response

    @app.get("/media/businesses/<int:business_id>/logo")
    def business_logo(business_id):
        business = models.Business.query.options(undefer(models.Business.logo_data)).filter_by(id=business_id).first_or_404()
        if not business.logo_data or not business.logo_mime_type:
            from flask import abort
            abort(404)
        response = Response(business.logo_data, mimetype=business.logo_mime_type)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    @app.get("/media/businesses/<int:business_id>/banner")
    def business_banner(business_id):
        business = models.Business.query.options(undefer(models.Business.banner_data)).filter_by(id=business_id).first_or_404()
        if not business.banner_data or not business.banner_mime_type:
            from flask import abort
            abort(404)
        response = Response(business.banner_data, mimetype=business.banner_mime_type)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    @app.get("/media/<path:filename>")
    def uploaded_media(filename):
        resolved_path = safe_join(app.config["UPLOAD_FOLDER"], filename)
        if not resolved_path:
            from flask import abort
            abort(404)
        resolved_path = os.path.realpath(resolved_path)
        upload_root = os.path.realpath(app.config["UPLOAD_FOLDER"])
        if os.path.commonpath([resolved_path, upload_root]) != upload_root or not os.path.isfile(resolved_path):
            from flask import abort
            abort(404)
        with open(resolved_path, "rb") as media_file:
            data = media_file.read()
        response = Response(data, mimetype="application/octet-stream")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    @app.get("/health")
    def health():
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    @app.context_processor
    def inject_common():
        business = getattr(g, "business", None)
        store_settings = models.StoreSettings.query.filter_by(business_id=business.id).first() if business else None
        cart_count = 0
        if business:
            cart = session.get("cart", {})
            try:
                variant_ids = [int(key.split(":", 1)[0]) for key in cart]
            except (TypeError, ValueError):
                variant_ids = []
            if variant_ids:
                variants = models.ProductVariant.query.filter(
                    models.ProductVariant.business_id == business.id,
                    models.ProductVariant.id.in_(variant_ids),
                ).all()
                cart_count = sum(int(cart.get(f"{variant.id}:", 0)) for variant in variants)
        return {"tenant": business, "cart_count": cart_count, "settings": store_settings}

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        flash("Your form session expired. Please review the form and submit it again.", "warning")
        return redirect(request.referrer or url_for("auth.login"))

    @app.errorhandler(404)
    def not_found(error):
        return {"error": "Not found"}, 404

    return app

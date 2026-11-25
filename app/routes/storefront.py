from flask import Blueprint, g, render_template, request, abort, jsonify
from sqlalchemy import case, func, or_, cast, String
from sqlalchemy.orm import joinedload, selectinload

from .. import db, csrf
from ..models import Category, Product, ProductVariant, StoreVisit, StoreSettings

bp = Blueprint("storefront", __name__)
PAGE_SIZE = 24


def public_business():
    business = getattr(g, "business", None)
    if business is None:
        abort(404)
    return business


@bp.post("/track-visit")
@csrf.exempt
def track_visit():
    """Record page views outside the navigation response so page changes stay fast."""
    business = getattr(g, "business", None)
    payload = request.get_json(silent=True) or {}
    path = payload.get("path", "")
    if business and isinstance(path, str) and path.startswith("/") and not path.startswith("//"):
        db.session.add(StoreVisit(business_id=business.id, path=path[:500]))
        db.session.commit()
    return jsonify({"ok": True}), 202


def storefront_context(business):
    settings = StoreSettings.query.filter_by(business_id=business.id).first()
    all_categories = Category.query.filter_by(business_id=business.id).order_by(Category.name, Category.id).all()
    categories = []
    seen_names = set()
    for category in all_categories:
        key = " ".join((category.name or "").split()).casefold()
        if key and key not in seen_names:
            categories.append(category)
            seen_names.add(key)
    return settings, categories


def public_products(business):
    return Product.query.options(
        selectinload(Product.images),
        selectinload(Product.variants),
        joinedload(Product.category),
    ).filter_by(business_id=business.id, is_published=True)


def category_for_slug(business, slug):
    category = Category.query.filter_by(business_id=business.id, slug=slug).first()
    if category:
        return category
    normalized = " ".join(slug.replace("-", " ").split()).casefold()
    candidates = Category.query.filter_by(business_id=business.id).order_by(Category.id).all()
    return next((item for item in candidates if " ".join((item.name or "").split()).casefold() == normalized), None)


def render_listing(business, products, selected_category=None, selected_size="", selected_colour="", page=1, page_count=1, search_term="", min_price=None, max_price=None, selected_brand="", selected_condition="", spec_key="", spec_value=""):
    settings, categories = storefront_context(business)
    size_values = db.session.query(ProductVariant.size).filter_by(
        business_id=business.id, is_available=True
    ).distinct().order_by(ProductVariant.size).all()
    colour_values = db.session.query(ProductVariant.colour).filter_by(
        business_id=business.id, is_available=True
    ).distinct().order_by(ProductVariant.colour).all()
    sizes = sorted({value.strip() for (value,) in size_values if value and value.strip()}, key=str.casefold)
    colours = sorted({value.strip() for (value,) in colour_values if value and value.strip()}, key=str.casefold)
    brands = [value for (value,) in db.session.query(Product.brand).filter(
        Product.business_id == business.id, Product.is_published.is_(True), Product.brand.isnot(None)
    ).distinct().order_by(Product.brand).all() if value]
    return render_template(
        "storefront/collection.html", business=business, products=products,
        categories=categories, selected_category=selected_category, settings=settings,
        sizes=sizes, colours=colours, selected_size=selected_size,
        selected_colour=selected_colour, page=page, page_count=page_count,
        search_term=search_term, min_price=min_price, max_price=max_price,
        brands=brands, selected_brand=selected_brand, selected_condition=selected_condition,
        spec_key=spec_key, spec_value=spec_value,
    )


@bp.route("/")
def home():
    business = public_business()
    settings, categories = storefront_context(business)
    featured = public_products(business).filter_by(featured=True).order_by(
        Product.created_at.desc(), Product.id.desc()
    ).limit(4).all()
    if not featured:
        featured = public_products(business).order_by(
            Product.created_at.desc(), Product.id.desc()
        ).limit(4).all()
    featured_ids = [product.id for product in featured]
    arrivals_query = public_products(business).filter_by(new_arrival=True)
    if featured_ids:
        arrivals_query = arrivals_query.filter(Product.id.notin_(featured_ids))
    new_arrivals = arrivals_query.order_by(
        Product.created_at.desc(), Product.id.desc()
    ).limit(4).all()
    displayed_ids = set(featured_ids + [product.id for product in new_arrivals])
    recent_products = public_products(business).order_by(
        Product.created_at.desc(), Product.id.desc()
    ).limit(60).all()
    products_by_category = {}
    for product in recent_products:
        if product.id not in displayed_ids and product.category_id is not None:
            products_by_category.setdefault(product.category_id, []).append(product)
    category_sections = []
    for category in categories:
        category_products = products_by_category.get(category.id, [])
        if category_products:
            category_sections.append({"category": category, "products": category_products[:4]})
    return render_template(
        "storefront/home.html", business=business, featured=featured,
        new_arrivals=new_arrivals, category_sections=category_sections,
        settings=settings, categories=categories,
    )


@bp.route("/collection")
def collection():
    business = public_business()
    query = public_products(business)
    category_id = request.args.get("category", type=int)
    selected_category = None
    selected_size = (request.args.get("size") or "").strip()
    selected_colour = (request.args.get("colour") or "").strip()
    search_term = (request.args.get("q") or "").strip()[:100]
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    selected_brand = (request.args.get("brand") or "").strip()[:120]
    selected_condition = (request.args.get("condition") or "").strip()[:40]
    spec_key = (request.args.get("spec_key") or "").strip()[:80]
    spec_value = (request.args.get("spec_value") or "").strip()[:100]
    page = max(request.args.get("page", 1, type=int), 1)
    if category_id:
        selected_category = Category.query.filter_by(id=category_id, business_id=business.id).first_or_404()
        same_name_ids = [c.id for c in Category.query.filter_by(business_id=business.id).all()
                         if " ".join((c.name or "").split()).casefold() == " ".join((selected_category.name or "").split()).casefold()]
        query = query.filter(Product.category_id.in_(same_name_ids))
    if search_term:
        pattern = f"%{search_term}%"
        query = query.filter(or_(
            Product.name.ilike(pattern),
            Product.description.ilike(pattern),
            Product.category.has(Category.name.ilike(pattern)),
            Product.brand.ilike(pattern),
            cast(Product.specifications, String).ilike(pattern),
        ))
    if selected_brand:
        query = query.filter(Product.brand.ilike(selected_brand))
    if selected_condition:
        query = query.filter(Product.condition.ilike(selected_condition))
    if spec_key and spec_value:
        query = query.filter(cast(Product.specifications, String).ilike(f"%{spec_key}%{spec_value}%"))
    price_value = func.coalesce(Product.discounted_price, Product.regular_price)
    if min_price is not None and min_price >= 0:
        query = query.filter(price_value >= min_price)
    if max_price is not None and max_price >= 0:
        query = query.filter(price_value <= max_price)
    if selected_size:
        matching = db.session.query(ProductVariant.product_id).filter(
            ProductVariant.business_id == business.id,
            ProductVariant.size.ilike(selected_size),
            ProductVariant.is_available.is_(True),
        )
        query = query.filter(Product.id.in_(matching))
    if selected_colour:
        matching = db.session.query(ProductVariant.product_id).filter(
            ProductVariant.business_id == business.id,
            ProductVariant.colour.ilike(selected_colour),
            ProductVariant.is_available.is_(True),
        )
        query = query.filter(Product.id.in_(matching))
    total = query.count()
    products = query.order_by(Product.created_at.desc(), Product.id.desc()).offset(
        (page - 1) * PAGE_SIZE
    ).limit(PAGE_SIZE).all()
    return render_listing(
        business, products, selected_category, selected_size, selected_colour,
        page, max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
        search_term=search_term, min_price=min_price, max_price=max_price,
        selected_brand=selected_brand, selected_condition=selected_condition,
        spec_key=spec_key, spec_value=spec_value,
    )


@bp.route("/category/<string:slug>")
def category(slug):
    business = public_business()
    selected_category = category_for_slug(business, slug)
    if not selected_category:
        abort(404)
    same_name_ids = [c.id for c in Category.query.filter_by(business_id=business.id).all()
                     if " ".join((c.name or "").split()).casefold() == " ".join((selected_category.name or "").split()).casefold()]
    query = public_products(business).filter(Product.category_id.in_(same_name_ids))
    selected_product_id = request.args.get("product", type=int)
    page = max(request.args.get("page", 1, type=int), 1)
    total = query.count()
    if selected_product_id:
        ordered = query.order_by(case((Product.id == selected_product_id, 0), else_=1),
                                 Product.created_at.desc(), Product.id.desc())
    else:
        ordered = query.order_by(Product.created_at.desc(), Product.id.desc())
    products = ordered.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return render_listing(
        business, products, selected_category, page=page,
        page_count=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
    )


@bp.route("/product/<string:slug>")
def product_detail(slug):
    business = public_business()
    product = public_products(business).filter_by(slug=slug).first_or_404()
    settings, categories = storefront_context(business)
    images = list(product.images or [])
    variants = [v for v in product.variants if v.is_available]
    related_query = public_products(business).filter(Product.id != product.id)
    if product.category_id:
        related_query = related_query.filter(Product.category_id == product.category_id)
    elif product.brand:
        related_query = related_query.filter(Product.brand.ilike(product.brand))
    related_products = related_query.order_by(Product.featured.desc(), Product.created_at.desc()).limit(4).all()
    return render_template(
        "storefront/product_detail.html", business=business, product=product,
        images=images, variants=variants, related_products=related_products,
        settings=settings, categories=categories,
    )


@bp.route("/wishlist")
def wishlist():
    business = public_business()
    settings, categories = storefront_context(business)
    return render_template("storefront/wishlist.html", business=business, settings=settings, categories=categories)


@bp.route("/cart")
def cart():
    business = public_business()
    settings, categories = storefront_context(business)
    return render_template(
        "storefront/cart.html", business=business,
        settings=settings, categories=categories,
    )

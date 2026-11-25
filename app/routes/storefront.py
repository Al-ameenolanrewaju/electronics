from flask import Blueprint, g, render_template, request, abort, jsonify
from sqlalchemy import String, case, cast, func, or_
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
    # Legacy categories may have inconsistent slugs; match a normalized name safely.
    normalized = " ".join(slug.replace("-", " ").split()).casefold()
    candidates = Category.query.filter_by(business_id=business.id).order_by(Category.id).all()
    return next((item for item in candidates if " ".join((item.name or "").split()).casefold() == normalized), None)


def render_listing(business, products, selected_category=None, selected_size="", selected_colour="", page=1, page_count=1, filters=None):
    settings, categories = storefront_context(business)
    variant_rows = ProductVariant.query.filter_by(
        business_id=business.id, is_available=True
    ).filter(ProductVariant.stock_quantity > 0).order_by(ProductVariant.size, ProductVariant.colour).all()
    sizes = sorted({v.size.strip() for v in variant_rows if v.size and v.size.strip()}, key=str.casefold)
    colours = sorted({v.colour.strip() for v in variant_rows if v.colour and v.colour.strip()}, key=str.casefold)
    brands = [
        brand for (brand,) in db.session.query(Product.brand).filter(
            Product.business_id == business.id,
            Product.is_published.is_(True),
            Product.brand.isnot(None),
            Product.brand != "",
        ).distinct().order_by(Product.brand).all()
    ]
    pagination_args = request.args.to_dict()
    pagination_args.pop("page", None)
    if selected_category:
        pagination_args["category"] = str(selected_category.id)
    return render_template(
        "storefront/collection.html", business=business, products=products,
        categories=categories, selected_category=selected_category, settings=settings,
        sizes=sizes, colours=colours, selected_size=selected_size,
        selected_colour=selected_colour, page=page, page_count=page_count,
        brands=brands, filters=filters or {}, pagination_args=pagination_args,
    )


@bp.route("/")
def home():
    business = public_business()
    products = public_products(business).order_by(func.random()).limit(4).all()
    settings, categories = storefront_context(business)
    return render_template(
        "storefront/home.html", business=business, featured=products,
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
    selected_brand = (request.args.get("brand") or "").strip()
    search = (request.args.get("q") or "").strip()[:120]
    minimum_price = request.args.get("min_price", type=float)
    maximum_price = request.args.get("max_price", type=float)
    available_only = request.args.get("available") == "1"
    specification_filters = {
        "spec_ram": "RAM",
        "spec_storage": "Storage",
        "spec_processor": "Processor",
        "spec_screen_size": "Screen size",
    }
    filters = {
        "q": search,
        "brand": selected_brand,
        "min_price": request.args.get("min_price", ""),
        "max_price": request.args.get("max_price", ""),
        "available": available_only,
    }
    for parameter in specification_filters:
        filters[parameter] = (request.args.get(parameter) or "").strip()[:80]
    page = max(request.args.get("page", 1, type=int), 1)
    if category_id:
        selected_category = Category.query.filter_by(id=category_id, business_id=business.id).first_or_404()
        same_name_ids = [c.id for c in Category.query.filter_by(business_id=business.id).all()
                         if " ".join((c.name or "").split()).casefold() == " ".join((selected_category.name or "").split()).casefold()]
        query = query.filter(Product.category_id.in_(same_name_ids))
    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            Product.name.ilike(term),
            Product.brand.ilike(term),
            Product.description.ilike(term),
            cast(Product.specifications, String).ilike(term),
            Product.category.has(Category.name.ilike(term)),
        ))
    if selected_brand:
        query = query.filter(Product.brand.ilike(selected_brand))
    price = func.coalesce(Product.discounted_price, Product.regular_price)
    if minimum_price is not None and minimum_price >= 0:
        query = query.filter(price >= minimum_price)
    if maximum_price is not None and maximum_price >= 0:
        query = query.filter(price <= maximum_price)
    for parameter, specification_name in specification_filters.items():
        value = filters[parameter]
        if value:
            query = query.filter(Product.specifications[specification_name].as_string().ilike(f"%{value}%"))
    if selected_size:
        matching = db.session.query(ProductVariant.product_id).filter(
            ProductVariant.business_id == business.id,
            ProductVariant.size.ilike(selected_size),
            ProductVariant.is_available.is_(True),
            ProductVariant.stock_quantity > 0,
        )
        query = query.filter(Product.id.in_(matching))
    if selected_colour:
        matching = db.session.query(ProductVariant.product_id).filter(
            ProductVariant.business_id == business.id,
            ProductVariant.colour.ilike(selected_colour),
            ProductVariant.is_available.is_(True),
            ProductVariant.stock_quantity > 0,
        )
        query = query.filter(Product.id.in_(matching))
    if available_only:
        in_stock = db.session.query(ProductVariant.product_id).filter(
            ProductVariant.business_id == business.id,
            ProductVariant.is_available.is_(True),
            ProductVariant.stock_quantity > 0,
        )
        query = query.filter(Product.id.in_(in_stock))
    total = query.count()
    products = query.order_by(func.random()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return render_listing(
        business, products, selected_category, selected_size, selected_colour,
        page, max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1), filters,
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
        ordered = query.order_by(func.random())
    products = ordered.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return render_listing(business, products, selected_category, page=page,
                          page_count=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1))


@bp.route("/product/<string:slug>")
def product_detail(slug):
    business = public_business()
    product = public_products(business).filter_by(slug=slug).first_or_404()
    settings, categories = storefront_context(business)
    images = list(product.images or [])
    variants = [v for v in product.variants if v.is_available and v.stock_quantity > 0]
    return render_template(
        "storefront/product_detail.html", business=business, product=product,
        images=images, variants=variants, settings=settings, categories=categories,
    )


@bp.route("/wishlist")
def wishlist():
    business = public_business()
    settings, categories = storefront_context(business)
    return render_template("storefront/wishlist.html", business=business, settings=settings, categories=categories)


@bp.route("/cart")
def cart():
    business = public_business()
    products = public_products(business).order_by(Product.created_at.desc(), Product.id.desc()).limit(4).all()
    settings, categories = storefront_context(business)
    return render_template(
        "storefront/home.html", business=business, featured=products,
        settings=settings, categories=categories,
    )

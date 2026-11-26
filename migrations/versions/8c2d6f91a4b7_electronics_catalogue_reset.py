"""Hide all legacy catalogue records and install electronics-only starter stock.

Revision ID: 8c2d6f91a4b7
Revises: f4a91c2d7e60
Create Date: 2026-11-26
"""
from alembic import op
import sqlalchemy as sa

revision = "8c2d6f91a4b7"
down_revision = "f4a91c2d7e60"
branch_labels = None
depends_on = None

CATEGORIES = [
    "Smartphones", "Laptops", "Desktop Computers", "Tablets",
    "Smartwatches", "Headphones", "Speakers", "Cameras",
    "Gaming Consoles", "Gaming Accessories", "Televisions",
    "Monitors", "Keyboards and Mice", "Power Banks",
    "Chargers and Cables", "Storage Devices", "Home Appliances",
    "Electronics Accessories",
]

STARTER_PRODUCTS = [
    ("Nova Pro 15", "Smartphones", "Samsung", 420000, "6.7-inch OLED display, 256GB storage and 12GB RAM.", "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=1200&q=85", "256 GB", "EL-101"),
    ("AeroBook 14", "Laptops", "Apple", 760000, "Lightweight laptop with 16GB memory and a 512GB SSD.", "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=1200&q=85", "512 GB", "EL-102"),
    ("Slate Pad 11", "Tablets", "Apple", 330000, "11-inch tablet with 128GB storage for work and entertainment.", "https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?auto=format&fit=crop&w=1200&q=85", "128 GB", "EL-103"),
    ("Pulse Watch S", "Smartwatches", "Samsung", 185000, "Smartwatch with AMOLED display, GPS and activity tracking.", "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=1200&q=85", "42 mm", "EL-104"),
    ("Studio Quiet Pro", "Headphones", "Sony", 145000, "Wireless over-ear headphones with active noise cancellation.", "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=1200&q=85", "Wireless", "EL-105"),
    ("Room Audio Mini", "Speakers", "JBL", 98000, "Portable Bluetooth speaker with room-filling stereo sound.", "https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?auto=format&fit=crop&w=1200&q=85", "Bluetooth", "EL-106"),
]


def upgrade():
    bind = op.get_bind()
    business = bind.execute(
        sa.text("""
            SELECT id FROM business
             WHERE lower(slug) = 'sulex' OR lower(name) LIKE '%sulex%'
             ORDER BY id LIMIT 1
        """)
    ).first()
    if not business:
        return
    business_id = business[0]

    # Keep all previous product/order history in the database, but remove every
    # pre-existing catalogue item from public listings and featured/arrival slots.
    bind.execute(
        sa.text("""
            UPDATE product
               SET is_published = FALSE, featured = FALSE, new_arrival = FALSE
             WHERE business_id = :business_id
        """),
        {"business_id": business_id},
    )

    # Remove clothing-only category labels, including singular/plural spellings.
    clothing_patterns = [
        "%abaya%", "%agbada%", "%blouse%", "%dress%", "%hijab%",
        "%jalabia%", "%kaftan%", "%cap%", "%skirt%", "%trouser%",
        "%shirt%", "%gown%", "%clothing%", "%fashion%", "%wear%",
        "%daviva%",
    ]
    category_rows = bind.execute(
        sa.text("SELECT id, name FROM category WHERE business_id = :business_id"),
        {"business_id": business_id},
    ).all()
    clothing_ids = [
        row[0] for row in category_rows
        if any(pattern.strip("%") in (row[1] or "").strip().casefold() for pattern in clothing_patterns)
    ]
    if clothing_ids:
        bind.execute(
            sa.text("DELETE FROM category WHERE business_id = :business_id AND id IN :ids")
            .bindparams(sa.bindparam("ids", expanding=True)),
            {"business_id": business_id, "ids": clothing_ids},
        )

    existing = {
        (row[0] or "").strip().casefold(): row[1]
        for row in bind.execute(
            sa.text("SELECT name, id FROM category WHERE business_id = :business_id"),
            {"business_id": business_id},
        ).all()
    }
    for name in CATEGORIES:
        if name.casefold() not in existing:
            slug = "-".join(name.lower().split())
            category_id = bind.execute(
                sa.text("""
                    INSERT INTO category (business_id, name, slug, gender, created_at, updated_at)
                    VALUES (:business_id, :name, :slug, 'All', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                """),
                {"business_id": business_id, "name": name, "slug": slug},
            ).scalar_one()
            existing[name.casefold()] = category_id

    for index, (name, category_name, brand, price, description, image_url, configuration, sku) in enumerate(STARTER_PRODUCTS):
        product_id = bind.execute(
            sa.text("""
                INSERT INTO product
                    (business_id, category_id, name, slug, description, regular_price,
                     discounted_price, gender, fashion_type, featured, new_arrival,
                     is_published, sku, brand, condition, created_at, updated_at)
                VALUES
                    (:business_id, :category_id, :name, :slug, :description, :price,
                     NULL, 'Unisex', 'Device', :featured, TRUE, TRUE, :sku, :brand,
                     'New', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """),
            {
                "business_id": business_id,
                "category_id": existing[category_name.casefold()],
                "name": name,
                "slug": "-".join(name.lower().split()),
                "description": description,
                "price": price,
                "featured": index < 4,
                "sku": sku,
                "brand": brand,
            },
        ).scalar_one()
        bind.execute(
            sa.text("""
                INSERT INTO product_image
                    (business_id, product_id, url, alt_text, sort_order, created_at, updated_at)
                VALUES
                    (:business_id, :product_id, :url, :alt_text, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {"business_id": business_id, "product_id": product_id, "url": image_url, "alt_text": name},
        )
        bind.execute(
            sa.text("""
                INSERT INTO product_variant
                    (business_id, product_id, size, colour, sku, stock_quantity,
                     is_available, created_at, updated_at)
                VALUES
                    (:business_id, :product_id, :configuration, 'Black', :sku, 8,
                     TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {"business_id": business_id, "product_id": product_id, "configuration": configuration, "sku": sku + "-BK"},
        )


def downgrade():
    # Do not republish the previous clothing catalogue automatically.
    pass

"""Replace legacy clothing storefront content with electronics defaults.

Revision ID: f4a91c2d7e60
Revises: e3f1a7c2d901
Create Date: 2026-11-26
"""
from alembic import op
import sqlalchemy as sa

revision = "f4a91c2d7e60"
down_revision = "e3f1a7c2d901"
branch_labels = None
depends_on = None


ELECTRONICS_CATEGORIES = [
    "Smartphones", "Laptops", "Desktop Computers", "Tablets",
    "Smartwatches", "Headphones", "Speakers", "Cameras",
    "Gaming Consoles", "Gaming Accessories", "Televisions",
    "Monitors", "Keyboards and Mice", "Power Banks",
    "Chargers and Cables", "Storage Devices", "Home Appliances",
    "Electronics Accessories",
]

CLOTHING_CATEGORIES = [
    "Abayas", "Agbada", "Blouses", "Dresses", "Hijabs", "Jalabias",
    "Kaftans", "Caps", "Skirts", "Trousers", "Shirts", "Gowns",
    "Clothing", "Fashion", "Fashion Accessories", "Accessories",
    "Men's Wear", "Women's Wear", "Islamic Wear",
]


def upgrade():
    bind = op.get_bind()

    business = bind.execute(
        sa.text("SELECT id FROM business WHERE slug = 'sulex' LIMIT 1")
    ).first()
    if not business:
        return
    business_id = business[0]

    # Remove the uploaded clothing-logo banner from the electronics hero.
    bind.execute(
        sa.text("""
            UPDATE business
               SET description = 'Sulex premium electronics store',
                   banner_url = NULL,
                   banner_public_id = NULL,
                   banner_data = NULL,
                   banner_mime_type = NULL
             WHERE id = :business_id
        """),
        {"business_id": business_id},
    )

    bind.execute(
        sa.text("""
            UPDATE store_settings
               SET announcement = NULL,
                   tagline = 'Technology, thoughtfully selected',
                   hero_title = 'Technology for better living.',
                   about_text = 'Discover premium smartphones, laptops, audio, gaming and smart devices selected for performance and everyday reliability.',
                   hero_cta = 'Shop all devices',
                   catalogue_eyebrow = 'Featured devices',
                   catalogue_title = 'Essential technology, beautifully selected.',
                   empty_title = 'Your next favourite device belongs here.',
                   empty_text = 'Our electronics collection is being prepared. Check back soon.',
                   seo_title = 'Sulex | Premium Electronics',
                   seo_description = 'Shop smartphones, laptops, audio, gaming and smart devices at Sulex.'
             WHERE business_id = :business_id
        """),
        {"business_id": business_id},
    )

    clothing_ids = bind.execute(
        sa.text("""
            SELECT id FROM category
             WHERE business_id = :business_id
               AND lower(trim(name)) IN :names
        """).bindparams(sa.bindparam("names", expanding=True)),
        {"business_id": business_id, "names": [name.lower() for name in CLOTHING_CATEGORIES]},
    ).scalars().all()

    if clothing_ids:
        bind.execute(
            sa.text("""
                UPDATE product
                   SET is_published = FALSE, category_id = NULL
                 WHERE business_id = :business_id
                   AND category_id IN :category_ids
            """).bindparams(sa.bindparam("category_ids", expanding=True)),
            {"business_id": business_id, "category_ids": clothing_ids},
        )
        bind.execute(
            sa.text("DELETE FROM category WHERE business_id = :business_id AND id IN :category_ids")
            .bindparams(sa.bindparam("category_ids", expanding=True)),
            {"business_id": business_id, "category_ids": clothing_ids},
        )

    existing = {
        row[0].strip().casefold()
        for row in bind.execute(
            sa.text("SELECT name FROM category WHERE business_id = :business_id"),
            {"business_id": business_id},
        ).all()
    }
    for name in ELECTRONICS_CATEGORIES:
        if name.casefold() in existing:
            continue
        slug = "-".join(name.lower().split())
        bind.execute(
            sa.text("""
                INSERT INTO category (business_id, name, slug, gender, created_at, updated_at)
                VALUES (:business_id, :name, :slug, 'All', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {"business_id": business_id, "name": name, "slug": slug},
        )


    # Give a newly cleaned storefront a small, clearly electronics-only starter catalogue.
    published_count = bind.execute(
        sa.text("SELECT count(*) FROM product WHERE business_id = :business_id AND is_published = TRUE"),
        {"business_id": business_id},
    ).scalar_one()
    if published_count == 0:
        category_ids = {
            row[0]: row[1]
            for row in bind.execute(
                sa.text("SELECT name, id FROM category WHERE business_id = :business_id"),
                {"business_id": business_id},
            ).all()
        }
        starter_products = [
            ("Nova Pro 15", "Smartphones", "Samsung", 420000, "6.7-inch OLED display, 256GB storage and 12GB RAM.", "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=1200&q=85", "256 GB", "EL-001"),
            ("AeroBook 14", "Laptops", "Apple", 760000, "Lightweight laptop with 16GB memory and a 512GB SSD.", "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=1200&q=85", "512 GB", "EL-002"),
            ("Slate Pad 11", "Tablets", "Apple", 330000, "11-inch tablet with 128GB storage for work and entertainment.", "https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?auto=format&fit=crop&w=1200&q=85", "128 GB", "EL-003"),
            ("Pulse Watch S", "Smartwatches", "Samsung", 185000, "Smartwatch with AMOLED display, GPS and activity tracking.", "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=1200&q=85", "42 mm", "EL-004"),
            ("Studio Quiet Pro", "Headphones", "Sony", 145000, "Wireless over-ear headphones with active noise cancellation.", "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=1200&q=85", "Wireless", "EL-005"),
            ("Room Audio Mini", "Speakers", "JBL", 98000, "Portable Bluetooth speaker with room-filling stereo sound.", "https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?auto=format&fit=crop&w=1200&q=85", "Bluetooth", "EL-006"),
        ]
        for index, (name, category_name, brand, price, description, image_url, configuration, sku) in enumerate(starter_products):
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
                    "category_id": category_ids[category_name],
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
    # Deliberately do not restore unpublished clothing catalogue content or banner assets.
    pass

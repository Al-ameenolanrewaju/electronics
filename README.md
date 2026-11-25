# Electronics Store Catalogue

A premium single-business electronics catalogue built with Flask. Customers can
browse products, view photos and available configurations/colours, then send an order
request directly to the shop's WhatsApp number. Customers do not need accounts,
and the application does not take payments.

The private dashboard is for one shop owner to manage products, categories,
images, inventory and store details. Product records include a brand and
category-relevant specifications; variants store configuration, colour, price
override and stock.

## Local setup (Windows PowerShell)

```powershell
py -3 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
$env:SECRET_KEY = "replace-with-a-random-secret-at-least-32-characters"
$env:DATABASE_URL = "sqlite:///electronics_store.db"
$env:COOKIE_SECURE = "false"
python -m flask --app "app:create_app()" db upgrade
python -m flask --app "app:create_app()" run
```

Open `http://127.0.0.1:5000/login` for the owner login. The app requires a
`SECRET_KEY` of at least 32 characters outside test mode.
Running `python run.py` loads environment variables from a local `.env` file.
Keep `.env` private and do not commit it.

## Create the shop and owner account

Run `python -m flask --app "app:create_app()" shell` using the same environment variables,
then create the single shop and its owner:

```python
from app import db
from app.models import Business, User

shop = Business(
    name="Your Electronics Store",
    slug="your-electronics-store",
    description="Your store description",
    whatsapp_number="2348012345678",
)
owner = User(
    name="Store Owner",
    email="owner@example.com",
    role="OWNER",
)
owner.set_password("use-a-unique-password-at-least-12-characters")
shop.users.append(owner)
db.session.add(shop)
db.session.commit()
```

The app automatically loads the first active business from the database on
the Render URL and any hostname that is not explicitly mapped to a connected
custom domain. You do not need to configure a store slug. Keep only one active
business in the database for this single-shop setup. A connected custom domain
can still point to the shop.

## Configuration

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Required outside testing; at least 32 random characters |
| `DATABASE_URL` | PostgreSQL in production; SQLite for local development |
| `APP_ENV` | Set to `production` on Render to enforce production database requirements |
| `COOKIE_SECURE` | Keep `true` on HTTPS; set `false` only for local HTTP |
| `UPLOAD_FOLDER` | Legacy image directory used only to serve images uploaded by older versions |
| `RENDER_API_KEY`, `RENDER_SERVICE_ID` | Optional existing custom-domain integration |

New product images and business logos validate JPEG, PNG and WebP signatures and are stored as binary data in PostgreSQL. They remain available across Render redeploys without Cloudinary or a persistent image disk. The legacy `/media/<filename>` route remains available for images uploaded by older versions; those old files still require their original persistent disk until re-uploaded.

## Deploy to Render

1. Connect this repository to a Render Web Service.
2. Build command: `pip install -r requirements.txt`.
3. Start command: `gunicorn 'app:create_app()'`.
4. Configure `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL` and `COOKIE_SECURE=true`.
5. Run `python -m flask --app "app:create_app()" db upgrade` once from the Render shell.
6. Create the shop and owner account with the Flask shell if they do not
   already exist.
7. Visit `/health` to check application and database readiness.

The repository Procfile also sets the web start command to
`gunicorn 'app:create_app()'`. If the Render dashboard has a custom Start
Command saved, it must match this command because dashboard settings override
the Procfile.

## Electronics catalogue data

The owner dashboard's product form accepts technical specifications as one
`Label: value` entry per line (for example `RAM: 8 GB` and `Storage: 256 GB`).
Only specifications entered for a product are shown on its details page.
Brand, category, price and common specifications can be combined in catalogue
filters. Use the variant inventory page to set actual stock; new configurations
start at zero stock.

For a fresh preview store, `python -m flask --app "app:create_app()" seed-electronics`
adds a one-time catalogue of sample products. It does nothing if the store
already has products.

## Customer ordering

1. Customer browses the catalogue and adds products to the locally saved cart.
2. The cart opens a WhatsApp message with the selected products and subtotal.
3. The shop owner confirms availability, delivery and payment directly with
   the customer in WhatsApp.

WhatsApp checkout does not create an order record, reserve stock, or deduct
inventory. The owner confirms the order and updates stock from the dashboard.
The existing order-related tables remain available for compatibility.

## Tests

```powershell
python -m pytest -q
```
